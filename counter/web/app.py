"""FastAPI app: site setup (login, organisation, cameras, layout) and live view.

All /api routes except /api/auth/* need the admin session cookie, as do the
WebSocket and the per-zone MJPEG stream.
"""
import asyncio
import time
from pathlib import Path

import cv2
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.websockets import WebSocketDisconnect

from counter.sources import make_source
from counter.sources.demo_registry import DATASET, DEMO_FEEDS, feed_info
from counter.web import auth, db
from counter.web.demo import load_demo_site
from counter.web.runtime import Runtime, source_block
from counter.web.validation import validate

STATIC = Path(__file__).resolve().parent / "static"
BOUNDARY = "frame"
SOURCE_TYPES = {"none", "demo", "file", "rtsp"}


def require_user(request: Request) -> str:
    user = auth.user_for(request.cookies.get(auth.COOKIE))
    if not user:
        raise HTTPException(401, "Sign in first")
    return user


def problems() -> list[dict]:
    return validate(db.get_layout(), db.get_roles(), db.get_cameras())


def create_app(runtime: Runtime) -> FastAPI:
    app = FastAPI(title="Site monitor")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    authed = [Depends(require_user)]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    # ---------- auth ----------
    @app.get("/api/auth/state")
    def auth_state(request: Request):
        return {"admin_exists": db.get_admin() is not None,
                "user": auth.user_for(request.cookies.get(auth.COOKIE))}

    @app.post("/api/auth/login")
    async def login(request: Request, response: Response):
        body = await request.json()
        token = auth.login(str(body.get("username", "")), str(body.get("password", "")))
        if not token:
            raise HTTPException(401, "Wrong username or password")
        response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict")
        return {"user": body["username"]}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        auth.logout(request.cookies.get(auth.COOKIE))
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    # ---------- organisation ----------
    @app.get("/api/org", dependencies=authed)
    def get_org():
        return {"org": db.get_org(), "live": runtime.live}

    @app.post("/api/org", dependencies=authed)
    async def create_org(request: Request):
        body = await request.json()
        name, site = str(body.get("name", "")).strip(), str(body.get("site_name", "")).strip()
        try:
            n = int(body.get("cameras", 0))  # cameras are usually added from the layout
        except (TypeError, ValueError):
            n = -1
        if not name or not site or not 0 <= n <= 32:
            raise HTTPException(400, "Enter an organisation name and a site name.")
        runtime.stop()
        db.create_org(name, site, n)
        return {"org": db.get_org()}

    @app.put("/api/org", dependencies=authed)
    async def rename_org(request: Request):
        body = await request.json()
        name, site = str(body.get("name", "")).strip(), str(body.get("site_name", "")).strip()
        if not db.get_org():
            raise HTTPException(404, "Set up a site first")
        if not name or not site:
            raise HTTPException(400, "Enter an organisation name and a site name.")
        db.update_org(name=name, site_name=site)
        return {"org": db.get_org()}

    @app.post("/api/demo/load", dependencies=authed)
    def demo_load():
        runtime.stop()
        load_demo_site()
        return {"org": db.get_org()}

    @app.get("/api/roles", dependencies=authed)
    def roles():
        return db.get_roles()

    # ---------- cameras ----------
    @app.get("/api/demo-feeds", dependencies=authed)
    def demo_feeds():
        return {"dataset": DATASET, "feeds": [feed_info(f["id"]) for f in DEMO_FEEDS]}

    @app.get("/api/cameras", dependencies=authed)
    def cameras():
        zones = {z["camera_id"]: z for z in db.get_layout()["zones"] if z["camera_id"]}
        live = {s.get("camera_id"): s for s in runtime.states()}
        out = []
        for c in db.get_cameras():
            z = zones.get(c["id"])
            s = live.get(c["id"])
            out.append({**c, "zone": {"id": z["id"], "name": z["name"]} if z else None,
                        "live_status": s["status"] if s else None})
        return out

    @app.post("/api/cameras", dependencies=authed)
    async def add_camera(request: Request):
        if not db.get_org():
            raise HTTPException(404, "Set up a site first")
        body = await request.json() if await request.body() else {}
        return db.create_camera(str(body.get("name") or "").strip() or None)

    @app.patch("/api/cameras/{cam_id}", dependencies=authed)
    async def update_camera(cam_id: str, request: Request):
        cam = db.get_camera(cam_id)
        if not cam:
            raise HTTPException(404, "No such camera")
        body = await request.json()
        fields = {k: body[k] for k in ("name", "source_type", "source", "offline") if k in body}
        if "source_type" in fields and fields["source_type"] not in SOURCE_TYPES:
            raise HTTPException(400, "Unknown source type")
        if "name" in fields and not str(fields["name"]).strip():
            raise HTTPException(400, "Camera name can't be empty")
        if "offline" in fields:
            fields["offline"] = 1 if fields["offline"] else 0
        if {"source_type", "source"} & fields.keys():
            fields.update(status="untested", status_detail="")
        db.update_camera(cam_id, **fields)
        if "offline" in fields:
            await asyncio.to_thread(runtime.set_camera_offline, cam_id, bool(fields["offline"]))
        return db.get_camera(cam_id)

    @app.get("/api/cameras/{cam_id}/snapshot", dependencies=authed)
    async def snapshot(cam_id: str):
        cam = db.get_camera(cam_id)
        if not cam:
            raise HTTPException(404, "No such camera")

        def grab():
            epoch = (runtime.config or {}).get("demo_epoch", time.time())
            src = make_source(source_block(cam, epoch))
            try:
                frame, _ = src.read()
                info = src.source_info
            finally:
                src.close()
            if frame is None:
                raise IOError("no frame from source")
            frame = cv2.resize(frame, (640, int(640 * frame.shape[0] / frame.shape[1])))
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            return jpg.tobytes(), info

        try:
            data, info = await asyncio.to_thread(grab)
        except Exception as e:
            db.update_camera(cam_id, status="error", status_detail=str(e))
            raise HTTPException(502, f"No picture: {e}")
        db.update_camera(cam_id, status="ok",
                         status_detail=f"{info.get('width')}x{info.get('height')}")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    # ---------- layout ----------
    @app.get("/api/layout", dependencies=authed)
    def get_layout():
        return {**db.get_layout(), "problems": problems()}

    @app.put("/api/layout", dependencies=authed)
    async def put_layout(request: Request):
        body = await request.json()
        try:
            db.save_layout(body)
        except (KeyError, ValueError, TypeError) as e:
            raise HTTPException(400, f"Bad layout: {e}")
        except Exception as e:  # sqlite constraint errors
            raise HTTPException(400, f"Layout not saved: {e}")
        return {"saved": True, "problems": problems()}

    # ---------- live ----------
    @app.get("/api/live", dependencies=authed)
    def live_state():
        cfg = runtime.config
        return {"live": runtime.live, "since": cfg["generated_at"] if cfg else None}

    @app.post("/api/live/start", dependencies=authed)
    async def go_live():
        found = problems()
        if found:
            raise HTTPException(409, {"message": "Fix the layout first", "problems": found})
        cfg = await asyncio.to_thread(runtime.go_live)
        return {"live": True, "since": cfg["generated_at"], "zones": len(cfg["zones"])}

    @app.post("/api/live/stop", dependencies=authed)
    async def stop_live():
        await asyncio.to_thread(runtime.stop)
        return {"live": False}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        if not auth.user_for(socket.cookies.get(auth.COOKIE)):
            await socket.close(code=4401)
            return
        await socket.accept()
        try:
            while True:
                await socket.send_json({"live": runtime.live, "zones": runtime.states(),
                                        "people": runtime.people()})
                await asyncio.sleep(1.0)
        except (WebSocketDisconnect, RuntimeError):
            pass

    @app.get("/api/people/{name}", dependencies=authed)
    def person(name: str):
        p = runtime.person(name)
        if p is None:
            raise HTTPException(404, f"{name} is not known (people are forgotten 30 minutes after they were last seen)")
        return p

    @app.get("/zones/{zone_id}/stream", dependencies=authed)
    async def stream(zone_id: str, request: Request):
        zs = runtime.sup.streams.get(zone_id) if runtime.sup else None
        if zs is None:
            raise HTTPException(404, f"Zone {zone_id} is not live")

        async def frames():
            zs.add_viewer()
            last = -1
            try:
                while not await request.is_disconnected():
                    if zs.seq != last and zs.latest is not None:
                        last = zs.seq
                        yield (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                               f"Content-Length: {len(zs.latest)}\r\n\r\n").encode() \
                            + zs.latest + b"\r\n"
                    await asyncio.sleep(0.01)
            finally:
                zs.remove_viewer()

        return StreamingResponse(
            frames(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store"})

    return app
