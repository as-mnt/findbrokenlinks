"""Fetcher must send a well-formed request, not just User-Agent.

Some WAFs return 403 to bot-looking minimal-header clients. Sending the
standard Accept and Accept-Language headers (with our honest UA still in place)
significantly reduces those false-positive 403s.
"""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from findbrokenlinks.fetcher import Fetcher
from findbrokenlinks.rate_limiter import NoopLimiter

# A header-echo server that bounces back whatever the client sent.
_seen: list[dict[str, str]] = []


async def _echo(request):
    _seen.append(dict(request.headers))
    return PlainTextResponse("ok")


@pytest.fixture(scope="module")
def echo_server():
    import socket
    import time
    import urllib.request

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    app = Starlette(routes=[Route("/", _echo)])
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run():
        asyncio.run(server.serve())

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    deadline = time.monotonic() + 5.0
    base = f"http://127.0.0.1:{port}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/", timeout=0.2):
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("echo server didn't start in time")
    yield base
    server.should_exit = True
    t.join(timeout=2)


@pytest.mark.asyncio
async def test_fetcher_sends_accept_and_accept_language(echo_server):
    _seen.clear()
    async with httpx.AsyncClient(timeout=5.0) as client:
        fetcher = Fetcher(
            client,
            NoopLimiter(),
            timeout_s=5.0,
            max_redirects=5,
            user_agent="findbrokenlinks/0.1-test",
        )
        await fetcher.fetch(echo_server + "/")

    assert _seen, "echo server didn't see a request"
    headers = _seen[-1]
    assert headers.get("user-agent") == "findbrokenlinks/0.1-test"
    # The exact Accept / Accept-Language values don't matter as much as them
    # being present and non-empty — that's what flips WAFs from 403 to 200.
    assert headers.get("accept"), "Accept header must be sent"
    assert headers.get("accept-language"), "Accept-Language header must be sent"
    # Accept must announce HTML.
    assert "text/html" in headers["accept"]
