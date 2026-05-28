"""Text and collection utility functions."""

from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any


def loads_json(content: str, label: str = "response") -> dict[str, Any]:
    """Parse JSON from *content*, falling back to extracting the first ``{…}`` block.

    Raises :class:`ValueError` when no valid JSON object can be extracted.
    """
    try:
        value = json.loads(content)
    except JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(f"LongCat {label} did not include JSON")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError(f"LongCat {label} must be a JSON object")
    return value


def unique_strings(values: list[str], *, normalize_whitespace: bool = True) -> list[str]:
    """Deduplicate a list of strings, preserving first-occurrence order.

    When *normalize_whitespace* is ``True`` (the default), each value is
    collapsed to single spaces and stripped before comparison.
    """
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split()) if normalize_whitespace else value
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result
