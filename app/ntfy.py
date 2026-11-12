import json
import urllib.error
import urllib.request
from collections.abc import Callable

from app import config

Publisher = Callable[[str, str], None]


class NtfyError(Exception):
    pass


def publish(title: str, message: str) -> None:
    """Send one notification to the configured ntfy topic.

    Uses ntfy's JSON publishing (POST to the base URL), so titles and messages can hold any
    Unicode text; plain-header publishing would be limited to Latin-1.
    """
    payload = json.dumps({"topic": config.NTFY_TOPIC, "title": title, "message": message})
    headers = {"Content-Type": "application/json"}
    if config.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {config.NTFY_TOKEN}"
    request = urllib.request.Request(
        config.NTFY_URL, data=payload.encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=5):
            pass
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NtfyError(str(exc)) from exc
