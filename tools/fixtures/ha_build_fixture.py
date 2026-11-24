"""Step 2 of 3: let a real Home Assistant core write the `.storage` files.

Run this with the development-only venv that has `homeassistant` installed
(see README.md in this folder). It feeds the spec from make_spec.py into HA's
own registry APIs, so the files on disk are exactly what HA writes.

Usage: python ha_build_fixture.py <spec_dir> <new_config_dir> house|defaults

  house     explicit exposure per entity, expose_new = false  (fixture A)
  defaults  no explicit exposure at all, expose_new = true    (fixture B,
            exposure is decided by HA's built-in default rules)
"""

import asyncio
import json
import pathlib
import sys
from types import MappingProxyType


async def main(spec_dir: str, config_dir: str, mode: str) -> None:
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.components.homeassistant.exposed_entities import (
        DATA_EXPOSED_ENTITIES,
        ExposedEntities,
        async_expose_entity,
    )
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    spec = json.loads((pathlib.Path(spec_dir) / "spec.json").read_text())
    pathlib.Path(config_dir, ".storage").mkdir(parents=True, exist_ok=True)
    hass = core.HomeAssistant(config_dir)
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)

    exposed = ExposedEntities(hass)
    await exposed.async_initialize()
    hass.data[DATA_EXPOSED_ENTITIES] = exposed
    exposed.async_set_expose_new_entities("conversation", mode == "defaults")

    entry = config_entries.ConfigEntry(
        data={}, discovery_keys=MappingProxyType({}), domain="acme", minor_version=1,
        options={}, source="user", subentries_data=None, title="Acme",
        unique_id="acme", version=1)
    hass.config_entries._entries[entry.entry_id] = entry  # same as the test helper does

    areg, dreg, ereg = ar.async_get(hass), dr.async_get(hass), er.async_get(hass)
    area_ids = {}
    for a in spec["areas"]:
        area_ids[a["id"]] = areg.async_create(a["name"], aliases=set(a["aliases"])).id
    dev_ids = {}
    for d in spec["devices"]:
        dev = dreg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={("acme", d["id"])},
            name=d["name"], manufacturer="Acme", model="Hub")
        if d["area_id"]:
            dreg.async_update_device(dev.id, area_id=area_ids[d["area_id"]])
        dev_ids[d["id"]] = dev.id

    states = {s["entity_id"]: s for s in spec["states"]}
    restore = []
    for e in spec["entities"]:
        domain, obj = e["entity_id"].split(".", 1)
        kw = {}
        if e["device_id"]:
            kw["device_id"] = dev_ids[e["device_id"]]
            kw["config_entry"] = entry
        new = ereg.async_get_or_create(
            domain, e["platform"], e["unique_id"], suggested_object_id=obj,
            original_name=e["original_name"], has_entity_name=e["has_entity_name"],
            entity_category=EntityCategory(e["entity_category"]) if e["entity_category"] else None,
            original_device_class=e["original_device_class"], **kw)
        extra = [a for a in e["aliases_v2"] if a]
        if extra:
            ereg.async_update_entity(new.entity_id, aliases=[er.COMPUTED_NAME, *extra])
        if mode == "house":
            async_expose_entity(hass, "conversation", new.entity_id, e["expose"])
        restore.append(states[e["entity_id"]])
    if mode == "house":
        for eid in spec["legacy_exposed"]:  # not in the registry: stored in homeassistant.exposed_entities
            async_expose_entity(hass, "conversation", eid, True)
    registry_ids = {e["entity_id"] for e in spec["entities"]}
    restore += [s for eid, s in states.items() if eid not in registry_ids]

    await hass.async_block_till_done()
    for store_owner in (areg, dreg, ereg, exposed):  # flush the delayed saves now
        await store_owner._store.async_save(store_owner._data_to_save())
    restore_doc = {
        "version": 1, "minor_version": 1, "key": "core.restore_state",
        "data": [{"state": {"entity_id": s["entity_id"], "state": s["state"],
                            "attributes": s["attributes"],
                            "last_changed": "2026-11-24T00:00:00+00:00"},
                  "extra_data": None, "last_seen": "2026-11-24T00:00:00+00:00"}
                 for s in restore]}
    pathlib.Path(config_dir, ".storage", "core.restore_state").write_text(
        json.dumps(restore_doc, indent=1, ensure_ascii=False))
    from homeassistant.const import __version__ as ha_version

    pathlib.Path(config_dir, ".HA_VERSION").write_text(ha_version)  # HA writes it without newline
    print("written:", sorted(p.name for p in pathlib.Path(config_dir, ".storage").iterdir()))


asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
