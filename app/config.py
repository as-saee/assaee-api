import os
from zoneinfo import ZoneInfo

DB_URL = os.environ.get("ASSAEE_DB_URL", "sqlite:///./assaee.db")
TZ = ZoneInfo(os.environ.get("ASSAEE_TZ", "Europe/Madrid"))
# Empty NTFY_URL means delivery is switched off.
NTFY_URL = os.environ.get("ASSAEE_NTFY_URL", "")
NTFY_TOPIC = os.environ.get("ASSAEE_NTFY_TOPIC", "assaee-nudges")
# Write-only access token for the nudges topic (ntfy runs with default access "deny-all").
NTFY_TOKEN = os.environ.get("ASSAEE_NTFY_TOKEN", "")
NUDGE_CAP = int(os.environ.get("ASSAEE_NUDGE_CAP", "3"))
# Local hours with no nudges: QUIET_START (inclusive) to QUIET_END (exclusive), wrapping midnight.
QUIET_START = int(os.environ.get("ASSAEE_QUIET_START", "22"))
QUIET_END = int(os.environ.get("ASSAEE_QUIET_END", "7"))
# Shared secret every request except /health must present as "Authorization: Bearer <key>".
# Empty means unset: the server refuses to start (see main.lifespan).
API_KEY = os.environ.get("ASSAEE_API_KEY", "")
