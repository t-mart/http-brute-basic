"""
A little testing server
"""
import base64
import binascii
import sys
from typing import Optional, Tuple

import typer
import uvicorn
from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    BaseUser,
    SimpleUser,
    requires,
)
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection, Request
from starlette.responses import PlainTextResponse, Response

CREDENTIAL_PAIRS: list[tuple[str, str]] = []


class BasicAuthBackend(AuthenticationBackend):
    async def authenticate(
        self, request: HTTPConnection
    ) -> Optional[Tuple[AuthCredentials, BaseUser]]:
        if "Authorization" not in request.headers:
            return None

        auth = request.headers["Authorization"]
        try:
            scheme, credentials = auth.split()
            if scheme.lower() != "basic":
                return None
            decoded = base64.b64decode(credentials).decode("ascii")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            raise AuthenticationError("Invalid basic auth credentials")

        username, password = decoded.split(":", maxsplit=1)

        if (username, password) not in CREDENTIAL_PAIRS:
            raise AuthenticationError("Invalid basic auth credentials")

        return AuthCredentials(["authenticated"]), SimpleUser(username)


def on_auth_error(request: Request, exc: Exception) -> Response:
    return PlainTextResponse(str(exc), status_code=401)


app = Starlette()
app.add_middleware(
    AuthenticationMiddleware,
    backend=BasicAuthBackend(),
    on_error=on_auth_error,
)


@app.route("/")
@requires("authenticated")
async def homepage(request: Request) -> Response:
    return PlainTextResponse("welcome")


def main(
    host: str = typer.Option(
        "127.0.0.1",
        help="Host to serve on",
    ),
    port: int = typer.Option(
        5000,
        help="Port to serve on",
    ),
    credentials: list[str] = typer.Option(
        [],
        "-c",
        "--credential",
        help=(
            'A credential pair in the form of "username:password". This option may '
            "be provided mulitple times. (And it may also be provided zero times, "
            "which will set the server to have no working credentials.) Note: "
            "usernames must not contain colons."
        ),
    ),
) -> None:
    """
    A little test server to brute force against.
    """
    global CREDENTIAL_PAIRS
    for cred in credentials:
        try:
            username, password = cred.split(":", maxsplit=1)
        except ValueError:
            print('credential pairs must be in the form of "<username>:<password>"')
            sys.exit(1)
        CREDENTIAL_PAIRS.append((username, password))

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    typer.run(main)
