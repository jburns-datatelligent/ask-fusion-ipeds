"""Where leads, questions and feedback go.

SnowflakeStore writes to IPEDS.AF_APP as the service user (insert-only on leads). LocalStore
writes JSON lines under app/.data/ for local development and tests.

A storage failure never stops someone asking a question: a prospect who hit an error on the
contact form would just leave. Failures are logged and the record is kept locally instead.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Protocol

log = logging.getLogger("ask_fusion_app")

DATA_DIR = Path(__file__).resolve().parent / ".data"


def lead_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]  # 128 bits; keeps sign-in links short


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


class Store(Protocol):
    def save_lead(self, lead: dict) -> None: ...
    def log_question(self, rec: dict) -> None: ...
    def save_feedback(self, rec: dict) -> None: ...
    def questions_today(self, key: str | None = None) -> int: ...


class LocalStore:
    def __init__(self, root: Path | None = None):
        self.root = root or DATA_DIR  # read at call time, so tests can point it elsewhere
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _append(self, name: str, rec: dict) -> None:
        rec = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), **rec}
        with self._lock, open(self.root / f"{name}.jsonl", "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")

    def _read(self, name: str) -> list[dict]:
        p = self.root / f"{name}.jsonl"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def save_lead(self, lead: dict) -> None:
        self._append("leads", lead)

    def log_question(self, rec: dict) -> None:
        self._append("questions", rec)

    def save_feedback(self, rec: dict) -> None:
        self._append("feedback", rec)

    def questions_today(self, key: str | None = None) -> int:
        today = _today_utc()
        return sum(1 for r in self._read("questions")
                   if r["at"][:10] == today and r.get("status") not in ("refused_limit", "smoke")
                   and (key is None or r.get("lead_key") == key))


class SnowflakeStore:
    """Short-lived statements over one cached connection, reopened if Snowflake drops it."""

    def __init__(self):
        self._conn = None
        self._lock = threading.Lock()
        self.fallback = LocalStore()

    def _connect(self):
        import snowflake.connector
        kw = dict(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
                  role=os.environ.get("SNOWFLAKE_ROLE", "IPEDS_PUBLIC_APP_RL"),
                  warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "IPEDS_PUBLIC_WH"),
                  login_timeout=30, network_timeout=30, client_session_keep_alive=True)
        if os.environ.get("SNOWFLAKE_PRIVATE_KEY"):
            from cryptography.hazmat.primitives import serialization
            key = serialization.load_pem_private_key(os.environ["SNOWFLAKE_PRIVATE_KEY"].encode(), password=None)
            kw["private_key"] = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption())
        else:
            kw["private_key_file"] = os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]
        return snowflake.connector.connect(**kw)

    def _execute(self, sql: str, params: tuple, fetch: bool = False):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.is_closed():
                        self._conn = self._connect()
                    cur = self._conn.cursor()
                    cur.execute(sql, params)
                    return cur.fetchone() if fetch else None
                except Exception:
                    self._conn = None
                    if attempt == 2:
                        raise

    def _safe(self, local_name: str, rec: dict, sql: str, params: tuple) -> None:
        try:
            self._execute(sql, params)
        except Exception:
            log.exception("Snowflake write failed; kept locally in %s.jsonl", local_name)
            getattr(self.fallback, {"leads": "save_lead", "questions": "log_question",
                                    "feedback": "save_feedback"}[local_name])(rec)

    def save_lead(self, lead: dict) -> None:
        self._safe("leads", lead,
                   "INSERT INTO IPEDS.AF_APP.AF_LEADS (lead_id, lead_key, first_name, last_name, email, organization, "
                   "job_role, consent_text, referrer, utm, user_agent) "
                   "SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s",
                   (lead["lead_id"], lead["lead_key"], lead["first_name"], lead["last_name"], lead["email"],
                    lead["organization"], lead["job_role"], lead["consent_text"], lead.get("referrer"),
                    json.dumps(lead.get("utm") or {}), lead.get("user_agent")))

    def log_question(self, rec: dict) -> None:
        self._safe("questions", rec,
                   "INSERT INTO IPEDS.AF_APP.AF_QUESTION_LOG (question_id, lead_id, lead_key, session_id, turn, "
                   "question, answer, sql_text, status, error, seconds, input_tokens, output_tokens, agent) "
                   "SELECT %s, %s, %s, %s, %s, %s, %s, PARSE_JSON(%s), %s, %s, %s, %s, %s, %s",
                   (rec["question_id"], rec.get("lead_id"), rec.get("lead_key"), rec.get("session_id"),
                    rec.get("turn"), rec["question"], rec.get("answer"), json.dumps(rec.get("sql") or []),
                    rec.get("status"), rec.get("error"), rec.get("seconds"), rec.get("input_tokens"),
                    rec.get("output_tokens"), rec.get("agent")))

    def save_feedback(self, rec: dict) -> None:
        self._safe("feedback", rec,
                   "INSERT INTO IPEDS.AF_APP.AF_FEEDBACK (question_id, lead_id, rating, comment) "
                   "VALUES (%s, %s, %s, %s)",
                   (rec["question_id"], rec.get("lead_id"), rec.get("rating"), rec.get("comment")))

    def questions_today(self, key: str | None = None) -> int:
        sql = ("SELECT COUNT(*) FROM IPEDS.AF_APP.AF_QUESTION_LOG "
               "WHERE asked_at >= DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())) "
               "AND COALESCE(status, '') NOT IN ('refused_limit', 'smoke')")
        params: tuple = ()
        if key:
            sql += " AND lead_key = %s"
            params = (key,)
        try:
            return int(self._execute(sql, params, fetch=True)[0])
        except Exception:
            # Fail open: a counting outage must not turn the site off. The warehouse monitor
            # and per-session limits still bound spend.
            log.exception("could not count today's questions")
            return 0


def make_store(kind: str) -> Store:
    return SnowflakeStore() if kind == "snowflake" else LocalStore()
