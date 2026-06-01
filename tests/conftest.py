from __future__ import annotations

import asyncio
import socket
import threading

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ----- routes ----- #

INDEX_HTML = """
<!doctype html>
<html><head><title>Home</title></head><body>
<h1>Home</h1>
<a href="/ok">ok</a>
<a href="/missing">missing</a>
<a href="/redirect-home">redirect-home</a>
<a href="/redirect-chain">redirect-chain</a>
<a href="/soft404-pattern">soft404</a>
<img src="/img-broken.png" alt="broken">
<img src="/img-ok.png" alt="ok">
<a href="https://nonexistent-host.invalid/">external dead</a>
</body></html>
"""

OK_HTML = "<html><head><title>OK</title></head><body><h1>OK</h1></body></html>"

SOFT404_HTML = (
    "<html><head><title>Страница не найдена</title></head>"
    "<body><h1>Страница не найдена</h1>"
    "<p>Запрашиваемая страница не найдена</p></body></html>"
)


async def index(_):
    return HTMLResponse(INDEX_HTML)


async def ok(_):
    return HTMLResponse(OK_HTML)


async def missing(_):
    return PlainTextResponse("nope", status_code=404)


async def redirect_home(_):
    return RedirectResponse("/", status_code=302)


_chain_steps = ["/r1", "/r2", "/r3", "/r4", "/ok"]


async def redirect_chain_entry(_):
    return RedirectResponse(_chain_steps[0], status_code=302)


def _make_chain_step(idx: int):
    async def step(_):
        return RedirectResponse(_chain_steps[idx + 1], status_code=302)

    return step


async def soft404_pattern(_):
    return HTMLResponse(SOFT404_HTML)


async def img_broken(_):
    return Response("not found", status_code=404)


async def img_ok(_):
    return Response(b"\x89PNG\r\n\x1a\n", media_type="image/png")


# Big "PDF" — 5 MB. Must NOT be downloaded by the crawler (binary content-type).
BIG_PDF = b"%PDF-1.4\n" + b"A" * (5 * 1024 * 1024)


async def big_pdf(_):
    return Response(BIG_PDF, media_type="application/pdf")


# Big HTML — 2 MB. Must be downloaded but capped by --max-body-bytes.
BIG_HTML = (
    b"<html><head><title>big</title></head><body>"
    + b"x" * (2 * 1024 * 1024)
    + b"</body></html>"
)


async def big_html(_):
    return Response(BIG_HTML, media_type="text/html")


# A "probe" route that returns the *same* body for any unknown URL — common soft-404 behavior.
async def catchall_soft404(_):
    return HTMLResponse(SOFT404_HTML)


def _make_app() -> Starlette:
    routes = [
        Route("/", index),
        Route("/ok", ok),
        Route("/missing", missing),
        Route("/redirect-home", redirect_home),
        Route("/redirect-chain", redirect_chain_entry),
        Route("/r1", _make_chain_step(0)),
        Route("/r2", _make_chain_step(1)),
        Route("/r3", _make_chain_step(2)),
        Route("/r4", _make_chain_step(3)),
        Route("/soft404-pattern", soft404_pattern),
        Route("/img-broken.png", img_broken),
        Route("/img-ok.png", img_ok),
        Route("/big.pdf", big_pdf),
        Route("/big.html", big_html),
    ]
    app = Starlette(routes=routes)

    # 404 handler — return the same body as soft404 to support probe-baseline test.
    async def not_found(_request, _exc):
        return HTMLResponse(SOFT404_HTML, status_code=404)

    app.add_exception_handler(404, not_found)
    return app


class _UvicornThread(threading.Thread):
    def __init__(self, app, port: int) -> None:
        super().__init__(daemon=True)
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        asyncio.run(self.server.serve())


@pytest.fixture(scope="session")
def live_server():
    port = _free_port()
    thread = _UvicornThread(_make_app(), port)
    thread.start()
    # Wait until server is ready.
    import time
    import urllib.request

    deadline = time.monotonic() + 5.0
    base = f"http://127.0.0.1:{port}"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/ok", timeout=0.2):
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("test server didn't start in time")
    yield base
    thread.server.should_exit = True
    thread.join(timeout=2)
