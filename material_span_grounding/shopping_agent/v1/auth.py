from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from typing import Any

from .database import AgentDatabase


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


@dataclass(frozen=True)
class LoginResult:
    user: dict[str, Any]
    token: str
    expires_at: str


class AuthService:
    def __init__(
        self,
        database: AgentDatabase,
        *,
        password_min_length: int = 8,
        iterations: int = 310_000,
        session_days: int = 30,
    ) -> None:
        self.database = database
        self.password_min_length = int(password_min_length)
        self.iterations = int(iterations)
        self.session_days = int(session_days)

    @staticmethod
    def normalize_email(email: str) -> str:
        value = str(email).strip().casefold()
        if len(value) > 254 or not EMAIL_RE.fullmatch(value):
            raise ValueError("올바른 이메일 주소를 입력해주세요.")
        return value

    def validate_password(self, password: str) -> str:
        value = str(password)
        if len(value) < self.password_min_length:
            raise ValueError(f"비밀번호는 {self.password_min_length}자 이상이어야 합니다.")
        if len(value) > 256:
            raise ValueError("비밀번호가 너무 깁니다.")
        return value

    def _hash_password(self, password: str, salt: bytes, iterations: int) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return _b64(digest)

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _new_session(self, user: dict[str, Any]) -> LoginResult:
        token = secrets.token_urlsafe(32)
        expires_at = self.database.save_auth_session(
            self.token_hash(token), user["user_id"], days=self.session_days
        )
        return LoginResult(user=user, token=token, expires_at=expires_at)

    def register(self, *, email: str, password: str, display_name: str) -> LoginResult:
        normalized_email = self.normalize_email(email)
        password = self.validate_password(password)
        name = str(display_name).strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("이름은 1~80자로 입력해주세요.")
        salt = secrets.token_bytes(16)
        user = self.database.create_user(
            email=normalized_email,
            display_name=name,
            password_hash=self._hash_password(password, salt, self.iterations),
            password_salt=_b64(salt),
            password_iterations=self.iterations,
        )
        return self._new_session(user)

    def login(self, *, email: str, password: str) -> LoginResult:
        normalized_email = self.normalize_email(email)
        credentials = self.database.user_credentials(normalized_email)
        if credentials is None:
            raise PermissionError("이메일 또는 비밀번호가 올바르지 않습니다.")
        try:
            salt = base64.urlsafe_b64decode(credentials["password_salt"])
        except Exception as exc:
            raise RuntimeError("Stored password credential is invalid") from exc
        actual = self._hash_password(str(password), salt, int(credentials["password_iterations"]))
        if not hmac.compare_digest(actual, str(credentials["password_hash"])):
            raise PermissionError("이메일 또는 비밀번호가 올바르지 않습니다.")
        user = self.database.get_user(str(credentials["user_id"]))
        assert user is not None
        return self._new_session(user)

    def authenticate(self, token: str | None) -> dict[str, Any]:
        if not token:
            raise PermissionError("로그인이 필요합니다.")
        user = self.database.authenticate_token_hash(self.token_hash(token))
        if user is None:
            raise PermissionError("로그인 세션이 만료되었거나 유효하지 않습니다.")
        return user

    def logout(self, token: str | None) -> None:
        if token:
            self.database.revoke_auth_session(self.token_hash(token))

