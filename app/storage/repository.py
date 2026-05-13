from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.providers.longcat_client import load_env_files


class StorageError(RuntimeError):
    """Raised when the configured storage backend cannot complete an operation."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


@dataclass
class StoredUser:
    user_id: str
    username: str
    display_name: str
    password_hash: str
    password_salt: str

    def public_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
        }


class AppRepository(Protocol):
    def get_user_by_username(self, username: str) -> StoredUser | None:
        ...

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        ...

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
    ) -> StoredUser:
        ...

    def save_session(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None:
        ...

    def get_user_by_session(self, token_hash: str) -> StoredUser | None:
        ...

    def delete_session(self, token_hash: str) -> None:
        ...

    def save_user_location(self, *, user_id: str, location: dict[str, Any]) -> None:
        ...

    def save_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        mode: str,
        message: str,
        user_context: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        ...

    def save_companions(self, *, user_id: str, companions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...

    def list_companions(self, user_id: str) -> list[dict[str, Any]]:
        ...

    def save_plan_notification_targets(
        self,
        *,
        user_id: str,
        plan_id: str,
        companions: list[dict[str, Any]],
        message: str,
    ) -> None:
        ...

    def mark_plan_notifications_sent(self, *, user_id: str, plan_id: str, message: str) -> None:
        ...


class MemoryAppRepository:
    def __init__(self) -> None:
        self.users: dict[str, StoredUser] = {}
        self.users_by_name: dict[str, str] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.locations: list[dict[str, Any]] = []
        self.plans: dict[str, dict[str, Any]] = {}
        self.companions: dict[str, dict[str, Any]] = {}
        self.plan_notifications: list[dict[str, Any]] = []

    def get_user_by_username(self, username: str) -> StoredUser | None:
        user_id = self.users_by_name.get(username.lower())
        return self.users.get(user_id or "")

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        return self.users.get(user_id)

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
    ) -> StoredUser:
        user = StoredUser(
            user_id=user_id,
            username=username,
            display_name=display_name,
            password_hash=password_hash,
            password_salt=password_salt,
        )
        self.users[user_id] = user
        self.users_by_name[username.lower()] = user_id
        return user

    def save_session(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None:
        self.sessions[token_hash] = {"user_id": user_id, "expires_at": expires_at}

    def get_user_by_session(self, token_hash: str) -> StoredUser | None:
        session = self.sessions.get(token_hash)
        if not session:
            return None
        if session["expires_at"] <= utc_now():
            self.sessions.pop(token_hash, None)
            return None
        return self.get_user_by_id(session["user_id"])

    def delete_session(self, token_hash: str) -> None:
        self.sessions.pop(token_hash, None)

    def save_user_location(self, *, user_id: str, location: dict[str, Any]) -> None:
        self.locations.append({"user_id": user_id, "location": location, "created_at": utc_now()})

    def save_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        mode: str,
        message: str,
        user_context: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        self.plans[plan_id] = {
            "user_id": user_id,
            "plan_id": plan_id,
            "mode": mode,
            "message": message,
            "user_context": user_context,
            "plan": plan,
            "created_at": utc_now(),
        }

    def save_companions(self, *, user_id: str, companions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for item in companions:
            normalized = normalize_companion(item)
            if not normalized:
                continue
            key = self._companion_key(user_id, normalized)
            companion = {"companion_id": key, "user_id": user_id, **normalized}
            self.companions[key] = companion
            saved.append(companion)
        return saved

    def list_companions(self, user_id: str) -> list[dict[str, Any]]:
        return [
            {key: value for key, value in item.items() if key != "user_id"}
            for item in self.companions.values()
            if item["user_id"] == user_id
        ]

    def save_plan_notification_targets(
        self,
        *,
        user_id: str,
        plan_id: str,
        companions: list[dict[str, Any]],
        message: str,
    ) -> None:
        for companion in companions:
            self.plan_notifications.append(
                {
                    "user_id": user_id,
                    "plan_id": plan_id,
                    "companion_id": companion.get("companion_id"),
                    "recipient_name": companion.get("name"),
                    "relation": companion.get("relation"),
                    "contact_method": companion.get("contact_method"),
                    "contact_value": companion.get("contact_value"),
                    "message": message,
                    "status": "pending",
                    "created_at": utc_now(),
                }
            )

    def mark_plan_notifications_sent(self, *, user_id: str, plan_id: str, message: str) -> None:
        for item in self.plan_notifications:
            if item["user_id"] == user_id and item["plan_id"] == plan_id:
                item["message"] = message
                item["status"] = "ready_to_send"

    def _companion_key(self, user_id: str, companion: dict[str, Any]) -> str:
        return "|".join(
            [
                user_id,
                companion["name"].lower(),
                companion.get("contact_method", "").lower(),
                companion.get("contact_value", "").lower(),
            ]
        )


class MySQLAppRepository:
    def __init__(self) -> None:
        self.host = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.database = os.getenv("MYSQL_DATABASE", "nearnow")
        self.user = os.getenv("MYSQL_USER", "nearnow")
        self.password = os.getenv("MYSQL_PASSWORD", "")
        if os.getenv("NEARNOW_MYSQL_AUTO_MIGRATE", "false").lower() == "true":
            self.ensure_schema()

    def get_user_by_username(self, username: str) -> StoredUser | None:
        rows = self._query(
            "SELECT user_id, username, display_name, password_hash, password_salt FROM users WHERE username = %s",
            (username,),
        )
        return self._user_from_row(rows[0]) if rows else None

    def get_user_by_id(self, user_id: str) -> StoredUser | None:
        rows = self._query(
            "SELECT user_id, username, display_name, password_hash, password_salt FROM users WHERE user_id = %s",
            (user_id,),
        )
        return self._user_from_row(rows[0]) if rows else None

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
    ) -> StoredUser:
        self._execute(
            """
            INSERT INTO users (user_id, username, display_name, password_hash, password_salt)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, username, display_name, password_hash, password_salt),
        )
        return StoredUser(user_id, username, display_name, password_hash, password_salt)

    def save_session(self, *, token_hash: str, user_id: str, expires_at: datetime) -> None:
        self._execute(
            """
            INSERT INTO app_sessions (token_hash, user_id, expires_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE user_id = VALUES(user_id), expires_at = VALUES(expires_at)
            """,
            (token_hash, user_id, expires_at.replace(tzinfo=None)),
        )

    def get_user_by_session(self, token_hash: str) -> StoredUser | None:
        rows = self._query(
            """
            SELECT u.user_id, u.username, u.display_name, u.password_hash, u.password_salt
            FROM app_sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > UTC_TIMESTAMP()
            """,
            (token_hash,),
        )
        return self._user_from_row(rows[0]) if rows else None

    def delete_session(self, token_hash: str) -> None:
        self._execute("DELETE FROM app_sessions WHERE token_hash = %s", (token_hash,))

    def save_user_location(self, *, user_id: str, location: dict[str, Any]) -> None:
        coordinates = location.get("coordinates") or {}
        self._execute(
            """
            INSERT INTO user_locations (
                user_id, home_location, city, district, landmark, formatted_address,
                lat, lng, location_source, accuracy_m, precision_value,
                address_source, address_confidence, raw_json
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                location.get("home_location"),
                location.get("city"),
                location.get("district"),
                location.get("landmark"),
                location.get("formatted_address"),
                coordinates.get("lat"),
                coordinates.get("lng"),
                location.get("location_source"),
                location.get("accuracy_m"),
                location.get("precision"),
                location.get("address_source"),
                location.get("address_confidence"),
                to_json(location),
            ),
        )

    def save_plan(
        self,
        *,
        user_id: str,
        plan_id: str,
        mode: str,
        message: str,
        user_context: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        self._execute(
            """
            INSERT INTO planning_records (plan_id, user_id, mode, message, user_context_json, plan_json)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              mode = VALUES(mode),
              message = VALUES(message),
              user_context_json = VALUES(user_context_json),
              plan_json = VALUES(plan_json)
            """,
            (plan_id, user_id, mode, message, to_json(user_context), to_json(plan)),
        )

    def save_companions(self, *, user_id: str, companions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        for item in companions:
            normalized = normalize_companion(item)
            if not normalized:
                continue
            companion_id = stable_companion_id(user_id, normalized)
            self._execute(
                """
                INSERT INTO companions (
                    companion_id, user_id, name, relation, contact_method, contact_value, note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  relation = VALUES(relation),
                  contact_method = VALUES(contact_method),
                  contact_value = VALUES(contact_value),
                  note = VALUES(note)
                """,
                (
                    companion_id,
                    user_id,
                    normalized["name"],
                    normalized.get("relation"),
                    normalized.get("contact_method"),
                    normalized.get("contact_value"),
                    normalized.get("note"),
                ),
            )
            saved.append({"companion_id": companion_id, **normalized})
        return saved

    def list_companions(self, user_id: str) -> list[dict[str, Any]]:
        return self._query(
            """
            SELECT companion_id, name, relation, contact_method, contact_value, note
            FROM companions
            WHERE user_id = %s
            ORDER BY updated_at DESC, created_at DESC
            """,
            (user_id,),
        )

    def save_plan_notification_targets(
        self,
        *,
        user_id: str,
        plan_id: str,
        companions: list[dict[str, Any]],
        message: str,
    ) -> None:
        for companion in companions:
            self._execute(
                """
                INSERT INTO plan_notifications (
                    plan_id, user_id, companion_id, recipient_name, relation,
                    contact_method, contact_value, message, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    plan_id,
                    user_id,
                    companion.get("companion_id"),
                    companion.get("name"),
                    companion.get("relation"),
                    companion.get("contact_method"),
                    companion.get("contact_value"),
                    message,
                ),
            )

    def mark_plan_notifications_sent(self, *, user_id: str, plan_id: str, message: str) -> None:
        self._execute(
            """
            UPDATE plan_notifications
            SET status = 'ready_to_send', message = %s
            WHERE user_id = %s AND plan_id = %s
            """,
            (message, user_id, plan_id),
        )

    def ensure_schema(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        statements = [statement.strip() for statement in schema_path.read_text(encoding="utf-8").split(";")]
        for statement in statements:
            if statement:
                self._execute(statement)

    def _connect(self):
        try:
            import mysql.connector
        except ImportError as exc:
            raise StorageError("mysql-connector-python 未安装，无法使用 MySQL 存储。") from exc
        try:
            return mysql.connector.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                autocommit=True,
            )
        except Exception as exc:  # pragma: no cover - depends on local MySQL
            raise StorageError("无法连接 MySQL，请检查 MYSQL_* 环境变量。") from exc

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as connection:
            with connection.cursor(dictionary=True) as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def _user_from_row(self, row: dict[str, Any]) -> StoredUser:
        return StoredUser(
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            password_hash=row["password_hash"],
            password_salt=row["password_salt"],
        )


def create_repository() -> AppRepository:
    load_env_files()
    backend = os.getenv("NEARNOW_STORAGE_BACKEND", "memory").strip().lower()
    if backend == "mysql":
        return MySQLAppRepository()
    return MemoryAppRepository()


def normalize_companion(item: dict[str, Any]) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    contact_value = str(item.get("contact_value") or item.get("contact") or "").strip()
    contact_method = str(item.get("contact_method") or infer_contact_method(contact_value)).strip()
    return {
        "name": name,
        "relation": str(item.get("relation") or "同行者").strip(),
        "contact_method": contact_method,
        "contact_value": contact_value,
        "note": str(item.get("note") or "").strip(),
    }


def infer_contact_method(value: str) -> str:
    if "@" in value:
        return "email"
    if value.replace("+", "").replace("-", "").replace(" ", "").isdigit():
        return "phone"
    return "wechat" if value else ""


def stable_companion_id(user_id: str, companion: dict[str, Any]) -> str:
    import hashlib

    raw = "|".join(
        [
            user_id,
            companion["name"].lower(),
            companion.get("contact_method", "").lower(),
            companion.get("contact_value", "").lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
