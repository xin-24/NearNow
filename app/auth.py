from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from app.storage.repository import AppRepository, StoredUser, utc_now


class AuthError(RuntimeError):
    """Raised when login credentials cannot be accepted."""


class AuthService:
    session_days = 7

    def __init__(self, repository: AppRepository) -> None:
        self.repository = repository

    def login_or_register(self, username: str, password: str, display_name: str | None = None) -> dict:
        username = self._normalize_username(username)
        password = password.strip()
        if len(password) < 6:
            raise AuthError("密码至少需要 6 位。")

        user = self.repository.get_user_by_username(username)
        if user is None:
            salt = secrets.token_hex(16)
            user = self.repository.create_user(
                user_id=f"user_{secrets.token_hex(12)}",
                username=username,
                display_name=(display_name or username).strip() or username,
                password_hash=self.hash_password(password, salt),
                password_salt=salt,
            )
        elif not self.verify_password(password, user):
            raise AuthError("账号或密码不正确。")

        token = secrets.token_urlsafe(32)
        self.repository.save_session(
            token_hash=self.hash_token(token),
            user_id=user.user_id,
            expires_at=utc_now() + timedelta(days=self.session_days),
        )
        return {"token": token, "user": user.public_dict()}

    def authenticate(self, token: str | None) -> dict | None:
        if not token:
            return None
        user = self.repository.get_user_by_session(self.hash_token(token))
        return user.public_dict() if user else None

    def logout(self, token: str | None) -> None:
        if token:
            self.repository.delete_session(self.hash_token(token))

    def _normalize_username(self, username: str) -> str:
        normalized = " ".join(str(username or "").split()).lower()
        if len(normalized) < 2:
            raise AuthError("账号至少需要 2 个字符。")
        return normalized

    def verify_password(self, password: str, user: StoredUser) -> bool:
        expected = self.hash_password(password, user.password_salt)
        return hmac.compare_digest(expected, user.password_hash)

    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        )
        return digest.hex()

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()
