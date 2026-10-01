"""
checklist.py - One-file health checklist / unit tests for the video clipping pipeline.

Usage:
    py checklist.py              # run all checks, print a pass/fail checklist
    py -m pytest checklist.py -v # run the same checks as unit tests (optional)

Checks:
  1. RSS feed        - channels from config.json list videos via yt-dlp (the RSS
                       endpoint 404s for plain-HTTP clients, so yt-dlp is used)
  2. Social creds    - config.json "upload_connectors" filled in (no YOUR_* placeholders)
  3. Redis database  - localhost:6379 answers PING
  4. LLM connection  - LLM endpoint answers on /v1/models (probes config.json llm.endpoint
                       if set, the endpoint hardcoded in pipeline.py, and LM Studio's
                       default port 1234)

Exit code: 0 = everything green, 1 = at least one check failed.
"""

import json
import socket
import sys
import urllib.error
import urllib.request

from yt_dlp import YoutubeDL

try:
    import redis
except ImportError:  # checklist still runs; falls back to a raw socket check
    redis = None

CONFIG_FILE = "config.json"
LM_STUDIO_ENDPOINT = "http://localhost:1234/v1"     # LM Studio default port
PLACEHOLDER_PREFIX = "YOUR_"


# ------------------------------------------------------------------ helpers

def _load_config():
    """Load config.json from the project root. Returns None on failure."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  Could not read {CONFIG_FILE}: {e}")
        return None


def _http_get(url, timeout=10):
    """GET a URL. Returns (status_code, body_bytes) or (None, error_message)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (checklist)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e)


# ------------------------------------------------------- 1. RSS feed check

def check_rss_feeds():
    """List every channel from config.json via yt-dlp and verify entries come back.

    (The RSS endpoint 404s for plain-HTTP clients on this machine, so yt-dlp's
    extraction path is used instead - the same path the trigger engine uses.)
    """
    config = _load_config()
    if config is None:
        return False, ["FAIL config.json unreadable - cannot determine channels"]

    channels = config.get("channels", {})
    channel_ids = [(name, cid) for cat in channels.values() for name, cid in cat.items()]
    if not channel_ids:
        return False, ["FAIL no channel IDs found in config.json 'channels' section"]

    lines = []
    ok = True
    for name, cid in channel_ids:
        channel_url = f"https://www.youtube.com/channel/{cid}/videos"
        ydl_opts = {"quiet": True, "extract_flat": True, "playlistend": 3}
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
        except Exception as e:
            ok = False
            lines.append(f"FAIL {name}: yt-dlp error - {e}")
            continue
        entries = info.get("entries") or []
        n = len(entries)
        if n == 0:
            ok = False
            lines.append(f"FAIL {name}: channel listed but 0 entries (check channel id {cid})")
        else:
            latest = entries[0].get("title") or "?"
            lines.append(f"OK   {name}: {n} entries, latest: {latest[:60]}")
    return ok, lines


# --------------------------------------------- 2. social credentials check

def check_social_credentials():
    """Verify upload connectors in config.json.

    YouTube is the active online platform. Twitter and TikTok are manual
    (clips saved locally), so their placeholders do not block the pipeline.
    """
    config = _load_config()
    if config is None:
        return False, ["FAIL config.json unreadable"]

    connectors = config.get("upload_connectors", {})
    if not connectors:
        return False, ["FAIL no 'upload_connectors' section in config.json"]

    lines = []
    youtube_ok = False
    for platform, creds in connectors.items():
        if not isinstance(creds, dict) or not creds:
            if platform == "youtube":
                lines.append(f"FAIL {platform}: no credentials configured")
            else:
                lines.append(f"--   {platform}: disabled (manual upload only)")
            continue
        missing = [k for k, v in creds.items()
                   if not v or str(v).startswith(PLACEHOLDER_PREFIX)]
        if missing:
            if platform == "youtube":
                lines.append(f"FAIL {platform}: placeholder/empty keys: {', '.join(missing)}")
            else:
                lines.append(f"INFO {platform}: placeholder keys ({', '.join(missing)}) - manual upload mode active")
        else:
            keys = ", ".join(creds.keys())
            lines.append(f"OK   {platform}: configured ({keys})")
            if platform == "youtube":
                youtube_ok = True

    if not youtube_ok:
        lines.append("-> fill in 'youtube' connector in config.json upload_connectors")
    return youtube_ok, lines


# ----------------------------------------------------- 3. Redis db check

def check_redis(host="localhost", port=6379):
    """PING Redis; falls back to a raw socket check if the redis package is missing."""
    if redis is not None:
        try:
            client = redis.Redis(host=host, port=port,
                                 socket_connect_timeout=3, socket_timeout=3)
            client.ping()
            version = client.info("server").get("redis_version", "?")
            return True, [f"OK   PONG from {host}:{port} (redis {version})"]
        except Exception as e:
            return False, [f"FAIL {host}:{port} - {e}",
                           "-> start Redis (docker: docker run -d -p 6379:6379 --name video-redis redis:7-alpine)"]
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, [f"OK   {host}:{port} accepts connections "
                          "(redis package not installed, socket check only)"]
    except Exception as e:
        return False, [f"FAIL {host}:{port} - {e}",
                       "-> start Redis (docker: docker run -d -p 6379:6379 --name video-redis redis:7-alpine)"]


# ------------------------------------------------------ 4. LLM connection

def _llm_endpoints():
    """Endpoints to probe: config.json llm.endpoint (if set), Ollama default, LM Studio default, pipeline.py."""
    endpoints = []
    config = _load_config()
    if config:
        llm = config.get("llm", {})
        if isinstance(llm, dict) and llm.get("endpoint"):
            ep = str(llm["endpoint"]).rstrip("/")
            if not ep.endswith("/v1"):
                ep += "/v1"
            endpoints.append(("config.json llm.endpoint", ep))
    endpoints.append(("Ollama default", "http://localhost:11434/v1"))
    endpoints.append(("LM Studio default", LM_STUDIO_ENDPOINT))
    return endpoints


def _extract_model_names(body):
    """Pull model ids out of an OpenAI-compatible /v1/models response."""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
        return [m.get("id", "?") for m in data.get("data", [])]
    except Exception:
        return []


def check_llm():
    """Probe LLM endpoints for an OpenAI-compatible server (GET /v1/models)."""
    lines = []
    any_ok = False
    for label, base in _llm_endpoints():
        status, body = _http_get(f"{base}/models", timeout=5)
        if status is None:
            lines.append(f"--   {label} ({base}): nothing listening - {body}")
        elif status == 200:
            any_ok = True
            models = _extract_model_names(body)
            names = ", ".join(models[:5]) if models else "?"
            lines.append(f"OK   {label} ({base}): models: {names}")
        elif status == 404:
            lines.append(f"WARN {label} ({base}): HTTP 404 - something is listening on this port "
                         "but it is not an OpenAI-compatible LLM (is this the FastAPI API server?)")
        else:
            lines.append(f"WARN {label} ({base}): HTTP {status}")

    if not any_ok:
        lines.append("-> start your LLM server (LM Studio: load a model, start the server on port 1234)")
        lines.append("-> NOTE pipeline.py hardcodes http://localhost:8000/v1 and calls /v1/generate;")
        lines.append("   LM Studio speaks /v1/chat/completions - pipeline.py needs updating to match")
    return any_ok, lines


# ------------------------------------------------------------ test runner

CHECKS = [
    ("1. RSS feed", check_rss_feeds),
    ("2. Social credentials", check_social_credentials),
    ("3. Redis database", check_redis),
    ("4. LLM connection", check_llm),
]


def run_checklist():
    print("=" * 64)
    print("VIDEO CLIPPING PIPELINE - HEALTH CHECKLIST")
    print("=" * 64)
    all_ok = True
    results = {}
    for title, fn in CHECKS:
        print(f"\n[{title}]")
        try:
            ok, lines = fn()
        except Exception as e:
            ok, lines = False, [f"FAIL check crashed: {e}"]
        results[title] = ok
        for line in lines:
            print(f"  {line}")
        if not ok:
            all_ok = False

    print("\n" + "=" * 64)
    print("SUMMARY")
    for title, ok in results.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {title}")
    print("=" * 64)
    return all_ok


# ------------------------------------------------------------- unit tests
# The same checks as pytest-compatible tests (optional):
#   py -m pytest checklist.py -v

def test_rss_feed():
    ok, lines = check_rss_feeds()
    assert ok, "\n".join(lines)


def test_social_credentials():
    ok, lines = check_social_credentials()
    assert ok, "\n".join(lines)


def test_redis():
    ok, lines = check_redis()
    assert ok, "\n".join(lines)


def test_llm_connection():
    ok, lines = check_llm()
    assert ok, "\n".join(lines)


if __name__ == "__main__":
    sys.exit(0 if run_checklist() else 1)
