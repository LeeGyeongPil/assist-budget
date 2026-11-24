"""Which entities does the ``conversation`` (Assist) assistant see?

Order of decision, as in Home Assistant 2026.11 ``exposed_entities.py``:

1. an explicit ``should_expose`` stored on the registry entry
   (``options.conversation``) or, for entities outside the registry, in
   ``homeassistant.exposed_entities``;
2. otherwise, if "expose new entities" is on, the built-in default rules;
3. otherwise not exposed.

The default rule table below is copied from HA 2026.11.3 (Apache-2.0, see NOTICE).
"""

from __future__ import annotations

from typing import Any

from .storage import Storage

ASSISTANT = "conversation"

DEFAULT_EXPOSED_DOMAINS = frozenset({
    "climate", "cover", "fan", "humidifier", "light", "media_player",
    "scene", "switch", "todo", "vacuum", "water_heater",
})
DEFAULT_BINARY_SENSOR_CLASSES = frozenset({
    "door", "garage_door", "lock", "motion", "opening", "presence", "window",
})
DEFAULT_SENSOR_CLASSES = frozenset({
    "aqi", "carbon_monoxide", "carbon_dioxide", "humidity", "pm10", "pm25",
    "temperature", "volatile_organic_compounds",
})


def device_class(entity_id: str, storage: Storage) -> str | None:
    """Device class from the state if the entity has one, else from the registry."""
    state = storage.states.get(entity_id)
    if state is not None:
        return state["attributes"].get("device_class")
    entry = storage.entities.get(entity_id)
    if entry is None:
        return None
    return entry.get("device_class") or entry.get("original_device_class")


def default_exposed(entity_id: str, storage: Storage) -> bool:
    """HA's ``_is_default_exposed`` for an entity without a stored setting."""
    entry = storage.entities.get(entity_id)
    if entry and (entry.get("entity_category") is not None or entry.get("hidden_by") is not None):
        return False
    domain = entity_id.split(".", 1)[0]
    if domain in DEFAULT_EXPOSED_DOMAINS:
        return True
    if entity_id not in storage.states and entry is None:
        return False
    klass = device_class(entity_id, storage)
    if domain == "binary_sensor":
        return klass in DEFAULT_BINARY_SENSOR_CLASSES
    if domain == "sensor":
        return klass in DEFAULT_SENSOR_CLASSES
    return False


def stored_setting(entity_id: str, storage: Storage) -> bool | None:
    """The explicit ``should_expose`` value, or None when nothing is stored."""
    entry = storage.entities.get(entity_id)
    if entry is not None:
        options: Any = (entry.get("options") or {}).get(ASSISTANT) or {}
    else:
        options = ((storage.legacy_exposed.get(entity_id) or {}).get("assistants") or {}).get(ASSISTANT) or {}
    value = options.get("should_expose")
    return value if isinstance(value, bool) else None


def should_expose(entity_id: str, storage: Storage) -> bool:
    """Whether Assist sees ``entity_id`` (offline estimate, see README "upper estimate")."""
    stored = stored_setting(entity_id, storage)
    if stored is not None:
        return stored
    if storage.expose_new:
        return default_exposed(entity_id, storage)
    return False
