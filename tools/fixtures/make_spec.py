"""Step 1 of 3: write the *spec* of a synthetic virtual house.

Nothing here is real Home Assistant data. The spec is a simplified set of
registry-like JSON files; step 2 (ha_build_fixture.py) feeds it into a real
Home Assistant core, which writes the authentic `.storage` files we ship.

Usage: python make_spec.py <spec_dir>
"""

import json
import pathlib
import random
import sys

random.seed(7)
out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "spec")
out.mkdir(parents=True, exist_ok=True)

AREAS = [
    ("living_room", "Living Room", ["Lounge", "거실"]),
    ("kitchen", "Kitchen", []),
    ("bedroom", "Bedroom", ["Master"]),
    ("office", "Office", []),
    ("garage", "Garage", []),
    ("garden", "Garden", ["Yard", "Backyard"]),
    ("bathroom", "Bathroom", []),
    ("kids_room", "Kids Room", []),
]

areas = [{"id": a, "name": n, "aliases": al} for a, n, al in AREAS]

devices, entities, states = [], [], []
KINDS = [  # (domain, device_class, entity_category, label, state, attrs)
    ("light", None, None, "Light", "on", {"brightness": 180}),
    ("switch", None, None, "Plug", "off", {}),
    ("sensor", "temperature", None, "Temperature", "21.4",
     {"unit_of_measurement": "°C", "device_class": "temperature"}),
    ("sensor", "humidity", None, "Humidity", "48",
     {"unit_of_measurement": "%", "device_class": "humidity"}),
    ("sensor", "battery", "diagnostic", "Battery", "87",
     {"unit_of_measurement": "%", "device_class": "battery"}),
    ("sensor", "signal_strength", "diagnostic", "Signal strength", "-61",
     {"unit_of_measurement": "dBm", "device_class": "signal_strength"}),
    ("binary_sensor", "motion", None, "Motion", "off", {"device_class": "motion"}),
    ("button", None, "config", "Identify", "unknown", {}),
    ("update", None, "config", "Firmware", "off", {}),
]
n = 0
for area_id, area_name, _ in AREAS:
    for d in range(random.randint(4, 7)):
        n += 1
        dev_id = f"dev{n:04d}"
        dev_name = f"{area_name} Sensor Hub {d + 1}"
        devices.append({"id": dev_id, "name": dev_name,
                        "area_id": area_id if random.random() > 0.12 else None})
        for kind in random.sample(KINDS, k=random.randint(3, 7)):
            domain, dc, cat, label, st, attrs = kind
            obj = f"{dev_name}_{label}".lower().replace(" ", "_")
            eid = f"{domain}.{obj}"
            expose = (cat is None) or random.random() < 0.6  # users bulk-expose
            aliases_v2 = [None]
            if random.random() < 0.15:
                aliases_v2.append(f"{area_name} {label.lower()} please use this long alias")
            entities.append({
                "entity_id": eid, "platform": "acme", "unique_id": eid,
                "device_id": dev_id, "original_name": label,
                "has_entity_name": True, "entity_category": cat,
                "aliases_v2": aliases_v2, "original_device_class": dc,
                "expose": expose,
            })
            a = dict(attrs)
            a["friendly_name"] = f"{dev_name} {label}"
            states.append({"entity_id": eid, "state": st, "attributes": a})

# exposed scripts: they get their own tools, so they must not show up in the static context
for s in ("good_night", "movie_mode", "leaving_home"):
    eid = f"script.{s}"
    entities.append({
        "entity_id": eid, "platform": "script", "unique_id": s, "device_id": None,
        "original_name": s.replace("_", " ").title(), "has_entity_name": False,
        "entity_category": None, "aliases_v2": [None], "original_device_class": None,
        "expose": True,
    })
    states.append({"entity_id": eid, "state": "off",
                   "attributes": {"friendly_name": s.replace("_", " ").title()}})

# entities that exist only as states (no registry entry): the legacy storage path
LEGACY = [
    ("sun.sun", "above_horizon", {"friendly_name": "Sun"}),
    ("weather.home", "sunny", {"friendly_name": "Home Weather"}),
    ("light.porch_lamp_legacy", "off", {"friendly_name": "Porch Lamp"}),
    ("sensor.garden_temperature_legacy", "12.0",
     {"friendly_name": "Garden Temperature", "device_class": "temperature",
      "unit_of_measurement": "°C"}),
    ("sensor.uptime_legacy", "42", {"friendly_name": "Uptime"}),
    ("binary_sensor.front_door_legacy", "off",
     {"friendly_name": "Front Door", "device_class": "door"}),
]
for eid, st, attrs in LEGACY:
    states.append({"entity_id": eid, "state": st, "attributes": attrs})

spec = {"areas": areas, "devices": devices, "entities": entities, "states": states,
        "legacy_exposed": ["sun.sun"]}
(out / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False))
print(f"areas={len(areas)} devices={len(devices)} entities={len(entities)} states={len(states)}")
