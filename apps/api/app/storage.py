"""Private storage for uploaded submission ZIPs."""
import hashlib
import os
from pathlib import Path

from .config import SUBMISSION_DIR


class TooLarge(Exception):
    pass


def path_for(key):
    return SUBMISSION_DIR / key[:2] / f"{key}.zip"


def temporary_path(key):
    return SUBMISSION_DIR / "incoming" / f"{key}.part"


async def receive(stream, target: Path, limit):
    """Streams a request body to disk, stopping as soon as it exceeds `limit`.
    Returns (size, sha256)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with open(target, "wb") as output:
        async for chunk in stream:
            size += len(chunk)
            if size > limit:
                raise TooLarge
            digest.update(chunk)
            output.write(chunk)
    return size, digest.hexdigest()


def commit(temporary: Path, key):
    final = path_for(key)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary, final)
    return final


def discard(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass
