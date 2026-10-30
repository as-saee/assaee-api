import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import config, ntfy


@pytest.fixture
def server():
    """A tiny real HTTP server standing in for ntfy; records what it receives."""
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.headers["Content-Type"], json.loads(body)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", received
    httpd.shutdown()


def test_publish_posts_json_with_unicode(server, monkeypatch):
    url, received = server
    monkeypatch.setattr(config, "NTFY_URL", url)
    monkeypatch.setattr(config, "NTFY_TOPIC", "my-topic")
    ntfy.publish("السعي – libro", "Lectura: hace 3 días")
    assert received == [
        (
            "application/json",
            {"topic": "my-topic", "title": "السعي – libro", "message": "Lectura: hace 3 días"},
        )
    ]


def test_publish_raises_when_ntfy_is_down(monkeypatch):
    monkeypatch.setattr(config, "NTFY_URL", "http://127.0.0.1:1")  # nothing listens on port 1
    with pytest.raises(ntfy.NtfyError):
        ntfy.publish("t", "m")
