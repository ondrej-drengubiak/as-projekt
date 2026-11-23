from common.db import thread_conn

def conn():
    return thread_conn("monolith.db")
