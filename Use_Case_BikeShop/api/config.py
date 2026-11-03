"""
Shop rules and settings in one place (SPEC §5).

Business rules are constants here so the API, the worker and, later, the
LLM tools all read the same values. Deployment settings come from the
environment (`.env` on the server, see `.env.example`).
"""
import os
from datetime import date, time
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------- deployment
DATA_DIR = Path(os.getenv("BIKESHOP_DATA_DIR", Path(__file__).parent / "data"))
DATABASE_URL = os.getenv("BIKESHOP_DATABASE_URL", f"sqlite:///{DATA_DIR / 'bikeshop.db'}")

# The static frontend (SPEC §7), served by FastAPI under /
FRONTEND_DIR = Path(os.getenv("BIKESHOP_FRONTEND_DIR", Path(__file__).parent.parent / "frontend"))

# Comma-separated list of allowed browser origins; "*" when running locally.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Secret mixed into API-key hashes. Set a long random value in production.
API_KEY_SECRET = os.getenv("API_KEY_SECRET", "local-dev-secret-change-in-production")

# BFH inference (MLMP), SPEC §8.1. From outside the BFH network use the proxy.
MLMP_BASE_URL = os.getenv("MLMP_BASE_URL", "https://inference.proxy.ti.bfh.ch/v1")
MLMP_API_KEY = os.getenv("MLMP_API_KEY", "")
MLMP_MODEL = os.getenv("MLMP_MODEL", "gpt-oss:120b")
INFERENCE_CHECK_TTL_SECONDS = 60
INFERENCE_CHECK_TIMEOUT_SECONDS = 5

# ---------------------------------------------------------------- shop time
SHOP_TZ = ZoneInfo("Europe/Zurich")

# Weekday (Mon=0) -> (opens, closes). Missing day = closed.
OPENING_HOURS: dict[int, tuple[time, time]] = {
    0: (time(9, 0), time(18, 30)),
    1: (time(9, 0), time(18, 30)),
    2: (time(9, 0), time(18, 30)),
    3: (time(9, 0), time(18, 30)),
    4: (time(9, 0), time(18, 30)),
    5: (time(9, 0), time(16, 0)),
}

# Swiss public holidays (canton of Bern) on which the shop is closed.
HOLIDAYS: dict[date, str] = {
    # The past year, for the invented history (SPEC §9.1)
    date(2025, 12, 25): "Christmas Day",
    date(2025, 12, 26): "St. Stephen's Day",
    date(2026, 1, 1): "New Year's Day",
    date(2026, 1, 2): "Berchtold's Day",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 6): "Easter Monday",
    date(2026, 5, 14): "Ascension Day",
    date(2026, 5, 25): "Whit Monday",
    date(2026, 8, 1): "Swiss National Day",
    date(2026, 12, 25): "Christmas Day",
    date(2026, 12, 26): "St. Stephen's Day",
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 2): "Berchtold's Day",
    date(2027, 3, 26): "Good Friday",
    date(2027, 3, 29): "Easter Monday",
    date(2027, 5, 6): "Ascension Day",
    date(2027, 5, 17): "Whit Monday",
    date(2027, 8, 1): "Swiss National Day",
    date(2027, 12, 25): "Christmas Day",
    date(2027, 12, 26): "St. Stephen's Day",
}

# ---------------------------------------------------------------- rentals
TIME_GRID_MINUTES = 15
MIN_RENTAL_HOURS = 1
MAX_RENTAL_DAYS = 14
MAX_DAYS_AHEAD = 60
MAX_OPEN_RENTALS_PER_CUSTOMER = 3

# ---------------------------------------------------------------- sales
ORDER_HOLD_DAYS = 7
MAX_RESERVED_ORDERS_PER_CUSTOMER = 2

# ---------------------------------------------------------------- worker (SPEC §5.7, §5.8)
EXPIRE_EVERY_MINUTES = int(os.getenv("EXPIRE_EVERY_MINUTES", "15"))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "2"))
JOB_HEARTBEAT_SECONDS = 15
JOB_STALE_AFTER_SECONDS = 120
JOB_MAX_ATTEMPTS = 3
JOB_RETRY_BASE_SECONDS = 30          # run_after = now + 30 s x attempts
JOB_MAX_ERROR_CHARS = 2000

# ---------------------------------------------------------------- email (SPEC §5.9)
# Mailgun EU. Without MAILGUN_API_KEY the logging mailer writes emails to the log.
MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "mail.kooistra.ch")
MAILGUN_BASE_URL = os.getenv("MAILGUN_BASE_URL", "https://api.eu.mailgun.net/v3")
MAIL_FROM = os.getenv("MAIL_FROM", "BikeShop <bikeshop@mail.kooistra.ch>")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:8130")   # links in emails

# ---------------------------------------------------------------- analytics (SPEC §5.10)
ANALYTICS_KEEP_DAYS = 365

# ---------------------------------------------------------------- help and legal pages (SPEC §6)
DOCS_DIR = Path(os.getenv("BIKESHOP_DOCS_DIR", Path(__file__).parent.parent / "docs"))

# ---------------------------------------------------------------- metrics (SPEC §10.3)
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "1") == "1"
SERVICE_NAME = "bikeshop"

# ---------------------------------------------------------------- API usage
STARTING_TOKENS = 100.0
DEMO_ACCOUNT_TOKENS = 10_000.0

RATE_LIMIT_PER_MINUTE = 60
RATE_LIMIT_PER_HOUR = 1_000
RATE_LIMIT_PER_DAY = 5_000

# Token cost per billable call (SPEC §5.6). Checked in order; first match wins.
# (method, path suffix or exact path, cost)
TOKEN_COST_RULES: list[tuple[str, str, float]] = [
    ("POST", "/cancel", 0.0),          # any cancel is free
    ("POST", "=/api/rentals", 5.0),    # "=" means exact path
    ("POST", "=/api/orders", 5.0),
]
DEFAULT_TOKEN_COST = 1.0

MONEY_PLACES = Decimal("0.01")
