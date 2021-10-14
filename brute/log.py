"""
Logging setup
"""
import sys

import arrow
from tqdm import tqdm

# all are 5 characters long for easier reading/alignment
DEBUG_LABEL = "DEBUG"
INFO_LABEL = "INFO "
WARN_LABEL = "WARN "
ERROR_LABEL = "ERROR"


def _log(*, label: str, msg: str) -> None:
    timestr = arrow.now().isoformat()
    out = f"{timestr} - {label} - {msg}"
    tqdm.write(out, file=sys.stderr)


def debug(msg: str) -> None:
    _log(label=DEBUG_LABEL, msg=msg)


def info(msg: str) -> None:
    _log(label=INFO_LABEL, msg=msg)


def warn(msg: str) -> None:
    _log(label=WARN_LABEL, msg=msg)


def error(msg: str) -> None:
    _log(label=ERROR_LABEL, msg=msg)
