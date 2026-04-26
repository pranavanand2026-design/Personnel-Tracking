"""'Load demo site': organisation, four demo cameras and a matching layout."""
from counter.sources.demo_registry import DEMO_FEEDS
from counter.web import db

# Grid cells on the 40x26 plan; outline is x 1-29, y 1-23. Blocks follow the
# scene's floor plan: a long corridor with an alcove off it, reception at its
# east end and the east wing corridor beyond reception.
ZONES = [
    {"id": "zone-reception", "name": "Reception", "role": "entry", "camera_id": "CAM-REC-01",
     "x": 21, "y": 13, "w": 8, "h": 10, "capacity": 40},
    {"id": "zone-corridor", "name": "Main Corridor", "role": "general",
     "camera_id": "CAM-COR-01", "x": 2, "y": 8, "w": 18, "h": 5, "capacity": 25},
    {"id": "zone-waiting", "name": "Waiting Alcove", "role": "general",
     "camera_id": "CAM-WAI-01", "x": 4, "y": 15, "w": 9, "h": 6, "capacity": 15},
    {"id": "zone-east", "name": "East Wing Corridor", "role": "general",
     "camera_id": "CAM-EAS-01", "x": 21, "y": 2, "w": 8, "h": 9, "capacity": 20},
]
PATHS = [("zone-reception", "zone-corridor"), ("zone-reception", "zone-east"),
         ("zone-corridor", "zone-waiting")]


def load_demo_site() -> None:
    db.create_org("Demo Organisation", "Hospital, Level 1", 0)
    with db._lock:
        c = db.db()
        for i, f in enumerate(DEMO_FEEDS, 1):
            c.execute("INSERT INTO cameras (id, name, source_type, source, sort) "
                      "VALUES (?, ?, 'demo', ?, ?)", (f["id"], f["name"], f["id"], i))
        c.execute("UPDATE organisation SET outline_x=1, outline_y=1, outline_w=28, "
                  "outline_h=22 WHERE id = 1")
        c.commit()
    db.save_layout({"zones": ZONES,
                    "paths": [{"from_zone": a, "to_zone": b} for a, b in PATHS]})
