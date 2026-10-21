import sqlite3
from pathlib import Path

MMAP_SIZE = 2 * 1024**3


def connect(path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        # Card rows are large (~4 KB); memory-mapped reads make full scans ~100x faster than
        # page-by-page reads, and the OS keeps the mapping warm between connections.
        conn.execute(f"PRAGMA mmap_size = {MMAP_SIZE}")
    return conn
