"""Step 3 of 3: golden files from the real Home Assistant.

Loads a fixture config folder into a headless HA core and records what HA
itself computes: the Assist static context, the full system prompt, entity
names, and (for the `defaults` fixture) which entities HA exposes by default.

Usage: python ha_truth.py <config_dir> <golden_dir>

The config folder is copied first, because HA writes defaults back to the
store while it decides exposure.
"""

import asyncio
import json
import pathlib
import shutil
import sys
import tempfile


async def main(config_dir: str, golden_dir: str) -> None:
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.components.homeassistant.exposed_entities import (
        DATA_EXPOSED_ENTITIES,
        ExposedEntities,
        async_should_expose,
    )
    from homeassistant.components.homeassistant.llm import (
        async_get_exposed_entities,
    )
    from homeassistant.components.homeassistant.llm import (
        async_get_tools as ha_tools,
    )
    from homeassistant.components.intent.llm import async_get_tools as intent_tools
    from homeassistant.const import __version__
    from homeassistant.helpers import entity_registry as er
    from homeassistant.helpers import intent
    from homeassistant.helpers.llm import (
        DEFAULT_INSTRUCTIONS_PROMPT,
        LLM_API_ASSIST,
        LLMContext,
    )

    work = pathlib.Path(tempfile.mkdtemp(prefix="ha-truth-"))
    shutil.copytree(config_dir, work / "config", dirs_exist_ok=True)
    hass = core.HomeAssistant(str(work / "config"))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await bootstrap.async_load_base_functionality(hass)

    restore = json.loads((work / "config/.storage/core.restore_state").read_text())
    for item in restore["data"]:
        st = item["state"]
        hass.states.async_set(st["entity_id"], st["state"], st["attributes"])
    exposed = ExposedEntities(hass)
    await exposed.async_initialize()
    hass.data[DATA_EXPOSED_ENTITIES] = exposed

    # Static context exactly as the homeassistant LLM platform builds it.
    entities = async_get_exposed_entities(hass, "conversation", include_state=False)
    ctx = LLMContext(platform="golden", context=None, language="en",
                     assistant="conversation", device_id=None)
    ha_result = ha_tools(hass, ctx, LLM_API_ASSIST)
    # The intent platform only contributes a prompt when intent handlers exist.
    from homeassistant.components import intent as intent_component

    intent.async_register(hass, intent_component.OnOffIntentHandler(
        intent.INTENT_TURN_ON, "homeassistant", "turn_on"))
    intent.async_register(hass, intent_component.OnOffIntentHandler(
        intent.INTENT_TURN_OFF, "homeassistant", "turn_off"))
    intent_result = intent_tools(hass, ctx, LLM_API_ASSIST)
    # components/llm merges platform prompts sorted by domain: homeassistant, intent.
    api_prompt = "\n".join(p for p in (ha_result.prompt, intent_result.prompt if intent_result else None) if p)
    # conversation/chat_log.py joins [instructions, api_prompt] with a newline
    # (no date prompt: the llm integration provides a GetDateTime tool in 2026.11).
    system_prompt = "\n".join([DEFAULT_INSTRUCTIONS_PROMPT, api_prompt])

    registry = er.async_get(hass)
    names = {}
    for entry in registry.entities.values():
        names[entry.entity_id] = er.async_get_entity_aliases(hass, entry)
    should_expose = {s.entity_id: async_should_expose(hass, "conversation", s.entity_id)
                     for s in hass.states.async_all()}

    from homeassistant.util import yaml as yaml_util

    out = pathlib.Path(golden_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "static_context.yaml").write_text(yaml_util.dump(list(entities.values())))
    (out / "system_prompt.txt").write_text(system_prompt)
    (out / "entities.json").write_text(json.dumps(entities, indent=1, ensure_ascii=False))
    (out / "names.json").write_text(json.dumps(names, indent=1, ensure_ascii=False, sort_keys=True))
    (out / "should_expose.json").write_text(
        json.dumps(should_expose, indent=1, ensure_ascii=False, sort_keys=True))
    (out / "HA_VERSION").write_text(__version__)
    print(f"HA {__version__}: exposed in static context = {len(entities)}, "
          f"system prompt chars = {len(system_prompt)}")
    await hass.async_stop(force=True)
    shutil.rmtree(work, ignore_errors=True)


asyncio.run(main(sys.argv[1], sys.argv[2]))
