"""Structural checks for the dashboard language packs.

Each locale lives in web/i18n/<locale>.json. Every pack must expose exactly the
same keys as the English source, keep the same {placeholders}, and cover every
data-i18n key referenced by the page.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "web" / "i18n"
INDEX = ROOT / "web" / "index.html"


def _flatten(obj, prefix=""):
    flat = {}
    for key, value in obj.items():
        if key.startswith("_"):
            continue
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", text))


def _packs() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in I18N_DIR.glob("*.json")}


def test_english_is_the_key_reference():
    packs = _packs()
    assert "en" in packs
    assert len(packs) >= 12
    assert packs["en"]["_locale"] == "en"


def test_every_pack_matches_english_keys():
    packs = _packs()
    reference = _flatten(packs["en"])
    assert reference
    for name, pack in packs.items():
        flat = _flatten(pack)
        assert set(flat) == set(reference), f"{name} key mismatch: {set(flat) ^ set(reference)}"
        for key, english in reference.items():
            assert _placeholders(flat[key]) == _placeholders(english), f"{name} placeholder mismatch in {key}"
            assert flat[key].strip(), f"{name} empty translation for {key}"


def test_pack_metadata_matches_filename():
    for name, pack in _packs().items():
        assert pack["_locale"] == name
        assert pack["_dir"] in {"ltr", "rtl"}
    assert _packs()["ar"]["_dir"] == "rtl"


def test_page_markup_keys_exist_in_english_pack():
    html = INDEX.read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-aria)?="([^"]+)"', html))
    missing = used - set(_flatten(_packs()["en"]))
    assert not missing, f"index.html references unknown translation keys: {missing}"
