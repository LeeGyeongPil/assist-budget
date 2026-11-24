"""Rebuild the Assist system prompt from a ``.storage`` folder, without Home Assistant.

``reconstruct`` walks the entities the way HA's ``async_get_exposed_entities``
does, dumps them as YAML with the same options HA uses, and joins the prompt
pieces of the matching profile. For HA 2026.11.3 the result is byte-identical
to what a real HA produces (see ``tests/test_reconstruct.py``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field

import yaml

from . import names
from .expose import should_expose
from .profiles import AREA_PROMPT, NO_TIMER_PROMPT, STATIC_HEADER, Profile
from .storage import Storage, Warn

# Calendars and scripts get their own tools, so HA keeps them out of the static context.
EXCLUDED_DOMAINS = frozenset({"calendar", "script"})


def dump_yaml(data: object) -> str:
    """YAML text exactly as ``homeassistant.util.yaml.dump``: block style, unicode kept."""
    return yaml.dump(data, Dumper=yaml.SafeDumper, default_flow_style=False, allow_unicode=True, sort_keys=False)


@dataclass
class Item:
    """One exposed entity and the text it adds to the prompt."""

    entity_id: str
    domain: str
    names: str
    areas: str | None
    fragment: str  # this entity's own YAML list item

    @property
    def area(self) -> str | None:
        """The primary area name, used for grouping."""
        return self.areas.split(", ", 1)[0] if self.areas else None


@dataclass
class Reconstruction:
    """The rebuilt prompt and its per-entity pieces."""

    profile: Profile
    items: list[Item]
    static_yaml: str
    system_prompt: str
    warnings: list[Warn] = field(default_factory=list)


def _candidates(storage: Storage) -> dict[str, dict | None]:
    """Entities HA could list: registry entries that are not disabled, plus state-only entities."""
    found: dict[str, dict | None] = {}
    for entity_id, entry in storage.entities.items():
        if entry.get("disabled_by") is None:
            found[entity_id] = entry
    for entity_id in storage.states:
        found.setdefault(entity_id, None)
    return found


def collect_items(storage: Storage, exclude: Collection[str] = ()) -> tuple[list[Item], list[Warn]]:
    """Exposed entities in HA order (sorted by state name), minus ``exclude``."""
    warnings: list[Warn] = []
    skipped = set(exclude)
    candidates = _candidates(storage)
    for entity_id in storage.legacy_exposed:  # exposed, but neither in the registry nor in the states
        if entity_id not in candidates and should_expose(entity_id, storage):
            warnings.append(("warn_entity_skipped_no_name", {"entity_id": entity_id}))
    ordered = sorted(
        candidates.items(),
        key=lambda pair: names.state_name(pair[0], storage, pair[1]),  # stable: registry order breaks ties
    )
    items: list[Item] = []
    for entity_id, entry in ordered:
        domain = entity_id.split(".", 1)[0]
        if domain in EXCLUDED_DOMAINS or not should_expose(entity_id, storage):
            continue
        if entry is None:
            display = [names.state_name(entity_id, storage, None).strip()]
            area_names: list[str] = []
        else:
            display = names.entity_aliases(entry, storage)
            area_names = names.entity_area_names(entry, storage)
        if entity_id in skipped:
            continue
        info: dict[str, str] = {"names": ", ".join(display), "domain": domain}
        if area_names:
            info["areas"] = ", ".join(area_names)
        items.append(Item(entity_id, domain, info["names"], info.get("areas"), dump_yaml([info])))
    return items, warnings


def assemble(profile: Profile, items: list[Item], instructions: str | None) -> tuple[str, str]:
    """Return ``(static_yaml, system_prompt)`` for ``items``."""
    static_yaml = "".join(item.fragment for item in items)
    first = profile.default_instructions if instructions is None else instructions
    if not items:
        return "", "\n".join([first, profile.no_entities_prompt])
    parts = [profile.dynamic_prompt, STATIC_HEADER, static_yaml]
    if profile.legacy_layout:
        api_parts = [profile.control_prompt, *parts, AREA_PROMPT, NO_TIMER_PROMPT]
    else:
        api_parts = [*parts, "\n".join([profile.control_prompt, AREA_PROMPT, NO_TIMER_PROMPT])]
    return static_yaml, "\n".join([first, "\n".join(api_parts)])


def reconstruct(
    storage: Storage,
    profile: Profile,
    instructions: str | None = None,
    exclude: Collection[str] = (),
) -> Reconstruction:
    """Rebuild the static context and the system prompt.

    ``instructions`` replaces the default instruction text (your own conversation
    agent prompt). ``exclude`` drops entities, which is how a plan's effect is measured.
    """
    items, warnings = collect_items(storage, exclude)
    static_yaml, system_prompt = assemble(profile, items, instructions)
    return Reconstruction(profile, items, static_yaml, system_prompt, warnings)
