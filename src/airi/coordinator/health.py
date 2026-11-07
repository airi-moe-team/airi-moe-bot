"""Container health: a recent authenticated coordinator/Discord heartbeat."""

import os
import sqlite3
import time
from pathlib import Path


def main():
    root = Path(os.getenv("AIRI_DATA_DIR") or os.getenv("DATA_DIR", "data"))
    with sqlite3.connect(f"file:{root / 'coordination.sqlite3'}?mode=ro", uri=True) as db:
        row = db.execute("SELECT seen FROM health WHERE id=1").fetchone()
    return 0 if row and time.time() - row[0] < 45 else 1


if __name__ == "__main__":
    raise SystemExit(main())
