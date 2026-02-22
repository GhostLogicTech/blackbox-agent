"""Tests for agent.client — HTTP client (register, ingest, seal)."""

import io
import json
import ssl
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from agent.client import register, post_ingest, post_seal, _make_ssl_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_urlopen(response_dict, status=200):
    """Create a mock for urllib.request.urlopen that returns JSON."""
    body = json.dumps(response_dict).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------

class TestRegister:

    @patch("agent.client.urllib.request.urlopen")
    def test_register_success(self, mock_urlopen_fn, sample_config, mock_register_response):
        mock_urlopen_fn.return_value = _mock_urlopen(mock_register_response)
        result = register(sample_config)
        assert result is not None
        assert result["api_key"] == mock_register_response["api_key"]
        assert result["tenant_id"] == mock_register_response["tenant_id"]

    @patch("agent.client.urllib.request.urlopen")
    @patch("agent.client.socket.gethostname", return_value="my-machine")
    def test_register_sends_correct_body(self, mock_host, mock_urlopen_fn, sample_config):
        mock_urlopen_fn.return_value = _mock_urlopen({"api_key": "glk_x"})
        register(sample_config)
        # Inspect the Request object passed to urlopen
        call_args = mock_urlopen_fn.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["name"] == "auto:my-machine"
        assert body["agent_id"] == sample_config["agent_id"]

    @patch("agent.client.urllib.request.urlopen")
    def test_register_http_error(self, mock_urlopen_fn, sample_config):
        error_body = io.BytesIO(b'{"detail": "rate limited"}')
        mock_urlopen_fn.side_effect = urllib.error.HTTPError(
            url="https://api.ghostlogic.tech/api/v1/register",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=error_body,
        )
        result = register(sample_config)
        assert result is None

    @patch("agent.client.urllib.request.urlopen")
    def test_register_url_error(self, mock_urlopen_fn, sample_config):
        mock_urlopen_fn.side_effect = urllib.error.URLError("Connection refused")
        result = register(sample_config)
        assert result is None

    @patch("agent.client.urllib.request.urlopen")
    def test_register_timeout(self, mock_urlopen_fn, sample_config):
        mock_urlopen_fn.side_effect = TimeoutError("timed out")
        result = register(sample_config)
        assert result is None

    @patch("agent.client.urllib.request.urlopen")
    def test_register_url_construction(self, mock_urlopen_fn, sample_config):
        sample_config["blackbox_url"] = "https://api.ghostlogic.tech/"  # trailing slash
        mock_urlopen_fn.return_value = _mock_urlopen({"api_key": "glk_x"})
        register(sample_config)
        req = mock_urlopen_fn.call_args[0][0]
        assert req.full_url == "https://api.ghostlogic.tech/api/v1/register"


# ---------------------------------------------------------------------------
# post_ingest()
# ---------------------------------------------------------------------------

class TestPostIngest:

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_success(self, mock_urlopen_fn):
        resp = {"status": "ingested", "accepted": 5, "buffer_size": 10}
        mock_urlopen_fn.return_value = _mock_urlopen(resp)
        result = post_ingest("https://api.ghostlogic.tech", "glk_key", {"events": []}, True)
        assert result["status"] == "ingested"
        assert result["accepted"] == 5

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_with_auth_headers(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen({"status": "ingested"})
        post_ingest("https://api.ghostlogic.tech", "glk_key", {}, True)
        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer glk_key"
        assert req.get_header("X-api-key") == "glk_key"

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_no_auth_when_empty(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen({"status": "ingested"})
        post_ingest("https://api.ghostlogic.tech", "", {}, True)
        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("Authorization") is None

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_http_error(self, mock_urlopen_fn):
        error_body = io.BytesIO(b'{"detail": "server error"}')
        mock_urlopen_fn.side_effect = urllib.error.HTTPError(
            url="test", code=500, msg="ISE", hdrs={}, fp=error_body,
        )
        result = post_ingest("https://api.ghostlogic.tech", "glk_key", {}, True)
        assert result["status"] == "error"
        assert result["http_code"] == 500

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_url_error(self, mock_urlopen_fn):
        mock_urlopen_fn.side_effect = urllib.error.URLError("refused")
        result = post_ingest("https://api.ghostlogic.tech", "glk_key", {}, True)
        assert result["status"] == "error"
        assert "refused" in result["detail"]

    @patch("agent.client.urllib.request.urlopen")
    def test_ingest_user_agent_header(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen({"status": "ok"})
        post_ingest("https://api.ghostlogic.tech", "glk_key", {}, True)
        req = mock_urlopen_fn.call_args[0][0]
        assert req.get_header("User-agent") == "GhostLogic-Agent/1.0"


# ---------------------------------------------------------------------------
# post_seal()
# ---------------------------------------------------------------------------

class TestPostSeal:

    @patch("agent.client.urllib.request.urlopen")
    def test_seal_success(self, mock_urlopen_fn):
        resp = {"status": "sealed", "capsule_id": "cap-001"}
        mock_urlopen_fn.return_value = _mock_urlopen(resp)
        result = post_seal("https://api.ghostlogic.tech", "glk_key", True)
        assert result["status"] == "sealed"
        assert result["capsule_id"] == "cap-001"

    @patch("agent.client.urllib.request.urlopen")
    def test_seal_sends_empty_body(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen({"status": "sealed"})
        post_seal("https://api.ghostlogic.tech", "glk_key", True)
        req = mock_urlopen_fn.call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body == {}

    @patch("agent.client.urllib.request.urlopen")
    def test_seal_url_construction(self, mock_urlopen_fn):
        mock_urlopen_fn.return_value = _mock_urlopen({"status": "sealed"})
        post_seal("https://api.ghostlogic.tech/", "glk_key", True)
        req = mock_urlopen_fn.call_args[0][0]
        assert req.full_url == "https://api.ghostlogic.tech/api/v1/seal"


# ---------------------------------------------------------------------------
# SSL context
# ---------------------------------------------------------------------------

class TestSSLContext:

    def test_demo_mode_disables_verification(self):
        ctx = _make_ssl_context(demo_mode=True)
        assert ctx.check_hostname is False
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_prod_mode_enables_verification(self):
        ctx = _make_ssl_context(demo_mode=False)
        assert ctx.check_hostname is True
        assert ctx.verify_mode == ssl.CERT_REQUIRED
