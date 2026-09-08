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


def get_database_pool(settings: DatabaseSettings) -> ConnectionPool:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    with _lock:
        pool = _pools.get(settings)
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


def close_database_pools() -> None:
    with _lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close(timeout=2)


atexit.register(close_database_pools)
