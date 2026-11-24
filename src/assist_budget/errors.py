"""Errors that carry a message key (translated at print time) and an exit code."""

from __future__ import annotations

from typing import Any

from . import EXIT_INPUT


class AssistBudgetError(Exception):
    """An error the CLI turns into a friendly message and a non-zero exit code.

    ``key`` is a key of the message table in ``locales/*.json`` and ``params``
    fill its placeholders. ``str(error)`` is the English text, so the error is
    readable when the package is used as a library.
    """

    def __init__(self, key: str, exit_code: int = EXIT_INPUT, **params: Any) -> None:
        self.key = key
        self.exit_code = exit_code
        self.params = params
        from .i18n import translate  # local import: i18n imports nothing from here

        super().__init__(translate("en", key, **params))
