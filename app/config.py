import os
from zoneinfo import ZoneInfo

DB_URL = os.environ.get("ASSAEE_DB_URL", "sqlite:///./assaee.db")
TZ = ZoneInfo(os.environ.get("ASSAEE_TZ", "Europe/Madrid"))
NUDGE_CAP = int(os.environ.get("ASSAEE_NUDGE_CAP", "3"))
# Local hours with no nudges: QUIET_START (inclusive) to QUIET_END (exclusive), wrapping midnight.
QUIET_START = int(os.environ.get("ASSAEE_QUIET_START", "22"))
QUIET_END = int(os.environ.get("ASSAEE_QUIET_END", "7"))
