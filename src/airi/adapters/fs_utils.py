"""Primitivas de sincronización con el sistema de archivos."""

from __future__ import annotations

import os
from pathlib import Path


def fsync_dir(path: str | os.PathLike[str]) -> None:
    """Sincroniza un directorio tras un reemplazo atómico (mejor esfuerzo).

    No todos los sistemas permiten abrir o sincronizar directorios; en esos
    casos la operación se considera opcional y no rompe la escritura.
    """
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(Path(path), flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
