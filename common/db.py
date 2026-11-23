import os, sqlite3, threading

_tl = threading.local()

def data_dir():
    return os.environ.get("DATA_DIR", "data/run")

def connect(path):
    c = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def thread_conn(name):
    """One connection per worker thread and per database file."""
    d = getattr(_tl, "d", None)
    if d is None:
        d = _tl.d = {}
    if name not in d:
        d[name] = connect(os.path.join(data_dir(), name))
    return d[name]
