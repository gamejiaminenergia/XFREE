"""The HTTP surface: REST, a WebSocket push and the frame as PNG.

This is a *thin* adapter over the hub; the engine never runs here.  Everything a
client can see is either the latest published state or the latest frame, so a
slow or broken client cannot slow the session down.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from jev_duum.theme import (
    ALARM,
    BG,
    INFO,
    OFF,
    OK,
    PANEL,
    RULE,
    STATIC,
    TITLE,
    TRACK,
    VALUE,
    WARN,
)

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
STREAM_INTERVAL = 1 / 15  # 15 frames a second is plenty for a schematic view


def palette_css() -> str:
    """The palette, straight from ``theme.py``, as CSS custom properties."""

    names = {
        "bg": BG, "panel": PANEL, "rule": RULE, "static": STATIC, "title": TITLE,
        "value": VALUE, "ok": OK, "warn": WARN, "alarm": ALARM, "info": INFO,
        "off": OFF, "track": TRACK,
    }
    return "\n".join(f"  --{name}: {value};" for name, value in names.items())


def create_app(hub, session=None, meta=None, *, control_token: str | None = None) -> FastAPI:
    app = FastAPI(title="jev-service", version="1.0", description=(
        "Live state, decisions and frames of the Jev pilot, over HTTP."
    ))
    app.state.hub = hub
    app.state.session = session
    app.state.meta = dict(meta or {})
    app.state.control_token = control_token
    app.state.started = time.time()

    def _session():
        if app.state.session is None:
            raise HTTPException(status_code=503, detail="this server has no session attached")
        return app.state.session

    @app.get("/health")
    def health():
        state = hub.state() or {}
        return {
            "ok": True,
            "service": "jev-service",
            "uptime_s": round(time.time() - app.state.started, 1),
            "tick": state.get("tick"),
            "seq": hub.seq(),
            "dropped": hub.dropped(),
        }

    @app.get("/api/meta")
    def api_meta():
        session = app.state.session
        return {
            **app.state.meta,
            "paused": bool(getattr(session, "paused", False)),
            "decision_rate": getattr(session, "decision_rate", None),
            "palette": palette_css(),
        }

    @app.get("/api/state")
    def api_state(full: int = 1):
        state = hub.state()
        if state is None:
            raise HTTPException(status_code=503, detail="no frame published yet")
        if not full:
            state = {key: value for key, value in state.items() if key != "snapshot"}
        return state

    @app.get("/api/frame.png")
    def api_frame():
        encoded = hub.png()
        if encoded is None:
            raise HTTPException(status_code=503, detail="no frame yet (run with pixels on)")
        payload, seq = encoded
        return Response(
            content=payload, media_type="image/png",
            headers={"Cache-Control": "no-store", "X-Frame-Seq": str(seq)},
        )

    @app.get("/api/frame.raw")
    def api_frame_raw():
        """The engine buffer as it is: 8-bit RGB, for a client that paints it.

        A terminal UI composes its own cells from these bytes; making it decode a
        PNG first would be work with nothing to show for it.
        """

        rgb = hub.rgb()
        if rgb is None:
            raise HTTPException(status_code=503, detail="no frame yet (run with pixels on)")
        width, height = hub.size()
        return Response(
            content=rgb, media_type="application/octet-stream",
            headers={
                "Cache-Control": "no-store",
                "X-Frame-Width": str(width),
                "X-Frame-Height": str(height),
                "X-Frame-Seq": str(hub.seq()),
            },
        )

    @app.get("/api/frames.stream")
    async def api_stream():
        """multipart/x-mixed-replace: an ``<img>`` follows it without JavaScript."""

        async def parts():
            last = -1
            while True:
                encoded = hub.png()
                if encoded is not None:
                    payload, seq = encoded
                    if seq != last:
                        last = seq
                        yield (
                            b"--frame\r\nContent-Type: image/png\r\n"
                            b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n"
                            + payload + b"\r\n"
                        )
                await asyncio.sleep(STREAM_INTERVAL)

        return StreamingResponse(
            parts(), media_type="multipart/x-mixed-replace; boundary=frame"
        )

    @app.websocket("/ws")
    async def websocket(websocket: WebSocket):
        await websocket.accept()
        loop = asyncio.get_running_loop()
        subscriber = hub.subscribe()

        async def pump():
            while True:
                payload = await loop.run_in_executor(None, subscriber.get)
                await websocket.send_text(json.dumps(payload))

        pump_task = asyncio.ensure_future(pump())
        try:
            while True:
                # Anything the client sends is ignored: this is a push channel.
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            pump_task.cancel()
            hub.unsubscribe(subscriber)

    @app.post("/api/control")
    async def api_control(request: Request):
        session = _session()
        token = app.state.control_token
        if token and request.headers.get("x-control-token") != token:
            raise HTTPException(status_code=403, detail="bad or missing x-control-token")
        body = await request.json()
        if "paused" in body:
            session.set_paused(bool(body["paused"]))
        if "decision_rate" in body:
            session.set_decision_rate(float(body["decision_rate"]))
        return {
            "paused": session.paused,
            "decision_rate": session.decision_rate,
        }

    @app.get("/", response_class=HTMLResponse)
    def index():
        page = (WEB_DIR / "index.html").read_text()
        meta_block = json.dumps({**app.state.meta, "palette": None}, default=str)
        return HTMLResponse(
            page.replace("/* PALETTE */", palette_css()).replace("__META__", meta_block)
        )

    return app
