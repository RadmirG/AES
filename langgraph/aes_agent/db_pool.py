"""Process-local PostgreSQL connections shared by auth and durable run storage."""
from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aes_agent.auth import DatabaseSettings
    from psycopg_pool import ConnectionPool

logger = logging.getLogger("aes_agent.db_pool")
_lock = threading.Lock()
_pools: dict[DatabaseSettings, ConnectionPool] = {}
_stopping = False


def start_database_pools() -> None:
    global _stopping
    with _lock:
        _stopping = False


def database_pools_stopping() -> bool:
    with _lock:
        return _stopping


def get_database_pool(settings: DatabaseSettings) -> ConnectionPool:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool, PoolClosed

    with _lock:
        if _stopping:
            raise PoolClosed("AES database pools are shutting down.")
        pool = _pools.get(settings)
        if pool is not None and pool.closed is True:
            logger.warning("Replacing unexpectedly closed PostgreSQL pool.")
            pool = None
        if pool is None:
            minimum = max(1, int(os.getenv("AES_DB_POOL_MIN_SIZE", "2")))
            maximum = max(minimum, int(os.getenv("AES_DB_POOL_MAX_SIZE", "8")))
            timeout = max(1.0, float(os.getenv("AES_DB_POOL_TIMEOUT", "10")))
            pool = ConnectionPool(
                kwargs={
                    "host": settings.host, "port": settings.port,
                    "dbname": settings.database, "user": settings.user,
                    "password": settings.password,
                    "connect_timeout": settings.connect_timeout_seconds,
                    "options": "-c statement_timeout=10000",
                    "application_name": "aes-langgraph",
                    "row_factory": dict_row,
                },
                name="aes-db", min_size=minimum, max_size=maximum,
                timeout=timeout, max_waiting=32,
                check=ConnectionPool.check_connection,
                open=False,
            )
            pool.open(wait=False)
            _pools[settings] = pool
            logger.info(
                "PostgreSQL pool opened: min_size=%s max_size=%s checkout_timeout_seconds=%s",
                minimum, maximum, timeout,
            )
        return pool


def close_database_pools(*, shutdown: bool = False) -> None:
    global _stopping
    with _lock:
        if shutdown:
            _stopping = True
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close(timeout=2)


atexit.register(close_database_pools, shutdown=True)
