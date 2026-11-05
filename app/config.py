"""Runtime settings for the public app, read from the environment (or app/.secrets/app.env).

Every value a host needs to set is here, so deploying is "set these variables", nothing more.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENV_FILE = APP_DIR / ".secrets" / "app.env"
# One per process, not per load(): Streamlit re-runs the script on every click.
_PROCESS_SECRET = secrets.token_urlsafe(32)


def _load_env_file() -> None:
    """Local convenience: values already in the environment win, so a host's secrets do too."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


@dataclass(frozen=True)
class Settings:
    agent: str
    store: str                 # snowflake | local
    app_secret: str
    per_lead_daily: int        # questions one person may ask per day
    global_daily: int          # questions the whole site may ask per day: the model-token cap
    deadline_s: int            # above the agent's 120s budget; a stream once stalled for minutes
    history_turns: int         # prior turns sent with a follow-up
    cta_url: str
    privacy_url: str
    require_contact: bool      # False: visitors ask without the contact form (demos and testing)

    @classmethod
    def load(cls) -> "Settings":
        _load_env_file()
        e = os.environ.get
        return cls(
            agent=e("IPEDS_AGENT", "IPEDS.DTDEV.AF_ASK_FUSION_IPEDS_PUBLIC"),
            store=e("APP_STORE", "local"),
            # Without a configured secret, sign-in links last until the process restarts.
            app_secret=e("APP_SECRET") or _PROCESS_SECRET,
            per_lead_daily=int(e("APP_PER_LEAD_DAILY", "25")),
            global_daily=int(e("APP_GLOBAL_DAILY", "400")),
            deadline_s=int(e("APP_DEADLINE_S", "150")),
            history_turns=int(e("APP_HISTORY_TURNS", "4")),
            cta_url=e("APP_CTA_URL", "https://datatelligent.ai"),
            privacy_url=e("APP_PRIVACY_URL", "https://datatelligent.ai"),
            # Required unless switched off explicitly: a typo must not quietly open the site.
            require_contact=e("APP_REQUIRE_CONTACT", "true").strip().lower() not in {"false", "0", "no", "off"},
        )


CONSENT_TEXT = (
    "Datatelligent may contact me about Ask Fusion, and may keep the questions I ask here "
    "to improve the service."
)

ROLES = (
    "President, provost or cabinet",
    "Enrollment management or admissions",
    "Institutional research or effectiveness",
    "Finance or budget",
    "Student success or advising",
    "Faculty or academic leadership",
    "Consultant or partner",
    "Other",
)
