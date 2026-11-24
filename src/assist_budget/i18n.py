"""Message tables and language selection (English / Korean).

All user-visible text lives in ``locales/en.json`` and ``locales/ko.json``.
Language order: ``--lang`` > ``ASSIST_BUDGET_LANG`` > ``LC_ALL`` /
``LC_MESSAGES`` / ``LANG`` (first one that is set). Anything that does not
start with ``ko`` means English.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from importlib import resources

LANGUAGES = ("en", "ko")
ENV_VAR = "ASSIST_BUDGET_LANG"
_POSIX_VARS = ("LC_ALL", "LC_MESSAGES", "LANG")


@cache
def messages(lang: str) -> dict[str, str]:
    """Return the message table for ``lang`` (``en`` or ``ko``)."""
    if lang not in LANGUAGES:
        raise ValueError(f"unsupported language {lang!r}; choose one of {', '.join(LANGUAGES)}")
    text = resources.files("assist_budget").joinpath("locales", f"{lang}.json").read_text(encoding="utf-8")
    return json.loads(text)


def _normalize(value: str | None) -> str | None:
    if not value:
        return None
    return "ko" if value.strip().lower().startswith("ko") else "en"


def resolve_lang(cli_value: str | None, env: Mapping[str, str]) -> str:
    """Decide the output language from the CLI option and the environment."""
    if cli_value:
        return _normalize(cli_value) or "en"
    if env.get(ENV_VAR):
        return _normalize(env[ENV_VAR]) or "en"
    for name in _POSIX_VARS:
        if env.get(name):  # POSIX: the first non-empty variable decides
            return _normalize(env[name]) or "en"
    return "en"


def translate(lang: str, key: str, **params: object) -> str:
    """Look up ``key`` and fill ``{placeholders}``; falls back to English."""
    table = messages(lang)
    text = table.get(key)
    if text is None:
        text = messages("en").get(key, key)
    return text.format(**params) if params else text
