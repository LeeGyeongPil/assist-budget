"""Entity names, aliases and areas, computed the way Home Assistant 2026.11 does.

The registry stores ``aliases_v2``: a list whose ``null`` entries mean "the
computed full entity name". HA resolves it at run time from the device name
and the entity name, so reading ``name`` or ``original_name`` alone is wrong.
"""

from __future__ import annotations

from typing import Any

from .storage import Storage


def _strip_prefix(entity_name: str | None, prefix: str | None) -> str | None:
    """Remove a leading device name from an entity name (HA ``_async_strip_prefix_from_entity_name``)."""
    if not entity_name or not prefix:
        return None
    if not entity_name.casefold().startswith(prefix.casefold()):
        return None
    rest = entity_name[len(prefix):].lstrip(" -_:")
    return rest or None


def _device_name(device: dict[str, Any]) -> str | None:
    return device.get("name_by_user") or device.get("name")


def entity_part(entity: dict[str, Any], raw_device_name: str | None) -> str | None:
    """The entity's own name part (explicit ``name`` or the original name)."""
    if entity.get("name") is not None:
        return entity["name"]
    original = entity.get("original_name")
    if not entity.get("has_entity_name"):
        stripped = _strip_prefix(original, raw_device_name)
        if stripped is not None:
            return stripped
    return original


def effective_area_id(device: dict[str, Any], storage: Storage) -> str | None:
    """A device's own area; a child device without one inherits its parent's."""
    if device.get("area_id") is not None:
        return device["area_id"]
    parent = storage.devices.get(device.get("parent_device_id") or "")
    if device.get("id") in storage.child_device_ids and parent is not None:
        return parent.get("area_id")
    return None


def full_entity_name(entity: dict[str, Any], storage: Storage) -> str:
    """HA's ``async_get_full_entity_name``: [parent device] [device] entity name.

    The device name is only part of the name while the entity has no area of its
    own (``next_name_part`` is then the device), and a parent device name only
    joins for a child device without an area.
    """
    device = storage.devices.get(entity.get("device_id") or "")
    raw_device_name = _device_name(device) if device else None
    parts: list[str | None] = []
    if device is not None and entity.get("area_id") is None:
        if device.get("id") in storage.child_device_ids and device.get("area_id") is None:
            parent = storage.devices.get(device.get("parent_device_id") or "")
            parts.append(_device_name(parent) if parent else None)
        parts.append(raw_device_name)
    parts.append(entity_part(entity, raw_device_name))
    return " ".join(part for part in parts if part)


def legacy_friendly_name(entity: dict[str, Any], storage: Storage) -> str:
    """The name HA writes into the state's ``friendly_name``: device name + entity name."""
    if entity.get("compat_name") is not None:
        return entity["compat_name"]
    device = storage.devices.get(entity.get("device_id") or "")
    raw_device_name = _device_name(device) if device else None
    parts = [raw_device_name, entity_part(entity, raw_device_name)]
    return " ".join(part for part in parts if part)


def entity_aliases(entity: dict[str, Any], storage: Storage) -> list[str]:
    """All names of an entity in user order; ``null`` becomes the computed name."""
    raw = entity.get("aliases_v2")
    if raw is None:  # older registry: aliases without a computed slot
        raw = [None, *entity.get("aliases", [])]
    return [(full_entity_name(entity, storage) if alias is None else str(alias)).strip() for alias in raw]


def entity_area_names(entity: dict[str, Any], storage: Storage) -> list[str]:
    """Area name plus sorted area aliases: the entity's area first, else its device's."""
    area_id = entity.get("area_id")
    if area_id is None:
        device = storage.devices.get(entity.get("device_id") or "")
        if device is not None:
            area_id = effective_area_id(device, storage)
    area = storage.areas.get(area_id) if area_id is not None else None
    if area is None:
        return []
    return [area["name"], *sorted(area.get("aliases", []))]


def state_name(entity_id: str, storage: Storage, entity: dict[str, Any] | None) -> str:
    """HA ``State.name``: the friendly name of the last state, else a computed one."""
    state = storage.states.get(entity_id)
    if state is not None:
        friendly = state["attributes"].get("friendly_name")
        if friendly:
            return str(friendly)
        return entity_id.split(".", 1)[1].replace("_", " ")
    if entity is not None:
        return legacy_friendly_name(entity, storage) or entity_id.split(".", 1)[1].replace("_", " ")
    return entity_id.split(".", 1)[1].replace("_", " ")
