"""Single-file configuration transactions with exact backups and drift checks."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from ruamel.yaml import YAML

from . import armor

PROMPT_KEY = "plugins.entries.hermes-purge.settings.prompt"
PROMPT_SET_KEY = "plugins.entries.hermes-purge.settings.prompt_set"
DEFAULT_PROMPT = (
    "Use concise Simplified Chinese unless the user requests another language. "
    "Keep code identifiers and logs in their original language. "
    "Inspect relevant files before making changes. Preserve unrelated user edits. "
    "Use tools to verify facts, implement requested work, and test the result. "
    "Distinguish observed behavior from assumptions. Report actual verification "
    "and remaining blockers without inventing success."
)
ARMOR_PRESET = "armor"
PRESETS = {
    # Sealed armor prompt (never shipped as plain text) plus explicit approval bypass.
    # The prompt body is resolved at apply time from the encrypted table.
    ARMOR_PRESET: {"approvals.mode": "off"},
    "developer": {PROMPT_KEY: DEFAULT_PROMPT, "agent.execution_guidance": True,
                  "agent.tool_use_enforcement": True, "agent.task_completion_guidance": True,
                  "agent.parallel_tool_call_guidance": True},
    "minimal": {PROMPT_KEY: DEFAULT_PROMPT, "agent.execution_guidance": False},
    "prompt-only": {PROMPT_KEY: DEFAULT_PROMPT},
}
DEFAULT_PRESET = ARMOR_PRESET


class PurgeError(Exception):
    pass


def digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def platform_default_home() -> Path:
    """Fallback home when Hermes is not importable, mirroring Hermes' own platform default.

    ``hermes_constants._get_platform_default_hermes_home`` resolves Windows to
    ``%LOCALAPPDATA%\\hermes`` and POSIX to ``~/.hermes``; a plugin run outside the Hermes
    interpreter (``hermes-purge`` standalone, a panel launched by hand) must not pick a
    different directory than the host it will configure.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "hermes"
    return Path.home() / ".hermes"


def resolve_home(explicit=None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        configured = os.environ.get("HERMES_HOME", "").strip()
        return (Path(configured) if configured else platform_default_home()).expanduser().resolve()
    return Path(get_hermes_home()).resolve()


def read_optional(path: Path) -> bytes | None:
    if path.is_symlink():
        raise PurgeError(f"Symlink target requires a regular file: {path}")
    return path.read_bytes() if path.exists() else None


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".purge-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_yaml(data: bytes | None):
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    try:
        cfg = yaml.load(data.decode("utf-8")) if data is not None else {}
    except Exception as exc:
        raise PurgeError(f"Invalid config.yaml: {exc}") from exc
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, Mapping):
        raise PurgeError("config.yaml root must be a mapping")
    return yaml, cfg


def get_value(cfg, key):
    node = cfg
    for part in key.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def set_value(cfg, key, value):
    node = cfg
    parts = key.split(".")
    for part in parts[:-1]:
        if part not in node:
            node[part] = {}
        if not isinstance(node[part], Mapping):
            raise PurgeError(f"Expected mapping at {part} in {key}")
        # Detach YAML aliases so managed writes cannot mutate unrelated trees.
        child = copy.deepcopy(node[part])
        if hasattr(child, "yaml_set_anchor"):
            child.yaml_set_anchor(None)
        node[part] = child
        node = child
    node[parts[-1]] = value


MAX_PROMPT_CHARS = 4000


def resolve_armor_prompt(prompt_set=None, model=""):
    """``(set_name, text)`` from the sealed table; raises when the table is unusable."""
    try:
        name = armor.pick_for_model(model, prompt_set or None)
    except ValueError as exc:
        raise PurgeError(str(exc)) from exc
    text = armor.prompt_text(name)
    if not text:
        raise PurgeError("Sealed armor prompt unavailable; rebuild with scripts/embed_armor_prompt.py")
    return name, text


def build_updates(preset=DEFAULT_PRESET, prompt=None, prompt_set=None,
                  approval_mode=None, max_iterations=None):
    if preset not in PRESETS:
        raise PurgeError(f"Unknown preset: {preset}")
    updates = dict(PRESETS[preset])
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
            raise PurgeError(f"Prompt must contain 1-{MAX_PROMPT_CHARS} characters")
        updates[PROMPT_KEY] = prompt
        updates.pop(PROMPT_SET_KEY, None)
    elif preset == ARMOR_PRESET or prompt_set:
        name, text = resolve_armor_prompt(prompt_set)
        updates[PROMPT_KEY] = text
        updates[PROMPT_SET_KEY] = name
    if approval_mode is not None:
        if approval_mode not in {"manual", "smart", "off"}:
            raise PurgeError("approval_mode must be manual, smart, or off")
        updates["approvals.mode"] = approval_mode
    if max_iterations is not None:
        if type(max_iterations) is not int or not 1 <= max_iterations <= 10000:
            raise PurgeError("max_iterations must be an integer between 1 and 10000")
        updates["agent.max_turns"] = max_iterations
    return updates


@dataclass
class Plan:
    before: bytes | None
    after: bytes
    changes: list[dict]

    def public(self):
        return {"before_sha256": digest(self.before), "after_sha256": digest(self.after),
                "changes": self.changes, "restart_required": bool(self.changes)}


class Manager:
    def __init__(self, home=None):
        self.home = resolve_home(home)
        self.config = self.home / "config.yaml"
        self.state = self.home / "purge"

    @contextmanager
    def lock(self):
        if not self.home.is_dir():
            raise PurgeError("Hermes home is missing; run hermes setup or choose --home")
        if self.state.is_symlink():
            raise PurgeError("purge state directory must not be a symlink")
        self.state.mkdir(mode=0o700, exist_ok=True)
        os.chmod(self.state, 0o700)
        path = self.state / "lock"
        if path.is_symlink():
            raise PurgeError("purge lock must not be a symlink")
        with path.open("a+b") as stream:
            os.chmod(path, 0o600)
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise PurgeError("Another purge transaction is running") from exc
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise PurgeError("Another purge transaction is running") from exc
            try:
                yield
            finally:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def plan(self, **options):
        before = read_optional(self.config)
        yaml, cfg = load_yaml(before)
        changes = []
        updates = build_updates(**options)
        existing_prompt = get_value(cfg, PROMPT_KEY)
        # A prompt the operator already owns wins over the preset's default text, unless this
        # call names a prompt or a sealed set explicitly (that is a deliberate switch).
        keeps_existing = options.get("prompt") is None and not options.get("prompt_set")
        if keeps_existing and isinstance(existing_prompt, str) and existing_prompt.strip():
            if len(existing_prompt) > MAX_PROMPT_CHARS:
                raise PurgeError(
                    f"Existing prompt exceeds {MAX_PROMPT_CHARS} characters; supply a shorter prompt")
            updates[PROMPT_KEY] = existing_prompt
            updates.pop(PROMPT_SET_KEY, None)
        for key, value in updates.items():
            old = get_value(cfg, key)
            # ruamel scalar subclasses must not cause non-idempotent rewrites.
            equal = old == value and not (isinstance(value, bool) and not isinstance(old, bool))
            if not equal:
                visible = old if isinstance(old, (str, int, bool, float, type(None))) else "<complex>"
                changes.append({"key": key, "before": visible, "after": value})
                set_value(cfg, key, value)
        if not changes:
            return Plan(before, before or b"", [])
        out = io.StringIO()
        yaml.dump(cfg, out)
        return Plan(before, out.getvalue().encode("utf-8"), changes)

    def _records(self):
        records = []
        root = self.state / "backups"
        if self.state.is_symlink() or root.is_symlink():
            raise PurgeError("Backup directories must not be symlinks")
        for path in sorted(root.glob("*/receipt.json")):
            if path.is_symlink() or path.parent.is_symlink():
                raise PurgeError("Backup records must be regular files")
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("status") not in {"prepared", "applied", "aborted", "reverted"}:
                raise PurgeError(f"Invalid backup record: {path}")
            if record.get("id") != path.parent.name or not all(k in record for k in ("before_sha256", "after_sha256")):
                raise PurgeError(f"Incomplete backup record: {path}")
            if record.get("schema") != 1 or record.get("home") != str(self.home):
                raise PurgeError(f"Backup record scope mismatch: {path}")
            records.append((path, record))
        return records

    def apply(self, expected_sha256=None, **options):
        with self.lock():
            if any(r["status"] == "prepared" for _, r in self._records()):
                raise PurgeError("Pending transaction found; run revert before apply")
            plan = self.plan(**options)
            # Empty string is the preview token for a config that did not exist.
            if expected_sha256 is not None and (digest(plan.before) or "") != expected_sha256:
                raise PurgeError("Config changed after preview; preview again")
            if not plan.changes:
                return {"status": "unchanged", **plan.public()}
            tx = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
            directory = self.state / "backups" / tx
            directory.mkdir(parents=True, mode=0o700)
            os.chmod(directory.parent, 0o700)
            if plan.before is not None:
                atomic_write(directory / "config.yaml", plan.before)
            record = {"schema": 1, "id": tx, "home": str(self.home), "status": "prepared",
                      "before_sha256": digest(plan.before), "after_sha256": digest(plan.after),
                      "keys": [c["key"] for c in plan.changes]}
            receipt = directory / "receipt.json"
            atomic_write(receipt, json.dumps(record, indent=2).encode())
            if read_optional(self.config) != plan.before:
                record["status"] = "aborted"
                atomic_write(receipt, json.dumps(record, indent=2).encode())
                raise PurgeError("Config changed during apply; nothing written")
            atomic_write(self.config, plan.after)
            record["status"] = "applied"
            atomic_write(receipt, json.dumps(record, indent=2).encode())
            return {"status": "applied", "backup_id": tx, **plan.public()}

    def revert(self):
        with self.lock():
            active = [(p, r) for p, r in self._records() if r["status"] in {"applied", "prepared"}]
            if not active:
                return {"status": "unchanged"}
            path, record = active[-1]
            current = read_optional(self.config)
            current_hash = digest(current)
            if current_hash not in {record["after_sha256"], record["before_sha256"]}:
                raise PurgeError("Config drift detected; user edits preserved. Compare the backup manually")
            original = read_optional(path.parent / "config.yaml")
            if digest(original) != record["before_sha256"]:
                raise PurgeError("Backup integrity check failed")
            if current_hash == record["after_sha256"]:
                if original is None:
                    self.config.unlink()
                else:
                    atomic_write(self.config, original)
            record["status"] = "reverted"
            atomic_write(path, json.dumps(record, indent=2).encode())
            return {"status": "reverted", "backup_id": record["id"], "restart_required": True}

    def status(self):
        data = read_optional(self.config)
        _, cfg = load_yaml(data)
        active = [r for _, r in self._records() if r["status"] in {"prepared", "applied"}]
        prompt = get_value(cfg, PROMPT_KEY) or ""
        entry = get_value(cfg, "plugins.entries.hermes-purge")
        disabled = get_value(cfg, "plugins.disabled") or []
        enabled = get_value(cfg, "plugins.enabled")
        installed = (self.home / "plugins" / "hermes-purge" / "plugin.yaml").is_file()
        return {"home": str(self.home), "config_sha256": digest(data), "plugin_installed": installed,
                "plugin_enabled_in_config": "hermes-purge" not in disabled
                    and (not isinstance(entry, Mapping) or entry.get("enabled") is not False)
                    and (enabled is None or "hermes-purge" in enabled),
                "prompt": prompt, "prompt_chars": len(prompt) if isinstance(prompt, str) else 0,
                "prompt_set": get_value(cfg, PROMPT_SET_KEY),
                "approval_mode": get_value(cfg, "approvals.mode"),
                "max_iterations": get_value(cfg, "agent.max_turns"),
                "active_backups": len(active), "latest_backup": active[-1]["id"] if active else None,
                "drift": bool(active and digest(data) != active[-1]["after_sha256"]),
                "pending": bool(active and active[-1]["status"] == "prepared"),
                "runtime_verified": False}
