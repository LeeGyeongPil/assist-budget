"""Token counters.

``approx`` needs nothing (one token per four characters, rounded up) and is the
default. ``tekken`` is Mistral's real tokenizer, shipped inside the optional
``mistral-common`` wheel, so it also works offline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .errors import AssistBudgetError

TOKENIZERS = ("approx", "tekken")
TEKKEN_FILE = "tekken_240911.json"


@dataclass(frozen=True)
class Tokenizer:
    """A named token counter."""

    name: str
    count: Callable[[str], int]


def _approx(text: str) -> int:
    return (len(text) + 3) // 4


def _load_tekken() -> Tokenizer:
    try:
        import mistral_common
        from mistral_common.tokens.tokenizers.tekken import Tekkenizer
    except ImportError as exc:
        raise AssistBudgetError("err_tekken_missing") from exc
    path = Path(mistral_common.__file__).parent / "data" / TEKKEN_FILE
    try:
        tekken = Tekkenizer.from_file(str(path))
    except (OSError, ValueError) as exc:
        raise AssistBudgetError("err_tekken_data", path=str(path), reason=str(exc)) from exc
    return Tokenizer("tekken", lambda text: len(tekken.encode(text, bos=False, eos=False)))


def get_tokenizer(name: str) -> Tokenizer:
    """Return the tokenizer called ``name`` (``approx`` or ``tekken``)."""
    if name == "approx":
        return Tokenizer("approx", _approx)
    if name == "tekken":
        return _load_tekken()
    raise AssistBudgetError("err_unknown_tokenizer", name=name, choices=", ".join(TOKENIZERS))
