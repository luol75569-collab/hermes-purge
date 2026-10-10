"""Platform behaviour: Windows home resolution and CJK-safe console output."""
import argparse
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hermes_purge import cli, core

try:  # the probe suite runs against a real Hermes checkout; unit tests normally cannot import it
    import hermes_constants  # noqa: F401
    HAS_HERMES = True
except ImportError:
    HAS_HERMES = False


class HomeResolutionTests(unittest.TestCase):
    def setUp(self):
        if HAS_HERMES:
            self.skipTest("hermes_constants importable: the fallback branch is unreachable here")

    def test_windows_default_uses_localappdata(self):
        with patch("sys.platform", "win32"), \
                patch.dict(os.environ, {"LOCALAPPDATA": "/fake-local"}, clear=True):
            self.assertEqual(core.resolve_home(), Path("/fake-local/hermes"))

    def test_windows_default_without_localappdata(self):
        with patch("sys.platform", "win32"), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(core.platform_default_home(),
                             Path.home() / "AppData" / "Local" / "hermes")

    def test_posix_default_is_dot_hermes(self):
        with patch("sys.platform", "darwin"), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(core.platform_default_home(), Path.home() / ".hermes")

    def test_hermes_home_env_wins_over_platform_default(self):
        with patch("sys.platform", "win32"), \
                patch.dict(os.environ, {"HERMES_HOME": "/fake-hermes-home"}, clear=True):
            self.assertEqual(core.resolve_home(), Path("/fake-hermes-home"))

    def test_explicit_home_wins_over_everything(self):
        with patch("sys.platform", "win32"), \
                patch.dict(os.environ, {"HERMES_HOME": "/fake-hermes-home"}, clear=True):
            target = Path(tempfile.mkdtemp())
            self.addCleanup(target.rmdir)
            self.assertEqual(core.resolve_home(target), target.resolve())


class ConsoleEncodingTests(unittest.TestCase):
    """A legacy Windows code page must not kill a command that already changed files."""

    def _run(self, action, **extra):
        raw = io.BytesIO()
        wrapper = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
        args = argparse.Namespace(action=action, **extra)
        with patch.object(sys, "stdout", wrapper), patch.object(sys, "stderr", wrapper):
            code = cli.handle_namespace(args)
            wrapper.flush()  # the interpreter flushes at exit; a test must do it explicitly
        return code, wrapper, raw

    def test_cjk_output_survives_ascii_console(self):
        home = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(home, ignore_errors=True))
        code, wrapper, raw = self._run("armor", home=home)
        self.assertEqual(code, 0)
        self.assertEqual(wrapper.encoding.lower(), "utf-8")
        self.assertIn("破甲", raw.getvalue().decode("utf-8"))

    def test_force_utf8_streams_tolerates_stream_without_reconfigure(self):
        class Plain:
            def write(self, _text):
                return len(_text)

        with patch.object(sys, "stdout", Plain()), patch.object(sys, "stderr", Plain()):
            cli.force_utf8_streams()  # must not raise

    def test_main_returns_zero_for_presets(self):
        raw = io.BytesIO()
        wrapper = io.TextIOWrapper(raw, encoding="ascii", errors="strict", newline="")
        with patch.object(sys, "stdout", wrapper), patch.object(sys, "stderr", wrapper):
            self.assertEqual(cli.main(["presets"]), 0)


if __name__ == "__main__":
    unittest.main()
