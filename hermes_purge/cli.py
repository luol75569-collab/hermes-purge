"""Standalone and Hermes-native CLI share the same parser and handlers."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from . import armor, scrub
from .core import DEFAULT_PRESET, Manager, PRESETS, PurgeError


def setup_parser(parser):
    parser.add_argument("--home", help="Explicit Hermes profile home")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("status", help="Inspect disk state (not a runtime claim)")
    commands.add_parser("presets", help="List built-in configuration presets")
    commands.add_parser("armor", help="Show the sealed armor prompt sets and scrub rules")
    commands.add_parser("revert", help="Restore the latest exact backup if there is no drift")
    commands.add_parser("install", help="Copy this native plugin into the selected home")
    sets = [item.name for item in armor.prompt_sets()]
    for action in ("plan", "apply"):
        command = commands.add_parser(action, help="Preview changes" if action == "plan" else "Apply with backup")
        command.add_argument("--preset", choices=PRESETS, default=DEFAULT_PRESET)
        if sets:
            command.add_argument("--prompt-set", choices=sets,
                                 help="Sealed armor prompt set to inject")
        command.add_argument("--prompt-file", type=Path)
        command.add_argument("--approval-mode", choices=("manual", "smart", "off"))
        command.add_argument("--max-iterations", type=int)
        if action == "apply":
            command.add_argument("--expected-sha256", help="SHA256 from plan; empty string if config was absent")
    serve = commands.add_parser("serve", help="Start a loopback-only local control panel")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="Open the panel in a browser")


def install(manager):
    source = Path(__file__).resolve().parent.parent
    target = manager.home / "plugins" / "hermes-purge"
    if not manager.home.is_dir():
        raise PurgeError("Hermes home is missing; run hermes setup first")
    if not (source / "plugin.yaml").is_file():
        raise PurgeError("Install from the source checkout, not the pip package")
    if target.resolve() == source:
        return {"status": "unchanged", "plugin_path": str(target)}
    with manager.lock():
        if target.exists() or target.is_symlink():
            raise PurgeError("Plugin target already exists; existing files preserved")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / ".hermes-purge-staging"
        if staging.exists():
            raise PurgeError("Install staging directory exists; inspect it before retrying")
        staging.mkdir(mode=0o700)
        try:
            for name in ("__init__.py", "plugin.yaml", "README.md", "LICENSE", "NOTICE.md", "pyproject.toml"):
                shutil.copy2(source / name, staging / name)
            shutil.copytree(source / "hermes_purge", staging / "hermes_purge",
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            if (source / "docs").is_dir():
                shutil.copytree(source / "docs", staging / "docs")
            staging.rename(target)
        except BaseException:
            shutil.rmtree(staging)
            raise
    return {"status": "installed", "plugin_path": str(target), "restart_required": True,
            "next": "hermes plugins enable hermes-purge"}


def execute(args):
    manager = Manager(args.home)
    if args.action == "presets":
        return PRESETS
    if args.action == "status":
        return manager.status()
    if args.action == "armor":
        return {"config": manager.status(),
                "prompt_sets": [{"name": item.name, "label": item.label,
                                 "chars": len(armor.prompt_text(item.name))}
                                for item in armor.prompt_sets()],
                "default_set": armor.DEFAULT_SET,
                "scrub_rules": scrub.rule_report()}
    if args.action == "revert":
        return manager.revert()
    if args.action == "install":
        return install(manager)
    if args.action == "serve":
        from .web import serve
        serve(manager, args.port, args.open)
        return {"status": "stopped"}
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else None
    options = dict(preset=args.preset, prompt=prompt, prompt_set=getattr(args, "prompt_set", None),
                   approval_mode=args.approval_mode, max_iterations=args.max_iterations)
    if args.action == "plan":
        return manager.plan(**options).public()
    return manager.apply(expected_sha256=args.expected_sha256, **options)


def handle_namespace(args):
    try:
        print(json.dumps(execute(args), indent=2, ensure_ascii=False))
        return 0
    except (PurgeError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hermes-purge")
    setup_parser(parser)
    return handle_namespace(parser.parse_args(argv))
