"""Rule Engine Loader — loads and caches the label→profile_key YAML rules.

Usage:
    from app.services.rule_engine.loader import rule_match
    profile_key = rule_match("Date of Birth")  # → "dob"
    profile_key = rule_match("जन्म तिथि")       # → "dob"
    profile_key = rule_match("unknown label")   # → None
"""

import os
import re
import unicodedata
from functools import lru_cache
from typing import Dict, Optional

import yaml


_RULES_PATH = os.path.join(os.path.dirname(__file__), "rules.yaml")


@lru_cache(maxsize=1)
def _load_rules() -> Dict[str, str]:
    """Load rules.yaml and build a normalised_label → profile_key lookup dict.

    Cached after the first load — the YAML file is read once per process.
    """
    with open(_RULES_PATH, encoding="utf-8") as f:
        raw: Dict[str, list] = yaml.safe_load(f)

    lookup: Dict[str, str] = {}
    for profile_key, variants in (raw or {}).items():
        for variant in (variants or []):
            normalised = _normalise(str(variant))
            lookup[normalised] = profile_key

    return lookup


def rule_match(label: str) -> Optional[str]:
    """Return the canonical profile field key for a form field label, or None.

    Matching is:
    - Case-insensitive
    - Unicode-normalised (NFC)
    - Strips leading/trailing whitespace and punctuation
    """
    lookup = _load_rules()
    return lookup.get(_normalise(label))


def _normalise(text: str) -> str:
    """Normalise a label string for case/accent-insensitive dictionary lookup."""
    # Unicode NFC normalisation
    text = unicodedata.normalize("NFC", text)
    # Strip surrounding whitespace and common trailing punctuation (* : .)
    text = text.strip().rstrip("*:. ")
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)
    # Lowercase
    return text.lower()
