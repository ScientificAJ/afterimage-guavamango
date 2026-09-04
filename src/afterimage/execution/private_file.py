from __future__ import annotations

import os
import stat
from pathlib import Path


class PrivateFileMissing(FileNotFoundError):
    pass


class PrivateFileInvalid(RuntimeError):
    pass


def read_private_bytes(path: str | Path, *, maximum_bytes: int = 65_536) -> bytes:
    """Read a small owner-only regular file without following its final symlink."""
    target = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags)
    except FileNotFoundError as exc:
        raise PrivateFileMissing(str(target)) from exc
    except OSError as exc:
        raise PrivateFileInvalid(str(target)) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PrivateFileInvalid(str(target))
        if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
            raise PrivateFileInvalid(str(target))
        payload = os.read(descriptor, maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise PrivateFileInvalid(str(target))
        return payload
    except OSError as exc:
        raise PrivateFileInvalid(str(target)) from exc
    finally:
        os.close(descriptor)


def read_private_text(path: str | Path, *, maximum_bytes: int = 65_536) -> str:
    try:
        return read_private_bytes(path, maximum_bytes=maximum_bytes).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PrivateFileInvalid(str(path)) from exc
