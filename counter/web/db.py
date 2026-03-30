"""SQLite store for the site: admin, organisation, roles, cameras, zones, paths.

The layout in this database is the configuration: "Go live" turns it into the
runtime config the zone workers read (see runtime.py).
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get("SITE_DB", ROOT / "data" / "site.db"))

# Plan canvas, in grid cells. The editor snaps everything to this grid.
GRID_W, GRID_H = 40, 26

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  username TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS organisation (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  site_name TEXT NOT NULL,
  outline_x INTEGER NOT NULL DEFAULT 1,
  outline_y INTEGER NOT NULL DEFAULT 1,
  outline_w INTEGER NOT NULL DEFAULT 28,
  outline_h INTEGER NOT NULL DEFAULT 22,
  live INTEGER NOT NULL DEFAULT 0,
  live_since TEXT
);
-- Roles are data: a new role (e.g. restricted) is a new row, not a schema change.
-- behaviour (JSON): counts = in_out | present | arrivals; outline = door | inside | outside
CREATE TABLE IF NOT EXISTS roles (
  key TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  description TEXT NOT NULL,
  behaviour TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cameras (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'none',   -- none | demo | file | rtsp
  source TEXT NOT NULL DEFAULT '',            -- demo feed id, file path or rtsp URL
  offline INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'untested',    -- untested | ok | error
  status_detail TEXT NOT NULL DEFAULT '',
  sort INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS zones (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL REFERENCES roles(key),
  x INTEGER NOT NULL, y INTEGER NOT NULL, w INTEGER NOT NULL, h INTEGER NOT NULL,
  camera_id TEXT REFERENCES cameras(id) ON DELETE SET NULL,
  capacity INTEGER NOT NULL DEFAULT 20
);
CREATE TABLE IF NOT EXISTS paths (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_zone TEXT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
  to_zone TEXT NOT NULL REFERENCES zones(id) ON DELETE CASCADE,
  UNIQUE (from_zone, to_zone)
);
"""

ROLES = [
    ("entry", "Entry zone",
     "A doorway into the site. Counts people coming in and going out.",
     {"counts": "in_out", "outline": "door"}, 1),
    ("general", "General zone",
     "An area inside the site. Counts the people present.",
     {"counts": "present", "outline": "inside"}, 2),
    ("muster", "Muster point",
     "The assembly area outside. Counts people arriving during an evacuation.",
     {"counts": "arrivals", "outline": "outside"}, 3),
]

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


_con: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = connect()
        _con.executescript(SCHEMA)
        for key, label, desc, behaviour, sort in ROLES:
            _con.execute("INSERT OR IGNORE INTO roles VALUES (?,?,?,?,?)",
                         (key, label, desc, json.dumps(behaviour), sort))
        _con.commit()
    return _con


def rows(sql: str, *args) -> list[dict]:
    with _lock:
        return [dict(r) for r in db().execute(sql, args).fetchall()]


def row(sql: str, *args) -> dict | None:
    r = rows(sql, *args)
    return r[0] if r else None


def execute(sql: str, *args) -> None:
    with _lock:
        db().execute(sql, args)
        db().commit()


# ---------- admin ----------
def get_admin() -> dict | None:
    return row("SELECT * FROM admin WHERE id = 1")


def set_admin(username: str, password_hash: str) -> None:
    execute("INSERT INTO admin (id, username, password_hash) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET username = excluded.username, "
            "password_hash = excluded.password_hash", username, password_hash)


# ---------- organisation ----------
def get_org() -> dict | None:
    return row("SELECT * FROM organisation WHERE id = 1")


def create_org(name: str, site_name: str, n_cameras: int) -> None:
    with _lock:
        c = db()
        c.execute("DELETE FROM paths")
        c.execute("DELETE FROM zones")
        c.execute("DELETE FROM cameras")
        c.execute("DELETE FROM organisation")
        c.execute("INSERT INTO organisation (id, name, site_name) VALUES (1, ?, ?)",
                  (name, site_name))
        for i in range(1, n_cameras + 1):
            c.execute("INSERT INTO cameras (id, name, sort) VALUES (?, ?, ?)",
                      (f"CAM-{i:02d}", f"Camera {i}", i))
        c.commit()


def update_org(**fields) -> None:
    allowed = {"name", "site_name", "outline_x", "outline_y", "outline_w", "outline_h",
               "live", "live_since"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if sets:
        execute(f"UPDATE organisation SET {', '.join(k + ' = ?' for k in sets)} WHERE id = 1",
                *sets.values())


# ---------- roles ----------
def get_roles() -> list[dict]:
    out = rows("SELECT * FROM roles ORDER BY sort, key")
    for r in out:
        r["behaviour"] = json.loads(r["behaviour"])
    return out


# ---------- cameras ----------
def get_cameras() -> list[dict]:
    return rows("SELECT * FROM cameras ORDER BY sort, id")


def get_camera(cam_id: str) -> dict | None:
    return row("SELECT * FROM cameras WHERE id = ?", cam_id)


def create_camera(name: str | None = None) -> dict:
    """Next free CAM-NN, not connected yet."""
    with _lock:
        c = db()
        ids = {r[0] for r in c.execute("SELECT id FROM cameras")}
        n = 1
        while f"CAM-{n:02d}" in ids:
            n += 1
        cam_id = f"CAM-{n:02d}"
        sort = (c.execute("SELECT MAX(sort) FROM cameras").fetchone()[0] or 0) + 1
        c.execute("INSERT INTO cameras (id, name, sort) VALUES (?, ?, ?)",
                  (cam_id, name or f"Camera {n}", sort))
        c.commit()
    return get_camera(cam_id)


def update_camera(cam_id: str, **fields) -> None:
    allowed = {"name", "source_type", "source", "offline", "status", "status_detail"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if sets:
        execute(f"UPDATE cameras SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?",
                *sets.values(), cam_id)


# ---------- layout ----------
def get_layout() -> dict:
    org = get_org() or {}
    return {
        "grid": {"w": GRID_W, "h": GRID_H},
        "outline": {k: org.get(f"outline_{k}") for k in ("x", "y", "w", "h")} if org else None,
        "zones": rows("SELECT * FROM zones ORDER BY rowid"),
        "paths": rows("SELECT from_zone, to_zone FROM paths ORDER BY id"),
    }


def save_layout(layout: dict) -> None:
    """Replace zones and paths with the editor's layout (full-document save)."""
    zones = layout.get("zones", [])
    ids = {z["id"] for z in zones}
    with _lock:
        c = db()
        c.execute("DELETE FROM paths")
        c.execute("DELETE FROM zones")
        for z in zones:
            c.execute("INSERT INTO zones (id, name, role, x, y, w, h, camera_id, capacity) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (z["id"], z["name"], z["role"], int(z["x"]), int(z["y"]), int(z["w"]),
                       int(z["h"]), z.get("camera_id") or None, int(z.get("capacity") or 20)))
        for p in layout.get("paths", []):
            if p["from_zone"] in ids and p["to_zone"] in ids and p["from_zone"] != p["to_zone"]:
                c.execute("INSERT OR IGNORE INTO paths (from_zone, to_zone) VALUES (?, ?)",
                          (p["from_zone"], p["to_zone"]))
        o = layout.get("outline")
        if o:
            c.execute("UPDATE organisation SET outline_x=?, outline_y=?, outline_w=?, "
                      "outline_h=? WHERE id = 1", (o["x"], o["y"], o["w"], o["h"]))
        c.commit()
