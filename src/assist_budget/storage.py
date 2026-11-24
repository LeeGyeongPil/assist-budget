"""Read a Home Assistant ``.storage`` folder (read-only, forgiving).

Home Assistant adds and renames registry fields from release to release, so
everything here uses ``dict.get`` and tolerates missing keys. Files are only
ever opened for reading.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import AssistBudgetError

# A warning is (message key, placeholder values); it is translated when printed.
Warn = tuple[str, dict[str, Any]]

# Registry versions this tool was verified against (HA 2026.11.3).
KNOWN_VERSIONS = {
    "core.entity_registry": (1, 24),
    "core.device_registry": (3, 4),
    "core.area_registry": (1, 9),
}


@dataclass
class Storage:
    """Parsed registries plus the last known states."""

    config_dir: Path
    ha_version: str | None
    entities: dict[str, dict[str, Any]]  # registry entries, in file order
    devices: dict[str, dict[str, Any]]  # devices and child devices by id
    child_device_ids: set[str]
    areas: dict[str, dict[str, Any]]
    states: dict[str, dict[str, Any]]  # entity_id -> {"state", "attributes"}
    legacy_exposed: dict[str, dict[str, Any]]  # exposed_entities.json: entities outside the registry
    expose_new: bool
    warnings: list[Warn] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:  # read-only
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AssistBudgetError("err_bad_storage_file", path=str(path), reason=str(exc)) from exc
    return data if isinstance(data, dict) else None


def find_dirs(path: str | Path) -> tuple[Path, Path]:
    """Return ``(config_dir, storage_dir)`` for a config folder or a ``.storage`` folder."""
    root = Path(path)
    if not root.is_dir():
        raise AssistBudgetError("err_path_not_found", path=str(root))
    if (root / ".storage").is_dir():
        return root, root / ".storage"
    if root.name == ".storage" or (root / "core.entity_registry").is_file():
        return root.parent, root
    raise AssistBudgetError("err_no_storage", path=str(root))


def read_ha_version(config_dir: Path) -> str | None:
    """Read ``<config>/.HA_VERSION`` if it exists."""
    try:
        text = (config_dir / ".HA_VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def _check_version(doc: dict[str, Any], name: str, warnings: list[Warn]) -> None:
    known = KNOWN_VERSIONS[name]
    seen = (doc.get("version"), doc.get("minor_version"))
    if not all(isinstance(part, int) for part in seen):
        return
    if seen[0] != known[0] or seen[1] > known[1]:  # type: ignore[operator]
        warnings.append(("warn_registry_version", {
            "name": name, "seen": f"{seen[0]}.{seen[1]}", "known": f"{known[0]}.{known[1]}"}))


def load_storage(path: str | Path) -> Storage:
    """Load the registries from ``path`` (a config folder or its ``.storage`` folder)."""
    config_dir, storage_dir = find_dirs(path)
    warnings: list[Warn] = []

    entity_doc = _read_json(storage_dir / "core.entity_registry")
    if entity_doc is None:
        raise AssistBudgetError("err_no_entity_registry", path=str(storage_dir))
    device_doc = _read_json(storage_dir / "core.device_registry") or {}
    area_doc = _read_json(storage_dir / "core.area_registry") or {}
    state_doc = _read_json(storage_dir / "core.restore_state")
    exposed_doc = _read_json(storage_dir / "homeassistant.exposed_entities") or {}
    for name, doc in (("core.entity_registry", entity_doc), ("core.device_registry", device_doc),
                      ("core.area_registry", area_doc)):
        if doc:
            _check_version(doc, name, warnings)

    entities = {e["entity_id"]: e for e in entity_doc.get("data", {}).get("entities", []) if "entity_id" in e}
    device_data = device_doc.get("data", {})
    devices = {d["id"]: d for d in device_data.get("devices", []) if "id" in d}
    child_ids: set[str] = set()
    for child in device_data.get("child_devices", []):
        if "id" in child:
            devices[child["id"]] = child
            child_ids.add(child["id"])
    areas = {a["id"]: a for a in area_doc.get("data", {}).get("areas", []) if "id" in a}

    states: dict[str, dict[str, Any]] = {}
    if state_doc is None:
        warnings.append(("warn_no_restore_state", {}))
    else:
        for item in state_doc.get("data", []):
            state = item.get("state", {}) if isinstance(item, dict) else {}
            if "entity_id" in state:
                states[state["entity_id"]] = {"state": state.get("state"), "attributes": state.get("attributes") or {}}

    exposed_data = exposed_doc.get("data", {})
    legacy = exposed_data.get("exposed_entities", {}) or {}
    prefs = (exposed_data.get("assistants", {}) or {}).get("conversation", {}) or {}
    expose_new = bool(prefs.get("expose_new", True))  # Assist exposes new entities by default

    return Storage(
        config_dir=config_dir,
        ha_version=read_ha_version(config_dir),
        entities=entities,
        devices=devices,
        child_device_ids=child_ids,
        areas=areas,
        states=states,
        legacy_exposed=legacy,
        expose_new=expose_new,
        warnings=warnings,
    )
