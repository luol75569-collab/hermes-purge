"""Native registration uses documented ctx surfaces only.

Two layers, both through Hermes' own plugin contract:

1. the sealed armor prompt set is injected as a bounded system-prompt section on new
   sessions (``register_system_prompt_section``), replacing the free-text prompt only when
   the operator has not written one;
2. :mod:`hermes_purge.armor_runtime` scrubs host copy from outbound requests and delivers
   refusal continuations through the ``llm_request`` middleware, registers the refusal
   observers, and publishes the model-facing ``purge_*`` tools.
"""
import json

from . import armor
from .armor_runtime import TOOLSET, ArmorRuntime
from .cli import handle_namespace, setup_parser
from .core import Manager, PurgeError

SETTINGS_KEYS = ("enabled", "scrub", "refusal_recover", "max_recoveries_per_turn",
                 "prompt_set", "recover_text")
PROMPT_SECTION = "hermes-purge.rules"
MAX_SECTION_CHARS = 4000


def register(ctx):
    if not callable(getattr(ctx, "register_system_prompt_section", None)):
        raise RuntimeError("This Hermes build needs register_system_prompt_section support")

    def setting(key, default=None):
        return ctx.get_config(key, default)

    def read_settings():
        out = {}
        for key in SETTINGS_KEYS:
            value = setting(key)
            if value is not None:
                out[key] = value
        return out

    runtime = ArmorRuntime(read_settings)

    def render(_session_info):
        prompt = setting("prompt", "")
        if isinstance(prompt, str) and prompt.strip():
            if len(prompt) > MAX_SECTION_CHARS:
                raise PurgeError(
                    f"Configured prompt must be a string with at most {MAX_SECTION_CHARS} characters")
            return prompt
        name = setting("prompt_set")
        text = armor.prompt_text(name if isinstance(name, str) and name else None)
        if not text:
            raise PurgeError(
                "Sealed armor prompt unavailable; rebuild with scripts/embed_armor_prompt.py")
        return text[:MAX_SECTION_CHARS]

    def slash(raw_args):
        action = (raw_args or "").strip() or "status"
        try:
            if action == "status":
                return json.dumps({"config": Manager().status(), "armor": runtime.status()},
                                  ensure_ascii=False, indent=2)
            if action == "armor":
                return json.dumps(runtime.status(), ensure_ascii=False, indent=2)
            if action == "presets":
                names = ", ".join(sorted(_preset_names()))
                sets = ", ".join(item.name for item in armor.prompt_sets()) or "(none)"
                return (f"presets: {names}; prompt sets: {sets}; "
                        "apply with hermes purge plan/apply or the local panel")
            return ("Use /purge status, /purge armor, or /purge presets. "
                    "Apply/revert run through hermes purge or the local panel.")
        except (PurgeError, OSError, ValueError) as exc:
            return str(exc)

    ctx.register_system_prompt_section(PROMPT_SECTION, render, max_chars=MAX_SECTION_CHARS)
    ctx.register_command("purge", slash, description="Inspect Hermes Purge configuration",
                         args_hint="[status|armor|presets]")
    ctx.register_cli_command("purge", "Manage Hermes Purge", setup_parser, handle_namespace)

    if callable(getattr(ctx, "register_middleware", None)):
        ctx.register_middleware("llm_request", runtime.llm_request)
    for hook_name, callback in (("transform_llm_output", runtime.observe_output),
                                ("post_llm_call", runtime.observe_post)):
        if callable(getattr(ctx, "register_hook", None)):
            ctx.register_hook(hook_name, callback)
    if callable(getattr(ctx, "register_tool", None)):
        for spec in runtime.tool_specs():
            name = spec["name"]
            ctx.register_tool(
                name=name, toolset=TOOLSET, schema=spec["schema"],
                handler=lambda args, _name=name, **kwargs: runtime.call_tool(_name, args),
                description=spec["schema"]["description"],
            )
    return runtime


def _preset_names():
    from .core import PRESETS
    return PRESETS
