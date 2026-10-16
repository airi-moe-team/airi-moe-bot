"""Lock de instancia única basado en `flock` (best-effort, sin dependencias).

Dos procesos del bot sobre el mismo `data/` se pisarían los JSON: este lock
lo evita a nivel de sistema operativo. El SO libera el lock automáticamente al
morir el proceso, así que un cierre abrupto no deja el fichero "atascado".
"""

from __future__ import annotations

import fcntl
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class InstanceLock:
    """Lock exclusivo de proceso (flock). El SO lo libera al morir el proceso."""

    def __init__(self, path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        """Intenta tomar el lock. Devuelve True si se obtuvo, False si ya hay otro."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "w")
        try:
            fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    def release(self) -> None:
        """Libera el lock (idempotente)."""
        if self._fh is not None:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            except OSError:
                pass
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "InstanceLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
