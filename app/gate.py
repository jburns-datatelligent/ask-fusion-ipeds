"""The contact gate: validate the form, and remember a visitor across a page reload.

Streamlit forgets session state on reload. Rather than make someone re-enter their details, the
page carries a signed token in its URL (?t=...): the lead id, hashed email key, first name and
an expiry, HMAC-signed with APP_SECRET. It cannot be forged without the secret, and the app
never needs to read the leads table back (the service role is insert-only there).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time

TOKEN_DAYS = 30
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# Personal addresses are allowed (plenty of IR staff use them) but flagged for sales.
FREEMAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com", "aol.com",
            "proton.me", "protonmail.com", "live.com", "msn.com", "me.com"}


def validate(form: dict) -> dict[str, str]:
    """Return {field: problem}; empty means the form is good."""
    errors = {}
    for f, name in (("first_name", "first name"), ("last_name", "last name"),
                    ("organization", "institution or organization")):
        if not (form.get(f) or "").strip():
            errors[f] = f"Please enter your {name}."
        elif len(form[f].strip()) > 200:
            errors[f] = "That is longer than we can store."
    email = (form.get("email") or "").strip()
    if not EMAIL.match(email) or len(email) > 254:
        errors["email"] = "Please enter a valid email address."
    if not form.get("job_role"):
        errors["job_role"] = "Please choose the role closest to yours."
    if not form.get("consent"):
        errors["consent"] = "Please agree so we can give you access."
    return errors


def is_freemail(email: str) -> bool:
    return email.rsplit("@", 1)[-1].lower() in FREEMAIL


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(lead: dict, secret: str, now: float | None = None) -> str:
    body = {"id": lead["lead_id"], "k": lead["lead_key"], "fn": lead["first_name"][:40],
            "org": lead["organization"][:80], "exp": int((now or time.time()) + TOKEN_DAYS * 86400)}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()[:18])
    return f"{payload}.{sig}"


def read_token(token: str | None, secret: str, now: float | None = None) -> dict | None:
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    want = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()[:18])
    if not hmac.compare_digest(sig, want):
        return None
    try:
        body = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if body.get("exp", 0) < (now or time.time()):
        return None
    return {"lead_id": body["id"], "lead_key": body["k"], "first_name": body.get("fn", ""),
            "organization": body.get("org", "")}
