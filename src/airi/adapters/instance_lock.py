"""Bloqueo de escritor único por directorio de datos."""

from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path


class InstanceAlreadyRunningError(RuntimeError):
    """Otra instancia ya mantiene el bloqueo del estado."""


class InstanceLock:
    """Bloqueo exclusivo no bloqueante sobre un archivo local."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            owner = self._read_owner(fd)
            os.close(fd)
            raise InstanceAlreadyRunningError(
                "otra instancia de Airi ya está activa"
                + (f" (pid {owner})" if owner else "")
            ) from exc
        except OSError as exc:
            os.close(fd)
            raise InstanceAlreadyRunningError(
                f"no se pudo adquirir el bloqueo {self.path}: {exc}"
            ) from exc

        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\nstarted_at={time.time():.0f}\n".encode())
            os.fsync(fd)
        except OSError:
            pass
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    @staticmethod
    def _read_owner(fd: int) -> str:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            content = os.read(fd, 256).decode("utf-8", "replace")
        except OSError:
            return ""
        for line in content.splitlines():
            if line.startswith("pid="):
                return line.partition("=")[2].strip()
        return ""
