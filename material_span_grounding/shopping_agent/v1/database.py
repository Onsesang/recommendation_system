from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


class AgentDatabase:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    password_iterations INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preferences (
                    preference_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    scope_category TEXT NOT NULL DEFAULT '',
                    attribute_type TEXT NOT NULL,
                    attribute TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strength REAL NOT NULL,
                    confidence REAL NOT NULL,
                    source TEXT NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, scope_category, attribute_type, attribute, direction)
                );

                CREATE TABLE IF NOT EXISTS behavior_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_user_time
                    ON behavior_events(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_preferences_user
                    ON preferences(user_id, active, updated_at DESC);

                CREATE TABLE IF NOT EXISTS cart_items (
                    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, product_id)
                );
                """
            )
            db.execute(
                "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _public_user(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "created_at": row["created_at"],
        }

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        password_salt: str,
        password_iterations: int,
    ) -> dict[str, Any]:
        now = iso_now()
        user_id = f"usr_{uuid.uuid4().hex}"
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?,?,?,?)",
                    (
                        user_id,
                        email,
                        display_name,
                        password_hash,
                        password_salt,
                        password_iterations,
                        now,
                        now,
                    ),
                )
                row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValueError("이미 가입된 이메일입니다.") from exc
        assert row is not None
        return self._public_user(row)

    def user_credentials(self, email: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return self._public_user(row) if row else None

    def save_auth_session(self, token_hash: str, user_id: str, *, days: int) -> str:
        now = utc_now()
        expires_at = (now + timedelta(days=days)).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO auth_sessions VALUES(?,?,?,?,?)",
                (token_hash, user_id, now.isoformat(), expires_at, now.isoformat()),
            )
        return expires_at

    def authenticate_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        now = iso_now()
        with self.connect() as db:
            row = db.execute(
                "SELECT u.* FROM auth_sessions s JOIN users u ON u.user_id=s.user_id "
                "WHERE s.token_hash=? AND s.expires_at>?",
                (token_hash, now),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?",
                    (now, token_hash),
                )
        return self._public_user(row) if row else None

    def revoke_auth_session(self, token_hash: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))

    def create_agent_session(self, user_id: str) -> dict[str, Any]:
        session_id = f"shop_{uuid.uuid4().hex}"
        now = iso_now()
        state = {
            "intent": {},
            "last_product_ids": [],
            "turn_count": 0,
            "agent_version": "v1",
        }
        with self.connect() as db:
            db.execute(
                "INSERT INTO agent_sessions VALUES(?,?,?,?,?)",
                (session_id, user_id, json.dumps(state), now, now),
            )
        return {"session_id": session_id, "state": state, "created_at": now, "updated_at": now}

    def get_agent_session(self, session_id: str, user_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM agent_sessions WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        value["state"] = json.loads(value.pop("state_json"))
        return value

    def update_agent_state(self, session_id: str, user_id: str, state: dict[str, Any]) -> None:
        with self.connect() as db:
            changed = db.execute(
                "UPDATE agent_sessions SET state_json=?, updated_at=? WHERE session_id=? AND user_id=?",
                (json.dumps(state, ensure_ascii=False), iso_now(), session_id, user_id),
            ).rowcount
        if not changed:
            raise KeyError("Agent session not found")

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        message_id = f"msg_{uuid.uuid4().hex}"
        created_at = iso_now()
        with self.connect() as db:
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?)",
                (message_id, session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), created_at),
            )
        return {"message_id": message_id, "role": role, "content": content, "metadata": metadata or {}, "created_at": created_at}

    def list_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        result = []
        for row in reversed(rows):
            value = dict(row)
            value["metadata"] = json.loads(value.pop("metadata_json"))
            result.append(value)
        return result

    def upsert_preference(
        self,
        user_id: str,
        *,
        scope_category: str | None,
        attribute_type: str,
        attribute: str,
        direction: str,
        strength: float,
        confidence: float,
        source: str,
        source_text: str = "",
    ) -> dict[str, Any]:
        now = iso_now()
        scope = scope_category or ""
        preference_id = f"pref_{uuid.uuid4().hex}"
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO preferences(
                    preference_id,user_id,scope_category,attribute_type,attribute,direction,
                    strength,confidence,source,source_text,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)
                ON CONFLICT(user_id,scope_category,attribute_type,attribute,direction)
                DO UPDATE SET
                    strength=MAX(preferences.strength, excluded.strength),
                    confidence=MAX(preferences.confidence, excluded.confidence),
                    source=excluded.source,
                    source_text=excluded.source_text,
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (
                    preference_id,
                    user_id,
                    scope,
                    attribute_type,
                    attribute,
                    direction,
                    float(strength),
                    float(confidence),
                    source,
                    source_text,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM preferences WHERE user_id=? AND scope_category=? AND "
                "attribute_type=? AND attribute=? AND direction=?",
                (user_id, scope, attribute_type, attribute, direction),
            ).fetchone()
        assert row is not None
        return self._preference_dict(row)

    @staticmethod
    def _preference_dict(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["scope_category"] = value["scope_category"] or None
        value["active"] = bool(value["active"])
        return value

    def list_preferences(self, user_id: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM preferences WHERE user_id=?"
        params: list[Any] = [user_id]
        if active_only:
            query += " AND active=1"
        query += " ORDER BY updated_at DESC, preference_id"
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._preference_dict(row) for row in rows]

    def update_preference(self, user_id: str, preference_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        allowed = {"direction", "strength", "confidence", "active"}
        if not changes or any(key not in allowed for key in changes):
            raise ValueError("Only direction, strength, confidence, and active can be updated")
        assignments = []
        values: list[Any] = []
        for key, value in changes.items():
            assignments.append(f"{key}=?")
            values.append(int(bool(value)) if key == "active" else value)
        assignments.append("updated_at=?")
        values.extend([iso_now(), preference_id, user_id])
        with self.connect() as db:
            try:
                changed = db.execute(
                    f"UPDATE preferences SET {','.join(assignments)} WHERE preference_id=? AND user_id=?",
                    values,
                ).rowcount
            except sqlite3.IntegrityError as exc:
                raise ValueError("Conflicting preference already exists") from exc
            row = db.execute(
                "SELECT * FROM preferences WHERE preference_id=? AND user_id=?",
                (preference_id, user_id),
            ).fetchone()
        if not changed or row is None:
            raise KeyError("Preference not found")
        return self._preference_dict(row)

    def delete_preference(self, user_id: str, preference_id: str) -> None:
        with self.connect() as db:
            changed = db.execute(
                "DELETE FROM preferences WHERE preference_id=? AND user_id=?",
                (preference_id, user_id),
            ).rowcount
        if not changed:
            raise KeyError("Preference not found")

    def record_event(
        self,
        user_id: str,
        *,
        event_id: str,
        event_type: str,
        product_id: str,
        session_id: str | None,
        context: dict[str, Any],
    ) -> bool:
        try:
            with self.connect() as db:
                db.execute(
                    "INSERT INTO behavior_events VALUES(?,?,?,?,?,?,?)",
                    (
                        event_id,
                        user_id,
                        session_id,
                        event_type,
                        product_id,
                        json.dumps(context, ensure_ascii=False),
                        iso_now(),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def list_events(self, user_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM behavior_events WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            value = dict(row)
            value["context"] = json.loads(value.pop("context_json"))
            result.append(value)
        return result

    def add_cart_item(self, user_id: str, product_id: str, quantity: int = 1) -> None:
        now = iso_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO cart_items VALUES(?,?,?,?,?)
                ON CONFLICT(user_id,product_id) DO UPDATE SET
                    quantity=excluded.quantity, updated_at=excluded.updated_at
                """,
                (user_id, product_id, quantity, now, now),
            )

    def remove_cart_item(self, user_id: str, product_id: str) -> bool:
        with self.connect() as db:
            return bool(
                db.execute(
                    "DELETE FROM cart_items WHERE user_id=? AND product_id=?",
                    (user_id, product_id),
                ).rowcount
            )

    def list_cart(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM cart_items WHERE user_id=? ORDER BY added_at DESC",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

