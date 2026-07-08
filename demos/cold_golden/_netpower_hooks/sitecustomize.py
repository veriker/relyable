"""Injected via PYTHONPATH so it loads at interpreter startup, BEFORE the skill runs.

Freezes the clock (so request-build becomes a pure function of inputs), no-ops sleeps (so
retry/backoff can't eat the subprocess timeout), and intercepts every common HTTP egress
(requests / urllib / http.client / httpx), recording each outbound request to NETPOWER_REC
as JSONL and short-circuiting it with a generic fake response. No bytes leave the process.
"""

import datetime as _dt
import json
import os
import sys
import time as _time

_REC = os.environ.get("NETPOWER_REC", "/tmp/netpower_rec.jsonl")
_FROZEN = _dt.datetime(2026, 6, 21, 12, 0, 0, 123000, tzinfo=_dt.timezone.utc)


def _body_str(body):
    """Stringify a request body (POST params often live here, not the query string)."""
    if body is None:
        return ""
    try:
        if isinstance(body, (bytes, bytearray)):
            return body.decode("utf-8", "replace")[:4000]
        if isinstance(body, (dict, list)):
            return json.dumps(body)[:4000]
        return str(body)[:4000]
    except Exception:
        return ""


def _record(method, url, headers=None, body=None):
    try:
        with open(_REC, "a") as f:
            f.write(
                json.dumps(
                    {
                        "method": (method or "GET").upper(),
                        "url": url,
                        "headers": {
                            str(k): str(v) for k, v in dict(headers or {}).items()
                        },
                        "body": _body_str(body),
                        "has_body": body is not None,
                    }
                )
                + "\n"
            )
    except Exception:
        pass


# --- freeze clock + kill sleeps --------------------------------------------------------
class _FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return _FROZEN if tz is None else _FROZEN.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _FROZEN.replace(tzinfo=None)


_dt.datetime = _FrozenDT
_time.sleep = lambda *a, **k: None
_time.time = lambda: 1782475200.123  # fixed epoch matching _FROZEN
try:
    import random as _random

    _random.seed(0)
except Exception:
    pass


# --- HARD network kill-switch: backstop so an unpatched HTTP lib (aiohttp, raw socket)
#     can NEVER reach the real internet. Record the attempt, then refuse the connect.
try:
    import socket as _socket

    _orig_connect = _socket.socket.connect

    def _guard_connect(self, address):
        try:
            host = address[0] if isinstance(address, tuple) else str(address)
        except Exception:
            host = ""
        if host in ("127.0.0.1", "::1", "localhost", ""):
            return _orig_connect(self, address)
        _record("CONNECT", f"socket://{host}")
        raise OSError("netpower: external network blocked (offline harness)")

    _socket.socket.connect = _guard_connect
except Exception:
    pass


# --- generic fake response (covers requests + httpx response surfaces) -----------------
class _FakeResp:
    status_code = 200
    text = '{"code":"0","data":[{}],"results":[],"items":[],"markets":[]}'
    content = text.encode()
    headers = {"content-type": "application/json"}
    ok = True

    def json(self):
        return {"code": "0", "data": [{}], "results": [], "items": [], "markets": []}

    def raise_for_status(self):
        return None

    def read(self):
        return self.content

    # httpx.Response-ish
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- requests ---------------------------------------------------------------------------
try:
    import requests

    def _req(self, method, url, **kw):
        _record(method, url, kw.get("headers"), kw.get("data") or kw.get("json"))
        return _FakeResp()

    requests.Session.request = _req
except Exception:
    pass

# --- urllib.request ---------------------------------------------------------------------
try:
    import urllib.request as _u

    class _UResp:
        status = 200

        def read(self, *a):
            return _FakeResp.content

        def getcode(self):
            return 200

        def info(self):
            return {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _urlopen(url, *a, **kw):
        if hasattr(url, "full_url"):
            _record(
                getattr(url, "method", "GET"),
                url.full_url,
                dict(getattr(url, "headers", {})),
            )
        else:
            _record("GET", url)
        return _UResp()

    _u.urlopen = _urlopen
except Exception:
    pass

# --- http.client ------------------------------------------------------------------------
try:
    import http.client as _h

    _orig_req = _h.HTTPConnection.request

    def _hc_request(self, method, url, body=None, headers=None, **kw):
        scheme = "https" if isinstance(self, _h.HTTPSConnection) else "http"
        _record(method, f"{scheme}://{self.host}{url}", headers or {}, body)
        # do not actually connect
        raise _NetCut()

    class _NetCut(Exception):
        pass

    _h.HTTPConnection.request = _hc_request
except Exception:
    pass

# --- httpx ------------------------------------------------------------------------------
try:
    import httpx

    def _httpx_send(self, request, *a, **kw):
        _record(request.method, str(request.url), dict(request.headers))
        return _FakeResp()

    httpx.Client.send = _httpx_send
    if hasattr(httpx, "AsyncClient"):

        async def _httpx_asend(self, request, *a, **kw):
            _record(request.method, str(request.url), dict(request.headers))
            return _FakeResp()

        httpx.AsyncClient.send = _httpx_asend
except Exception:
    pass
