"""Sealed armor prompt slots and deterministic host-copy scrubbing.

Layout mirrors the upstream dsh-purge table (`lib/table-key.js` + `lib/table-read.js`):
a randomly salted key is derived by hashing a fixed mix string together with the salt,
the payload is deflated and encrypted, and only the packed slot plus its mask/tag ride
the source tree.  The upstream project uses AES-256-GCM from Node's crypto; this port
uses an HMAC-SHA256 keystream plus an HMAC tag so the plugin keeps zero third-party
runtime dependencies while keeping the same property: the armor text is not readable
in the repository or in the installed package without running the code.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import zlib
from dataclasses import dataclass

MIX = (
    "hermes.armor.v1",
    "hermes-purge",
    "surface:cli|gateway|tui|desktop",
    "ov.table.1",
)
TAG_BYTES = 16


def mix_key(mask: str) -> bytes:
    """Derive the slot key from a fixed mix string plus the per-slot random mask."""
    joined = "\x1e".join(MIX) + "\x1e" + str(mask or "")
    return hashlib.sha256(joined.encode("utf-8")).digest()


def _keystream(key: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, _keystream(key, len(data))))


def seal(text: str) -> dict:
    """Seal *text*; returns the slot payload a source file can carry."""
    mask = base64.b64encode(os.urandom(16)).decode("ascii")
    key = mix_key(mask)
    body = _xor(zlib.compress(str(text).encode("utf-8"), 9), key)
    tag = hmac.new(key, body, hashlib.sha256).digest()[:TAG_BYTES]
    return {"slot": base64.b64encode(body).decode("ascii"),
            "mask": mask, "tag": base64.b64encode(tag).decode("ascii")}


def unseal(slot: str, mask: str, tag: str) -> str:
    """Open a sealed slot; any corruption, truncation or wrong mask yields ``""``."""
    try:
        key = mix_key(mask)
        body = base64.b64decode(slot)
        expected = hmac.new(key, body, hashlib.sha256).digest()[:TAG_BYTES]
        if not hmac.compare_digest(expected, base64.b64decode(tag)):
            return ""
        return zlib.decompress(_xor(body, key)).decode("utf-8")
    except Exception:
        return ""


@dataclass(frozen=True)
class PromptSet:
    name: str
    label: str
    note: str


PLAIN_NOTE = ("Neutral engineering instructions; no identity or refusal handling.")

# Model families that need the short variant: long Chinese instruction blocks crowd
# out the actual task on small-context or heavily RLHF'd small models.
SHORT_MODEL_HINTS = (
    "flash", "turbo", "mini", "lite", "small", "1.5b", "3b", "4b",
)
MODEL_HINTS: tuple[tuple[str, str], ...] = (
    ("gpt", "armor"),
    ("claude", "armor"),
    ("gemini", "armor"),
    ("deepseek", "armor"),
    ("kimi", "armor"),
    ("grok", "armor"),
    ("glm", "armor"),
    ("qwen", "armor"),
)
DEFAULT_SET = "armor"


def _blob() -> dict:
    """Load the generated sealed table (imported lazily so a broken blob never blocks import)."""
    from . import armor_blob
    return armor_blob.load()


def available() -> dict:
    """``{set_name: text}`` for every set carried by the sealed table."""
    try:
        raw = unseal(**_blob())
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


SET_META: tuple[tuple[str, str, str], ...] = (
    ("armor", "破甲（默认）", "Identity, refusal handling and direct-execution rules."),
    ("armor-lite", "破甲·精简", "Short variant for small-context or heavily gated models."),
    ("plain", "工程版", PLAIN_NOTE),
)


def prompt_sets() -> list[PromptSet]:
    """Sealed prompt sets in stable order, with labels for the panel."""
    sets = available()
    known = [name for name, _, _ in SET_META]
    out = [PromptSet(name, label, note) for name, label, note in SET_META if name in sets]
    out += [PromptSet(name, name, "Sealed set") for name in sorted(sets) if name not in known]
    return out


def pick_for_model(model: str = "", requested: str = None) -> str:
    """Resolve the prompt set for *model*; an explicit *requested* name always wins."""
    sets = available()
    if requested:
        if requested not in sets:
            raise ValueError(f"Unknown prompt set: {requested}")
        return requested
    lowered = str(model or "").lower()
    if any(hint in lowered for hint in SHORT_MODEL_HINTS) and "armor-lite" in sets:
        return "armor-lite"
    for hint, name in MODEL_HINTS:
        if hint in lowered and name in sets:
            return name
    if DEFAULT_SET in sets:
        return DEFAULT_SET
    return sorted(sets)[0] if sets else ""


def prompt_text(name: str = None) -> str:
    """Sealed prompt text for *name* (default set when omitted); ``""`` when unavailable."""
    sets = available()
    if not sets:
        return ""
    if name is None:
        name = DEFAULT_SET if DEFAULT_SET in sets else sorted(sets)[0]
    return sets.get(name, "")
