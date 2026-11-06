"""Tiny JSON-over-HTTP helper (stdlib only)."""
import json
import urllib.error
import urllib.request


def post_json(url: str, body: dict, headers: dict = None, timeout: float = 60.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} from {url.split('?')[0]}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"connection failed: {e.reason}") from None


def get_json(url: str, headers: dict = None, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.URLError as e:
        raise RuntimeError(f"connection failed: {getattr(e, 'reason', e)}") from None
