"""Call the Cortex Agent AF_ASK_FUSION_IPEDS over the Snowflake REST API.

Authentication is key-pair JWT, so the web backend holds a private key for a dedicated
low-privilege service user and nothing else. Locally it reuses ~/.snowflake/connections.toml.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path

import jwt
import requests
from cryptography.hazmat.primitives import serialization

AGENT = "IPEDS.DTDEV.AF_ASK_FUSION_IPEDS"


def agent_path(agent: str = AGENT) -> str:
    db, schema, name = agent.split(".")
    return f"/api/v2/databases/{db}/schemas/{schema}/agents/{name}:run"


AGENT_PATH = agent_path()


class AgentConfig:
    def __init__(self, account: str, user: str, private_key_file: str | None = None,
                 host: str | None = None, private_key_pem: str | None = None):
        self.account = account.split(".")[0].upper()  # locator, as the JWT issuer expects
        self.user = user.upper()
        self.host = host or f"https://{account.lower()}.snowflakecomputing.com"
        # A hosted app usually receives the key as a secret value rather than a file.
        pem = private_key_pem.encode() if private_key_pem else Path(private_key_file).read_bytes()
        self.key = serialization.load_pem_private_key(pem, password=None)

    @classmethod
    def from_env(cls) -> "AgentConfig":
        if os.getenv("SNOWFLAKE_ACCOUNT"):
            return cls(os.environ["SNOWFLAKE_ACCOUNT"], os.environ["SNOWFLAKE_USER"],
                       os.getenv("SNOWFLAKE_PRIVATE_KEY_FILE"), os.getenv("SNOWFLAKE_HOST"),
                       os.getenv("SNOWFLAKE_PRIVATE_KEY"))
        name = os.getenv("IPEDS_DEMO_SF_CONNECTION", "fusion")
        cfg = tomllib.loads((Path.home() / ".snowflake" / "connections.toml").read_text())[name]
        return cls(cfg["account"], cfg["user"], cfg.get("private_key_file") or cfg["private_key_path"])

    def token(self) -> str:
        pub = self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        fp = "SHA256:" + base64.b64encode(hashlib.sha256(pub).digest()).decode()
        now = int(time.time())
        claims = {"iss": f"{self.account}.{self.user}.{fp}", "sub": f"{self.account}.{self.user}",
                  "iat": now, "exp": now + 3000}
        return jwt.encode(claims, self.key, algorithm="RS256")


def run(question: str, cfg: AgentConfig, history: list[dict] | None = None,
        timeout: float = 90, agent: str = AGENT) -> Iterator[tuple[str, dict]]:
    """Yield (event, data) pairs from the agent's server-sent-event stream."""
    messages = list(history or []) + [{"role": "user", "content": [{"type": "text", "text": question}]}]
    resp = requests.post(
        cfg.host + agent_path(agent),
        headers={"Authorization": f"Bearer {cfg.token()}",
                 "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
                 "Content-Type": "application/json", "Accept": "text/event-stream"},
        json={"messages": messages}, stream=True, timeout=(10, timeout))
    with resp:
        resp.raise_for_status()
        # text/event-stream arrives without a charset, so requests falls back to ISO-8859-1 and an
        # en dash ("2022-23 aid year") came out as "2022â€"23". The stream is UTF-8.
        resp.encoding = "utf-8"
        event = None
        for raw in resp.iter_lines(decode_unicode=True):
            if raw.startswith("event:"):
                event = raw[6:].strip()
            elif raw.startswith("data:"):
                payload = raw[5:].strip()
                try:
                    yield event or "message", json.loads(payload)
                except json.JSONDecodeError:
                    yield event or "message", {"raw": payload}
