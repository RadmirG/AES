from __future__ import annotations

import hashlib
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Callable, Dict, List, Protocol


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,63}$")
GENERIC_LOGIN_ERROR = "Invalid user name or password."


class AuthenticationError(Exception):
    """Base exception for the AES authentication boundary."""


class InvalidCredentialsError(AuthenticationError):
    pass


class InvalidUserDataError(AuthenticationError):
    pass


class UserAlreadyExistsError(AuthenticationError):
    pass


class AuthenticationBackendError(AuthenticationError):
    pass


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    display_name: str
    status: str
    created_at: datetime

    def public_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "username": self.username,
            "displayName": self.display_name,
            "createdAt": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class LoginResult:
    user: AuthUser
    session_token: str
    expires_at: datetime


@dataclass(frozen=True)
class CookieSettings:
    name: str
    secure: bool
    same_site: str
    ttl_seconds: int


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str
    connect_timeout_seconds: int


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str:
        ...

    def verify(self, password_hash: str, password: str) -> bool:
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        ...


class AuthRepository(Protocol):
    def ping(self) -> None:
        ...

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> AuthUser:
        ...

    def get_user_by_username(self, username: str) -> tuple[AuthUser, str] | None:
        ...

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        ...

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        ...

    def get_user_by_session_hash(self, token_hash: str) -> AuthUser | None:
        ...

    def touch_session(self, token_hash: str) -> None:
        ...

    def revoke_session(self, token_hash: str) -> None:
        ...


class Argon2idPasswordHasher:
    """Lazy Argon2id adapter so repository unit tests need no native packages."""

    def __init__(self) -> None:
        try:
            from argon2 import PasswordHasher as ArgonPasswordHasher
        except ImportError as exc:
            raise AuthenticationBackendError(
                "argon2-cffi is required for AES authentication."
            ) from exc

        self._hasher = ArgonPasswordHasher(
            time_cost=2,
            memory_cost=19_456,
            parallelism=1,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, password: str) -> str:
        return str(self._hasher.hash(password))

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return bool(self._hasher.verify(password_hash, password))
        except Exception:
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return bool(self._hasher.check_needs_rehash(password_hash))
        except Exception:
            return False


class PostgresAuthRepository:
    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self.settings = settings or database_settings()

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise AuthenticationBackendError(
                "psycopg is required for AES database access."
            ) from exc

        try:
            return psycopg.connect(
                host=self.settings.host,
                port=self.settings.port,
                dbname=self.settings.database,
                user=self.settings.user,
                password=self.settings.password,
                connect_timeout=self.settings.connect_timeout_seconds,
                row_factory=dict_row,
            )
        except Exception as exc:
            raise AuthenticationBackendError(
                "Authentication database is unavailable."
            ) from exc

    def ping(self) -> None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
        except AuthenticationBackendError:
            raise
        except Exception as exc:
            raise AuthenticationBackendError(
                "Authentication database health check failed."
            ) from exc

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> AuthUser:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO identity.app_user (
                            id, username, display_name, password_hash
                        ) VALUES (%s, %s, %s, %s)
                        RETURNING id, username, display_name, status, created_at
                        """,
                        (user_id, username, display_name, password_hash),
                    )
                    row = cursor.fetchone()
        except AuthenticationBackendError:
            raise
        except Exception as exc:
            if getattr(exc, "sqlstate", "") == "23505":
                raise UserAlreadyExistsError(
                    "A user with this name already exists."
                ) from exc
            raise AuthenticationBackendError("Could not create AES user.") from exc

        return _user_from_row(row)

    def get_user_by_username(self, username: str) -> tuple[AuthUser, str] | None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, username, display_name, status, created_at,
                               password_hash
                        FROM identity.app_user
                        WHERE username = %s
                        """,
                        (username,),
                    )
                    row = cursor.fetchone()
        except AuthenticationBackendError:
            raise
        except Exception as exc:
            raise AuthenticationBackendError("Could not read AES user.") from exc

        if not row:
            return None
        return _user_from_row(row), str(row["password_hash"])

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        self._execute_write(
            "UPDATE identity.app_user SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
            "Could not update password hash.",
        )

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        self._execute_write(
            """
            INSERT INTO identity.auth_session (
                id, user_id, token_hash, expires_at
            ) VALUES (%s, %s, %s, %s)
            """,
            (session_id, user_id, token_hash, expires_at),
            "Could not create authentication session.",
        )

    def get_user_by_session_hash(self, token_hash: str) -> AuthUser | None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT u.id, u.username, u.display_name, u.status,
                               u.created_at
                        FROM identity.auth_session AS s
                        JOIN identity.app_user AS u ON u.id = s.user_id
                        WHERE s.token_hash = %s
                          AND s.revoked_at IS NULL
                          AND s.expires_at > now()
                          AND u.status = 'active'
                        """,
                        (token_hash,),
                    )
                    row = cursor.fetchone()
        except AuthenticationBackendError:
            raise
        except Exception as exc:
            raise AuthenticationBackendError(
                "Could not validate authentication session."
            ) from exc

        return _user_from_row(row) if row else None

    def touch_session(self, token_hash: str) -> None:
        self._execute_write(
            """
            UPDATE identity.auth_session
            SET last_seen_at = now()
            WHERE token_hash = %s
              AND last_seen_at < now() - interval '5 minutes'
            """,
            (token_hash,),
            "Could not update authentication session.",
        )

    def revoke_session(self, token_hash: str) -> None:
        self._execute_write(
            """
            UPDATE identity.auth_session
            SET revoked_at = COALESCE(revoked_at, now())
            WHERE token_hash = %s
            """,
            (token_hash,),
            "Could not revoke authentication session.",
        )

    def _execute_write(
        self,
        statement: str,
        parameters: tuple[Any, ...],
        error_message: str,
    ) -> None:
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(statement, parameters)
        except AuthenticationBackendError:
            raise
        except Exception as exc:
            raise AuthenticationBackendError(error_message) from exc


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        password_hasher: PasswordHasher,
    ) -> None:
        self.repository = repository
        self.password_hasher = password_hasher
        self._dummy_password_hash = password_hasher.hash(
            secrets.token_urlsafe(24)
        )

    def ping(self) -> None:
        self.repository.ping()

    def create_user(
        self,
        *,
        username: str,
        display_name: str,
        password: str,
    ) -> AuthUser:
        normalized_username = normalize_username(username)
        validate_password(password)
        normalized_display_name = display_name.strip() or normalized_username
        if len(normalized_display_name) > 120:
            raise InvalidUserDataError(
                "Display name must be at most 120 characters."
            )

        return self.repository.create_user(
            user_id=str(uuid.uuid4()),
            username=normalized_username,
            display_name=normalized_display_name,
            password_hash=self.password_hasher.hash(password),
        )

    def login(
        self,
        *,
        username: str,
        password: str,
        ttl_seconds: int,
    ) -> LoginResult:
        try:
            normalized_username = normalize_username(username)
        except InvalidUserDataError as exc:
            self.password_hasher.verify(self._dummy_password_hash, password)
            raise InvalidCredentialsError(GENERIC_LOGIN_ERROR) from exc

        record = self.repository.get_user_by_username(normalized_username)
        if record is None:
            self.password_hasher.verify(self._dummy_password_hash, password)
            raise InvalidCredentialsError(GENERIC_LOGIN_ERROR)

        user, password_hash = record
        if user.status != "active" or not self.password_hasher.verify(
            password_hash,
            password,
        ):
            raise InvalidCredentialsError(GENERIC_LOGIN_ERROR)

        if self.password_hasher.needs_rehash(password_hash):
            self.repository.update_password_hash(
                user.id,
                self.password_hasher.hash(password),
            )

        session_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        self.repository.create_session(
            session_id=str(uuid.uuid4()),
            user_id=user.id,
            token_hash=hash_session_token(session_token),
            expires_at=expires_at,
        )
        return LoginResult(
            user=user,
            session_token=session_token,
            expires_at=expires_at,
        )

    def authenticate_session(self, session_token: str) -> AuthUser | None:
        if not session_token or len(session_token) > 512:
            return None
        token_hash = hash_session_token(session_token)
        user = self.repository.get_user_by_session_hash(token_hash)
        if user is not None:
            self.repository.touch_session(token_hash)
        return user

    def logout(self, session_token: str) -> None:
        if session_token and len(session_token) <= 512:
            self.repository.revoke_session(hash_session_token(session_token))


class LoginRateLimiter:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max(1, max_attempts)
        self.window_seconds = max(1, window_seconds)
        self.clock = clock
        self._failures: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            failures = self._active_failures(key)
            return len(failures) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        with self._lock:
            failures = self._active_failures(key)
            failures.append(self.clock())
            self._failures[key] = failures

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _active_failures(self, key: str) -> List[float]:
        cutoff = self.clock() - self.window_seconds
        failures = [
            timestamp
            for timestamp in self._failures.get(key, [])
            if timestamp >= cutoff
        ]
        if failures:
            self._failures[key] = failures
        else:
            self._failures.pop(key, None)
        return failures


def normalize_username(value: str) -> str:
    normalized = value.strip().lower()
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUserDataError(
            "User name must contain 3-64 lowercase letters, numbers, dots, "
            "underscores, or hyphens."
        )
    return normalized


def validate_password(value: str) -> None:
    minimum = max(8, int(os.getenv("AES_AUTH_MIN_PASSWORD_LENGTH", "12")))
    if len(value) < minimum:
        raise InvalidUserDataError(
            f"Password must contain at least {minimum} characters."
        )
    if len(value) > 256:
        raise InvalidUserDataError("Password must be at most 256 characters.")


def hash_session_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def auth_enabled() -> bool:
    return _env_bool("AES_AUTH_ENABLED", True)


def cookie_settings() -> CookieSettings:
    same_site = os.getenv("AES_AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    if same_site not in {"lax", "strict", "none"}:
        same_site = "lax"
    secure = _env_bool("AES_AUTH_COOKIE_SECURE", False)
    name = os.getenv("AES_AUTH_COOKIE_NAME", "aes_session").strip() or "aes_session"
    if name.startswith("__Host-") and not secure:
        raise AuthenticationBackendError(
            "__Host- cookies require AES_AUTH_COOKIE_SECURE=true."
        )
    return CookieSettings(
        name=name,
        secure=secure,
        same_site=same_site,
        ttl_seconds=max(
            300,
            int(os.getenv("AES_AUTH_SESSION_TTL_SECONDS", "43200")),
        ),
    )


def database_settings() -> DatabaseSettings:
    password = os.getenv("AES_DB_PASSWORD", "")
    if not password:
        raise AuthenticationBackendError("AES_DB_PASSWORD is not configured.")
    return DatabaseSettings(
        host=os.getenv("AES_DB_HOST", "aes-postgres"),
        port=int(os.getenv("AES_DB_PORT", "5432")),
        database=os.getenv("AES_DB_NAME", "aes"),
        user=os.getenv("AES_DB_USER", "aes_app"),
        password=password,
        connect_timeout_seconds=max(
            1,
            int(os.getenv("AES_DB_CONNECT_TIMEOUT", "5")),
        ),
    )


@lru_cache(maxsize=1)
def get_auth_service() -> AuthService:
    return AuthService(
        repository=PostgresAuthRepository(),
        password_hasher=Argon2idPasswordHasher(),
    )


def _user_from_row(row: Dict[str, Any]) -> AuthUser:
    return AuthUser(
        id=str(row["id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        status=str(row["status"]),
        created_at=row["created_at"],
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

