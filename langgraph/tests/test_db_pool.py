from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import psycopg
import pytest
from psycopg_pool import PoolTimeout

from aes_agent.auth import DatabaseSettings, PostgresAuthRepository
from aes_agent.db_pool import close_database_pools, get_database_pool
from aes_agent.runs import PostgresRunRepository, RunStoreUnavailable


@pytest.fixture
def settings():
    return DatabaseSettings("test-db", 5432, "aes", "aes_app", "test-only", 5)


def test_concurrent_auth_and_run_access_reuse_one_bounded_pool(settings):
    close_database_pools()
    try:
        with patch("psycopg_pool.ConnectionPool") as factory, patch(
            "aes_agent.runs.database_settings", return_value=settings,
        ):
            with ThreadPoolExecutor(max_workers=8) as executor:
                pools = list(executor.map(lambda _: get_database_pool(settings), range(24)))
            factory.assert_called_once()
            assert all(pool is factory.return_value for pool in pools)
            kwargs = factory.call_args.kwargs
            assert kwargs["min_size"] == 2
            assert kwargs["max_size"] == 8
            assert kwargs["check"] == factory.check_connection
            assert kwargs["kwargs"]["application_name"] == "aes-langgraph"
            factory.return_value.open.assert_called_once_with(wait=False)
            PostgresAuthRepository(settings)._connect()
            PostgresRunRepository()._connect()
            assert factory.return_value.connection.call_count == 2
    finally:
        close_database_pools()
    factory.return_value.close.assert_called_once_with(timeout=2)


def test_pool_configuration_is_applied(settings, monkeypatch):
    monkeypatch.setenv("AES_DB_POOL_MIN_SIZE", "3")
    monkeypatch.setenv("AES_DB_POOL_MAX_SIZE", "6")
    monkeypatch.setenv("AES_DB_POOL_TIMEOUT", "7")
    close_database_pools()
    try:
        with patch("psycopg_pool.ConnectionPool") as factory:
            get_database_pool(settings)
            assert factory.call_args.kwargs["min_size"] == 3
            assert factory.call_args.kwargs["max_size"] == 6
            assert factory.call_args.kwargs["timeout"] == 7
    finally:
        close_database_pools()


def test_pool_checkout_timeout_is_a_recoverable_run_store_error():
    repository = PostgresRunRepository()
    checkout = Mock()
    checkout.__enter__ = Mock(side_effect=PoolTimeout("test timeout"))
    checkout.__exit__ = Mock()
    with patch.object(repository, "_connect", return_value=checkout):
        with pytest.raises(RunStoreUnavailable) as error:
            repository.heartbeat("run", "worker")
    assert isinstance(error.value.__cause__, PoolTimeout)


def test_query_failure_returns_connection_without_replaying_statement():
    repository = PostgresRunRepository()
    cursor = Mock()
    cursor.execute.side_effect = psycopg.OperationalError("connection lost")
    connection = Mock()
    transaction_exit = []

    @contextmanager
    def cursor_context():
        yield cursor

    @contextmanager
    def checkout():
        try:
            yield connection
        finally:
            transaction_exit.append(True)

    connection.cursor = cursor_context
    with patch.object(repository, "_connect", side_effect=checkout):
        with pytest.raises(RunStoreUnavailable):
            repository.claim("worker")
    cursor.execute.assert_called_once()
    assert transaction_exit == [True]


def test_finish_requires_database_acknowledgement_and_allows_same_result_retry():
    repository = PostgresRunRepository()
    with patch.object(repository, "_query", return_value={"id": "run"}) as query:
        assert repository.finish("run", "worker", "completed", {"answer": "done"}, None)
        sql, parameters = query.call_args.args
        assert "RETURNING id" in sql
        assert "status IN ('running', %s)" in sql
        assert parameters[-1] == "completed"
    with patch.object(repository, "_query", return_value=None):
        assert not repository.finish("run", "worker", "completed", {}, None)
