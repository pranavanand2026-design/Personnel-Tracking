"""Layout validation. "Go live" is allowed only when this returns no problems.

Rules come from role behaviour, not role names, so a new role only needs a
row in the roles table.
"""
from collections import defaultdict


def _overlaps(z: dict, o: dict) -> bool:
    return not (z["x"] >= o["x"] + o["w"] or z["x"] + z["w"] <= o["x"]
                or z["y"] >= o["y"] + o["h"] or z["y"] + z["h"] <= o["y"])


def validate(layout: dict, roles: list[dict], cameras: list[dict]) -> list[dict]:
    """Return problems as [{"code", "message", "zone"?}]."""
    behaviour = {r["key"]: r["behaviour"] for r in roles}
    label = {r["key"]: r["label"] for r in roles}
    cams = {c["id"]: c for c in cameras}
    zones = layout["zones"]
    by_id = {z["id"]: z for z in zones}
    problems = []

    def counts(z):
        return behaviour.get(z["role"], {}).get("counts")

    entries = [z for z in zones if counts(z) == "in_out"]
    if not entries:
        problems.append({"code": "no_entry", "message": "Add an entry zone."})

    used = defaultdict(list)
    for z in zones:
        if z["role"] not in behaviour:
            problems.append({"code": "unknown_role", "zone": z["id"],
                             "message": f"{z['name']}: unknown role '{z['role']}'."})
        cam = z.get("camera_id")
        if not cam:
            problems.append({"code": "no_camera", "zone": z["id"],
                             "message": f"{z['name']} has no camera."})
            continue
        used[cam].append(z)
        c = cams.get(cam)
        if not c:
            problems.append({"code": "missing_camera", "zone": z["id"],
                             "message": f"{z['name']}: camera {cam} no longer exists."})
        elif c["source_type"] == "none" or not c["source"]:
            problems.append({"code": "camera_no_source", "zone": z["id"],
                             "message": f"{z['name']}: camera {c['name']} has no source."})
    for cam, zs in used.items():
        if len(zs) > 1:
            name = cams[cam]["name"] if cam in cams else cam
            problems.append({"code": "camera_twice",
                             "message": f"Camera {name} is assigned to "
                                        f"{', '.join(z['name'] for z in zs)}."})

    # Reachability over paths (either direction) from any entry zone
    graph = defaultdict(set)
    for p in layout["paths"]:
        graph[p["from_zone"]].add(p["to_zone"])
        graph[p["to_zone"]].add(p["from_zone"])
    seen = {z["id"] for z in entries}
    todo = list(seen)
    while todo:
        for nxt in graph[todo.pop()]:
            if nxt not in seen and nxt in by_id:
                seen.add(nxt)
                todo.append(nxt)
    if entries:
        for z in zones:
            if z["id"] not in seen:
                problems.append({"code": "unreachable", "zone": z["id"],
                                 "message": f"{z['name']} can't be reached from an entry. "
                                            "Draw a path to it."})

    outline = layout.get("outline")
    if outline:
        for z in zones:
            where = behaviour.get(z["role"], {}).get("outline")
            inside = _overlaps(z, outline)
            if where == "outside" and inside:
                problems.append({"code": "outside_overlaps", "zone": z["id"],
                                 "message": f"{z['name']} must sit outside the building "
                                            "outline."})
            elif where in ("inside", "door") and not inside:
                problems.append({"code": "inside_outside", "zone": z["id"],
                                 "message": f"{z['name']} ({label.get(z['role'], z['role'])}) "
                                            "must be inside the building outline."})
    return problems
