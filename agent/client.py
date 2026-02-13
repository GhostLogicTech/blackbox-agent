"""HTTP client for GhostLogic Black Box API."""

import json
import logging
import urllib.request
import urllib.error
import ssl

log = logging.getLogger("ghostlogic.client")


def _make_ssl_context(demo_mode: bool) -> ssl.SSLContext:
    if demo_mode:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def post_ingest(base_url: str, tenant_key: str, payload: dict, demo_mode: bool = True) -> dict:
    """POST events to /api/v1/ingest. Returns parsed response dict."""
    url = f"{base_url.rstrip('/')}/api/v1/ingest"
    return _post(url, tenant_key, payload, demo_mode)


def post_seal(base_url: str, tenant_key: str, demo_mode: bool = True) -> dict:
    """POST to /api/v1/seal. Returns parsed response dict."""
    url = f"{base_url.rstrip('/')}/api/v1/seal"
    return _post(url, tenant_key, {}, demo_mode)


def _post(url: str, tenant_key: str, payload: dict, demo_mode: bool) -> dict:
    """Generic POST with JSON body and auth header."""
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if tenant_key:
        req.add_header("Authorization", f"Bearer {tenant_key}")
        req.add_header("X-API-Key", tenant_key)

    ctx = _make_ssl_context(demo_mode)

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                log.error("Non-JSON response from %s: %s", url, body[:500])
                return {"status": "error", "detail": f"non-JSON response: {body[:200]}"}
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
