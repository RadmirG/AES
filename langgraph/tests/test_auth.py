from __future__ import annotations

import unittest
from datetime import datetime, timezone

from aes_agent.auth import (
    AuthService,
    AuthUser,
    InvalidCredentialsError,
    InvalidUserDataError,
    LoginRateLimiter,
    UserAlreadyExistsError,
    hash_session_token,
)


class _FakeHasher:
    def hash(self, password: str) -> str:
        return f"argon2id:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        return password_hash == self.hash(password)

    def needs_rehash(self, _password_hash: str) -> bool:
        return False


class _FakeRepository:
    def __init__(self) -> None:
        self.users = {}
        self.sessions = {}
        self.touched = []
        self.revoked = []

    def ping(self) -> None:
        return None

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
    ) -> AuthUser:
        if username in self.users:
            raise UserAlreadyExistsError(username)
        user = AuthUser(
            id=user_id,
            username=username,
            display_name=display_name,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        self.users[username] = (user, password_hash)
        return user

    def get_user_by_username(self, username: str):
        return self.users.get(username)

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        for username, (user, _old_hash) in self.users.items():
            if user.id == user_id:
                self.users[username] = (user, password_hash)
                return

    def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        self.sessions[token_hash] = {
            "id": session_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "revoked": False,
        }

    def get_user_by_session_hash(self, token_hash: str):
        session = self.sessions.get(token_hash)
        if not session or session["revoked"]:
            return None
        if session["expires_at"] <= datetime.now(timezone.utc):
            return None
        for user, _password_hash in self.users.values():
            if user.id == session["user_id"]:
                return user
        return None

    def touch_session(self, token_hash: str) -> None:
        self.touched.append(token_hash)

    def revoke_session(self, token_hash: str) -> None:
        session = self.sessions.get(token_hash)
        if session:
            session["revoked"] = True
        self.revoked.append(token_hash)


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeRepository()
        self.service = AuthService(self.repository, _FakeHasher())
        self.user = self.service.create_user(
            username="Engineer.One",
            display_name="Engineer One",
            password="correct-horse-battery",
        )

    def test_user_name_is_normalized(self):
        self.assertEqual(self.user.username, "engineer.one")

    def test_invalid_user_name_is_rejected(self):
        with self.assertRaises(InvalidUserDataError):
            self.service.create_user(
                username="not valid",
                display_name="Invalid",
                password="correct-horse-battery",
            )

    def test_login_stores_only_hashed_session_token(self):
        result = self.service.login(
            username="ENGINEER.ONE",
            password="correct-horse-battery",
            ttl_seconds=3600,
        )

        token_hash = hash_session_token(result.session_token)
        self.assertIn(token_hash, self.repository.sessions)
        self.assertNotIn(result.session_token, self.repository.sessions)
        self.assertEqual(result.user.id, self.user.id)

    def test_wrong_password_raises_generic_credentials_error(self):
        with self.assertRaisesRegex(
            InvalidCredentialsError,
            "Invalid user name or password",
        ):
            self.service.login(
                username="engineer.one",
                password="wrong-password-value",
                ttl_seconds=3600,
            )

    def test_session_authentication_and_logout(self):
        result = self.service.login(
            username="engineer.one",
            password="correct-horse-battery",
            ttl_seconds=3600,
        )

        authenticated = self.service.authenticate_session(result.session_token)
        self.assertEqual(authenticated, self.user)

        self.service.logout(result.session_token)
        self.assertIsNone(
            self.service.authenticate_session(result.session_token)
        )


class LoginRateLimiterTests(unittest.TestCase):
    def test_failures_block_until_window_expires(self):
        now = [100.0]
        limiter = LoginRateLimiter(
            max_attempts=2,
            window_seconds=10,
            clock=lambda: now[0],
        )

        limiter.record_failure("client")
        self.assertFalse(limiter.is_blocked("client"))
        limiter.record_failure("client")
        self.assertTrue(limiter.is_blocked("client"))

        now[0] = 111.0
        self.assertFalse(limiter.is_blocked("client"))


if __name__ == "__main__":
    unittest.main()
