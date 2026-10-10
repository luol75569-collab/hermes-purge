"""Seal the armor prompt sets into hermes_purge/armor_blob.py.

Mirrors upstream dsh-purge `scripts/embed-default-prompt.mjs`: sources live as plain
markdown for editing and review, the shipped table carries only the sealed slot.
Run from the repository root:

    python3 scripts/embed_armor_prompt.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hermes_purge.armor import seal  # noqa: E402

SOURCE = ROOT / "hermes_purge" / "armor"
TARGET = ROOT / "hermes_purge" / "armor_blob.py"
CHUNK = 96

HEADER = '''"""Generated sealed armor table - do not edit by hand.

Rebuild with ``python3 scripts/embed_armor_prompt.py`` after changing any file under
``hermes_purge/armor/``.  The table holds the packed slot only: the prompt text is not
readable in the source tree, matching upstream dsh-purge's ``lib/asset-table.js``.
"""
from __future__ import annotations

'''


def main() -> int:
    sets = {}
    for path in sorted(SOURCE.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise SystemExit(f"empty source: {path}")
        sets[path.stem] = text
    if not sets:
        raise SystemExit(f"no prompt sources under {SOURCE}")
    packed = seal(json.dumps(sets, ensure_ascii=False, sort_keys=True))
    rows = [packed["slot"][i:i + CHUNK] for i in range(0, len(packed["slot"]), CHUNK)]
    body = [
        f"SLOT_ROWS = {json.dumps(rows, indent=2, ensure_ascii=False)}",
        "",
        'SLOT = "".join(SLOT_ROWS)',
        f"MASK = {json.dumps(packed['mask'])}",
        f"TAG = {json.dumps(packed['tag'])}",
        "",
        "",
        "def load() -> dict:",
        '    """Packed slot payload for :func:`hermes_purge.armor.unseal`."""',
        '    return {"slot": SLOT, "mask": MASK, "tag": TAG}',
        "",
    ]
    TARGET.write_text(HEADER + "\n".join(body), encoding="utf-8")
    total = sum(len(value) for value in sets.values())
    print(f"wrote {TARGET.relative_to(ROOT)} sets={sorted(sets)} chars={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
