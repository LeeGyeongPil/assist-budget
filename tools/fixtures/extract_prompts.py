"""Extract the prompt strings assist-budget needs from Home Assistant sources.

Usage: python extract_prompts.py <old_helpers_llm.py> <new_ha_llm.py> <new_intent_llm.py> <new_helpers_llm.py> <out.json>

Needs only the standard library: it reads the module source and evaluates the
plain string constants with `ast.literal_eval` (nothing is imported or run).
"""

import ast
import json
import pathlib
import sys

WANTED = ("DEFAULT_INSTRUCTIONS_PROMPT", "NO_ENTITIES_PROMPT", "DEVICE_CONTROL_TOOL_USAGE_PROMPT",
          "DYNAMIC_CONTEXT_PROMPT", "DATE_TIME_PROMPT")


def constants(path: str) -> dict[str, str]:
    found = {}
    for node in ast.parse(pathlib.Path(path).read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in WANTED:
            found[node.targets[0].id] = ast.literal_eval(node.value)
    return found


old = constants(sys.argv[1])
new = {}
for p in sys.argv[2:5]:
    new.update(constants(p))
out = {"2025.5-2026.7": old, "2026.8+": new}
pathlib.Path(sys.argv[5]).write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))
for k, v in out.items():
    print(k, sorted(v))
