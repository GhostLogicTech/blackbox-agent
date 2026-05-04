"""HTTP client — error-hardened with SHA256 signing, retries, and offline queue."""

import hashlib
import hmac
import json
import logging
import os
import socket
import time
import urllib.request
import urllib.error
import ssl

log = logging.getLogger("ghostlogic.client")


# ============================================================
# HMAC-SHA256 signing
# ============================================================

def _sign_payload(body_bytes: bytes, secret: str) -> str:
    """HMAC-SHA256 sign a payload. Returns hex digest."""
    return hmac.new(
        secret.encode("utf-8"),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()


# ============================================================
# SSL
# ============================================================

def _make_ssl_context(demo_mode: bool) -> ssl.SSLContext:
    if demo_mode:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


# ============================================================
# Offline queue — saves failed payloads to disk
# ============================================================

def queue_to_disk(payload: dict, queue_dir: str) -> None:
    """Save a failed payload to the offline queue directory."""
    os.makedirs(queue_dir, exist_ok=True)
    filename = f"payload_{int(time.time() * 1000)}.json"
    path = os.path.join(queue_dir, filename)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        log.warning("Queued offline: %s", filename)
    except Exception as e:
        log.error("Failed to queue offline: %s", e)


def flush_queue(queue_dir: str, config: dict) -> int:
    """Flush queued payloads with rate limiting + abort-on-auth-failure.

    Honors these config keys:
        drain_max_posts_per_minute  — sliding 60s window cap on POST count
        drain_max_bytes_per_minute  — sliding 60s window cap on POST bytes
        drain_max_retries_per_batch — per-file retry count
        drain_abort_on_codes        — HTTP codes that stop the flush entirely
        drain_retry_on_codes        — HTTP codes worth retrying within a batch

    Returns count of successfully sent payloads. Partial flushes are normal
    (the next call resumes where this one left off). Files are deleted only
    after successful ingest; corrupt files move to queue_dir/corrupt/.
    """
    if not os.path.isdir(queue_dir):
        return 0

    files = sorted(f for f in os.listdir(queue_dir)
                   if f.endswith(".json") and os.path.isfile(os.path.join(queue_dir, f)))
    if not files:
        return 0

    max_posts_per_min = int(config.get("drain_max_posts_per_minute", 30))
    max_bytes_per_min = int(config.get("drain_max_bytes_per_minute", 50_000_000))
    abort_codes = set(config.get("drain_abort_on_codes", [401, 403, 422]))
    log.info(
        "Flushing %d queued payloads (rate: <=%d posts/min, <=%.1f MB/min)...",
        len(files), max_posts_per_min, max_bytes_per_min / 1_000_000,
    )

    sent = 0
    # Sliding-window tracker: list of (epoch_seconds, byte_count) tuples
    window: list[tuple[float, int]] = []

    def _wait_for_window(next_byte_count: int) -> None:
        """Sleep until adding a POST of next_byte_count would not breach
        either the posts/min cap or the bytes/min cap."""
        while True:
            now = time.time()
            # Drop entries older than 60s
            cutoff = now - 60.0
            while window and window[0][0] < cutoff:
                window.pop(0)
            posts_in_window = len(window)
            bytes_in_window = sum(b for _, b in window)
            posts_ok = posts_in_window < max_posts_per_min
            bytes_ok = bytes_in_window + next_byte_count <= max_bytes_per_min
            if posts_ok and bytes_ok:
                return
            # Sleep until the oldest entry falls out of the window
            sleep_for = max(0.5, (window[0][0] + 60.0) - now) if window else 1.0
            log.info(
                "drain rate cap reached (posts=%d bytes=%d) — sleeping %.1fs",
                posts_in_window, bytes_in_window, sleep_for,
            )
            time.sleep(min(sleep_for, 30.0))

    for filename in files:
        path = os.path.join(queue_dir, filename)
        try:
            file_size = os.path.getsize(path)
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            log.error("Corrupt queue file %s: %s — moving to corrupt/", filename, e)
            corrupt_dir = os.path.join(queue_dir, "corrupt")
            os.makedirs(corrupt_dir, exist_ok=True)
            try:
                os.replace(path, os.path.join(corrupt_dir, filename))
            except OSError:
                pass
            continue

        # Honor rate limits before each POST.
        _wait_for_window(file_size)

        resp = post_ingest(
            config["blackbox_url"],
            config.get("tenant_key", ""),
            payload,
            config.get("demo_mode", True),
            max_retries=int(config.get("drain_max_retries_per_batch", 3)),
        )

        # Record the post in the rate window (count it whether success or not —
        # we burned the request budget either way).
        window.append((time.time(), file_size))

        status = resp.get("status", "")
        http_code = resp.get("http_code")

        if status not in ("error",):
            try:
                os.remove(path)
            except OSError:
                pass
            sent += 1
            continue

        # Hard abort on auth/validation errors — don't keep hammering 61k batches.
        if http_code in abort_codes:
            log.warning(
                "Queue flush ABORTED on HTTP %d (%s). %d/%d sent before abort.",
                http_code, _abort_reason(http_code), sent, len(files),
            )
            break

        # Other failures: stop this flush attempt; resume next cycle.
        log.warning("Queue flush stopped — server still unreachable (status=%s code=%s)",
                    status, http_code)
        break

    if sent:
        log.info("Flushed %d/%d queued payloads", sent, len(files))
    return sent


def _abort_reason(code: int | None) -> str:
    return {
        401: "auth rejected — refresh tenant_key before retrying",
        403: "scope mismatch — tenant_key not allowed for this agent_id",
        422: "payload shape rejected — likely server schema change",
    }.get(int(code) if code else 0, "unknown")


# ============================================================
# Registration
# ============================================================

def register(cfg: dict) -> dict | None:
    """Register this agent with the Blackbox API and get a tenant key."""
    base_url = cfg.get("blackbox_url", "").rstrip("/")
    url = f"{base_url}/api/v1/register"
    hostname = socket.gethostname()
    agent_id = cfg.get("agent_id", "")

    body = json.dumps({"name": f"auto:{hostname}", "agent_id": agent_id}).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "GhostLogic-Agent/2.0")

    ctx = _make_ssl_context(cfg.get("demo_mode", True))

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
            log.info("Registration successful: tenant_id=%s", result.get("tenant_id"))
            return result
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = "(unreadable)"
        log.error("Registration HTTP %d from %s: %s", e.code, url, err_body[:500])
        return None
    except urllib.error.URLError as e:
        log.error("Registration connection failed to %s: %s", url, e.reason)
        return None
    except Exception as e:
        log.error("Registration request failed to %s: %s", url, e)
        return None


# ============================================================
# Ingest — with retry + SHA256 + backoff
# ============================================================

def post_ingest(
    base_url: str,
    tenant_key: str,
    payload: dict,
    demo_mode: bool = True,
    max_retries: int = 3,
) -> dict:
    """POST events to /api/v1/ingest with retry, backoff, and SHA256 signing."""
    url = f"{base_url.rstrip('/')}/api/v1/ingest"
    return _post_with_retry(url, tenant_key, payload, demo_mode, max_retries)


def post_seal(base_url: str, tenant_key: str, demo_mode: bool = True) -> dict:
    """POST to /api/v1/seal."""
    url = f"{base_url.rstrip('/')}/api/v1/seal"
    return _post_with_retry(url, tenant_key, {}, demo_mode, max_retries=2)


def _post_with_retry(
    url: str,
    tenant_key: str,
    payload: dict,
    demo_mode: bool,
    max_retries: int = 3,
) -> dict:
    """POST with exponential backoff retry and HMAC-SHA256 signing."""
    body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    # Codes we never retry — they're permanent rejections for this batch.
    PERMANENT = (400, 401, 403, 404, 410, 422)

    for attempt in range(1, max_retries + 1):
        try:
            result = _post_once(url, tenant_key, body_bytes, demo_mode)
            if result.get("status") != "error" or result.get("http_code", 0) in PERMANENT:
                # Success, or client error (don't retry auth/validation failures)
                return result
        except Exception as e:
            result = {"status": "error", "detail": str(e)}

        if attempt < max_retries:
            backoff = min(2 ** attempt, 30)
            log.warning("Attempt %d/%d failed, retrying in %ds...", attempt, max_retries, backoff)
            time.sleep(backoff)

    log.error("All %d attempts failed for %s", max_retries, url)
    return result


def _post_once(url: str, tenant_key: str, body_bytes: bytes, demo_mode: bool) -> dict:
    """Single POST attempt with SHA256 signature."""
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "GhostLogic-Agent/2.0")

    if tenant_key:
        req.add_header("Authorization", f"Bearer {tenant_key}")
        req.add_header("X-API-Key", tenant_key)
        # SHA256 signature
        sig = _sign_payload(body_bytes, tenant_key)
        req.add_header("X-Signature", sig)
        req.add_header("X-Signature-Algorithm", "hmac-sha256")

    ctx = _make_ssl_context(demo_mode)

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                log.error("Non-JSON response from %s: %s", url, body[:500])
                return {"status": "error", "detail": f"non-JSON: {body[:200]}"}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "(unreadable)"
        log.error("HTTP %d from %s: %s", e.code, url, body[:500])
        return {"status": "error", "http_code": e.code, "detail": body[:500]}
    except urllib.error.URLError as e:
        log.error("Connection failed to %s: %s", url, e.reason)
        return {"status": "error", "detail": str(e.reason)}
    except Exception as e:
        log.error("Request failed to %s: %s", url, e)
        return {"status": "error", "detail": str(e)}
