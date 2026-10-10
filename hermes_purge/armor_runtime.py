"""Runtime armor: request scrubbing, refusal recovery, and the model-facing purge tools.

Registered through documented Hermes seams only:

* ``llm_request`` middleware (``hermes_cli/middleware.py``) rewrites the provider payload
  before hooks, approvals and execution see it - the seam upstream dsh-purge reaches by
  patching the host's prompt assembler on disk.
* ``transform_llm_output`` / ``post_llm_call`` observers (``VALID_HOOKS``) record refusals.
  Both return ``None``: the armor never rewrites the answer the user already saw.
* ``register_tool`` publishes the same three tools upstream ships
  (``purge_status`` / ``purge_apply`` / ``purge_revert``).

Recovery semantics: upstream resumes the turn immediately (``agent.followup``).  Hermes
has no plugin seam for that, so the continuation rides the next request as a user-role row
and is counted per turn.  The difference is deliberate and documented in the README.
"""
from __future__ import annotations

import json
import threading
import time

from . import armor, refusal, scrub
from .core import PRESETS, Manager, PurgeError

SETTINGS_TTL = 5.0

DEFAULTS = {
    "enabled": True,
    "scrub": True,
    "refusal_recover": True,
    "max_recoveries_per_turn": refusal.MAX_RECOVERIES_PER_TURN,
    "prompt_set": "",
    "recover_text": "",
}

TOOLSET = "hermes_purge"


class ArmorRuntime:
    """Stateful armor runtime; one instance per plugin load."""

    def __init__(self, settings_getter=None):
        self._get_settings = settings_getter or (lambda: {})
        self._lock = threading.Lock()
        self._tracker = refusal.RefusalTracker()
        self._settings_cache = None
        self._stats = {
            "requests": 0,
            "messages_scrubbed": 0,
            "rule_hits": {},
            "refusals_seen": 0,
            "recoveries": 0,
        }

    # -- settings ------------------------------------------------------------------
    def settings(self) -> dict:
        """Merged settings, re-read at most once per :data:`SETTINGS_TTL` seconds.

        ``get_config`` hits the config loader on every call and this runs once per provider
        request, so the cache keeps the hot path free of repeated YAML reads while still
        picking up an operator change within a few seconds.
        """
        now = time.monotonic()
        with self._lock:
            cached = self._settings_cache
            if cached and now - cached[0] < SETTINGS_TTL:
                return cached[1]
        raw = self._get_settings() or {}
        merged = dict(DEFAULTS)
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    merged[key] = raw[key]
        try:
            merged["max_recoveries_per_turn"] = max(
                0, min(5, int(merged["max_recoveries_per_turn"]))
            )
        except (TypeError, ValueError):
            merged["max_recoveries_per_turn"] = refusal.MAX_RECOVERIES_PER_TURN
        self._tracker.cap = merged["max_recoveries_per_turn"]
        with self._lock:
            self._settings_cache = (now, merged)
        return merged

    # -- counters ------------------------------------------------------------------
    def _bump(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[key] = self._stats.get(key, 0) + amount

    def _bump_rule(self, rule_id: str, amount: int) -> None:
        with self._lock:
            hits = self._stats["rule_hits"]
            hits[rule_id] = hits.get(rule_id, 0) + amount

    # -- llm_request middleware ----------------------------------------------------
    def llm_request(self, **_kwargs):
        """Scrub the outbound payload and deliver a pending refusal continuation."""
        settings = self.settings()
        if not settings["enabled"]:
            return None
        payload = _kwargs.get("request")
        if not isinstance(payload, dict):
            return None
        session_id = str(_kwargs.get("session_id") or "")
        turn_id = _kwargs.get("turn_id")
        self._bump("requests")
        self._tracker.note_turn(session_id, turn_id)

        changed = False
        messages = payload.get("messages")
        if settings["scrub"] and isinstance(messages, list):
            scrubbed, hits = scrub.scrub_request(payload)
            if hits:
                payload = scrubbed
                changed = True
                self._bump("messages_scrubbed", sum(hits.values()))
                for rule_id, count in hits.items():
                    self._bump_rule(rule_id, count)

        if settings["refusal_recover"] and isinstance(messages, list):
            text = refusal.last_assistant_text(messages)
            if (text and refusal.looks_like_refusal(text)
                    and not refusal.already_continued(messages)
                    and self._tracker.allow(session_id)):
                continuation = refusal.recovery_message(settings["recover_text"])
                payload = {**payload, "messages": [*payload.get("messages", []), continuation]}
                self._tracker.mark(session_id)
                self._bump("recoveries")
                changed = True

        return {"request": payload, "source": "hermes-purge"} if changed else None

    # -- refusal observers ---------------------------------------------------------
    def observe_output(self, response_text: str = "", session_id: str = "", **_kwargs):
        """``transform_llm_output``: record only; the visible answer is never rewritten."""
        if self.settings()["enabled"] and refusal.looks_like_refusal(response_text):
            self._bump("refusals_seen")
        return None

    def observe_post(self, assistant_response: str = "", **_kwargs):
        """``post_llm_call``: same bookkeeping for text that only reached this seam."""
        if self.settings()["enabled"] and refusal.looks_like_refusal(assistant_response):
            self._bump("refusals_seen")
        return None

    # -- status --------------------------------------------------------------------
    def status(self) -> dict:
        settings = self.settings()
        with self._lock:
            stats = json.loads(json.dumps(self._stats))
        return {
            "enabled": bool(settings["enabled"]),
            "scrub": bool(settings["scrub"]),
            "refusal_recover": bool(settings["refusal_recover"]),
            "max_recoveries_per_turn": settings["max_recoveries_per_turn"],
            "prompt_set": settings["prompt_set"] or "(auto by model)",
            "prompt_sets": [{"name": item.name, "label": item.label} for item in armor.prompt_sets()],
            "prompt_chars": {name: len(text) for name, text in armor.available().items()},
            "rules": scrub.rule_report(),
            "stats": stats,
            "sessions_tracked": len(self._tracker.snapshot()),
        }

    # -- model-facing tools --------------------------------------------------------
    def tool_specs(self) -> list[dict]:
        return [
            {
                "name": "purge_status",
                "schema": {
                    "name": "purge_status",
                    "description": "Report Hermes Purge configuration, armor prompt sets, scrub rules and counters.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "name": "purge_apply",
                "schema": {
                    "name": "purge_apply",
                    "description": (
                        "Apply a Hermes Purge preset (armor/developer/minimal/prompt-only) with a backup. "
                        "Requires the operator's Go; never call it to change policy on your own."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "preset": {"type": "string", "enum": sorted(PRESETS)},
                            "prompt_set": {"type": "string", "enum": [s.name for s in armor.prompt_sets()]},
                            "approval_mode": {"type": "string", "enum": ["manual", "smart", "off"]},
                            "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10000},
                            "expected_sha256": {"type": "string"},
                            "home": {"type": "string"},
                        },
                        "required": ["preset"],
                    },
                },
            },
            {
                "name": "purge_revert",
                "schema": {
                    "name": "purge_revert",
                    "description": "Restore the latest exact Hermes Purge backup when there is no drift.",
                    "parameters": {"type": "object",
                                   "properties": {"home": {"type": "string"}}},
                },
            },
        ]

    def call_tool(self, name: str, args: dict) -> str:
        args = dict(args or {})
        try:
            if name == "purge_status":
                manager = Manager(args.get("home"))
                return json.dumps({"config": manager.status(), "armor": self.status()},
                                  ensure_ascii=False, indent=2)
            if name == "purge_apply":
                manager = Manager(args.pop("home", None))
                return json.dumps(manager.apply(**args), ensure_ascii=False)
            if name == "purge_revert":
                manager = Manager(args.pop("home", None))
                return json.dumps(manager.revert(), ensure_ascii=False)
        except (PurgeError, OSError, ValueError, TypeError) as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
