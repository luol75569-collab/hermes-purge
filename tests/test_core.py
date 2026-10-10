import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hermes_purge.core import Manager, PurgeError, digest, load_yaml, get_value, PROMPT_KEY


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.manager = Manager(self.home)
        self.original = b'# retain this comment\nmodel: "local/example"\napprovals:\n  mode: manual # operator choice\nprivate: "DO_NOT_EXPOSE"\n'
        self.manager.config.write_bytes(self.original)

    def test_plan_is_read_only(self):
        plan = self.manager.plan()
        self.assertTrue(plan.changes)
        self.assertEqual(self.manager.config.read_bytes(), self.original)
        self.assertFalse(self.manager.state.exists())
        self.assertNotIn("DO_NOT_EXPOSE", json.dumps(plan.public()))

    def test_apply_preserves_comments_and_other_values(self):
        result = self.manager.apply(preset='developer')
        data = self.manager.config.read_bytes()
        self.assertIn(b'# retain this comment', data)
        self.assertIn(b'"local/example"', data)
        self.assertIn(b'# operator choice', data)
        _, cfg = load_yaml(data)
        self.assertEqual(cfg['approvals']['mode'], 'manual')
        self.assertTrue(get_value(cfg, PROMPT_KEY))
        self.assertEqual(result['status'], 'applied')

    def test_apply_is_idempotent(self):
        self.manager.apply()
        data = self.manager.config.read_bytes()
        self.assertEqual(self.manager.apply()['status'], 'unchanged')
        self.assertEqual(data, self.manager.config.read_bytes())
        self.assertEqual(self.manager.status()['active_backups'], 1)

    def test_revert_exact_bytes(self):
        self.manager.apply()
        self.assertEqual(self.manager.revert()['status'], 'reverted')
        self.assertEqual(self.manager.config.read_bytes(), self.original)
        self.assertEqual(self.manager.revert()['status'], 'unchanged')

    def test_multiple_reverts_are_lifo(self):
        self.manager.apply(prompt='first')
        first = self.manager.config.read_bytes()
        self.manager.apply(prompt='second')
        self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), first)
        self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), self.original)

    def test_absent_config_restored_as_absent(self):
        self.manager.config.unlink()
        self.manager.apply(expected_sha256='')
        self.manager.revert()
        self.assertFalse(self.manager.config.exists())

    def test_preview_hash_rejects_drift(self):
        sha = self.manager.plan().public()['before_sha256']
        modified = self.original + b'new: value\n'
        self.manager.config.write_bytes(modified)
        with self.assertRaises(PurgeError):
            self.manager.apply(expected_sha256=sha)
        self.assertEqual(self.manager.config.read_bytes(), modified)

    def test_revert_preserves_later_user_edits(self):
        self.manager.apply()
        modified = self.manager.config.read_bytes() + b'user_change: yes\n'
        self.manager.config.write_bytes(modified)
        with self.assertRaises(PurgeError):
            self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), modified)
        self.assertTrue(self.manager.status()['drift'])

    def test_corrupt_backup_does_not_overwrite(self):
        tx = self.manager.apply()['backup_id']
        current = self.manager.config.read_bytes()
        (self.manager.state / 'backups' / tx / 'config.yaml').write_bytes(b'bad')
        with self.assertRaises(PurgeError):
            self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), current)

    def test_invalid_yaml_fails_closed(self):
        for data in (b'root: [\n', b'- list\n', b'agent: text\n', b'agent:\n  a: 1\n  a: 2\n'):
            with self.subTest(data=data):
                self.manager.config.write_bytes(data)
                with self.assertRaises(PurgeError):
                    self.manager.apply(preset='developer')
                self.assertEqual(self.manager.config.read_bytes(), data)

    def test_input_bounds(self):
        for opts in ({'prompt': ''}, {'prompt': 'x' * 4001}, {'max_iterations': 0},
                     {'max_iterations': True}, {'approval_mode': 'auto'}, {'preset': 'unknown'}):
            with self.subTest(opts=opts), self.assertRaises(PurgeError):
                self.manager.plan(**opts)

    def test_explicit_settings_and_unicode(self):
        self.manager.apply(prompt='精确执行，保留证据。', approval_mode='off', max_iterations=300)
        _, cfg = load_yaml(self.manager.config.read_bytes())
        self.assertEqual(get_value(cfg, PROMPT_KEY), '精确执行，保留证据。')
        self.assertEqual(get_value(cfg, 'approvals.mode'), 'off')
        self.assertEqual(get_value(cfg, 'agent.max_turns'), 300)

    def test_lock_rejects_concurrent_writer(self):
        with self.manager.lock(), self.assertRaises(PurgeError):
            Manager(self.home).apply()

    def test_symlink_config_is_preserved(self):
        target = self.home / 'other.yaml'
        target.write_bytes(self.original)
        self.manager.config.unlink()
        self.manager.config.symlink_to(target)
        with self.assertRaises(PurgeError):
            self.manager.apply()
        self.assertEqual(target.read_bytes(), self.original)

    def test_profile_isolation(self):
        second = self.home / 'profiles' / 'second'
        second.mkdir(parents=True)
        Manager(second).apply(prompt='second profile')
        self.assertEqual(self.manager.config.read_bytes(), self.original)
        self.assertEqual(Manager(second).status()['prompt'], 'second profile')

    def test_private_backup_permissions(self):
        tx = self.manager.apply()['backup_id']
        path = self.manager.state / 'backups' / tx / 'config.yaml'
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_prepared_transaction_recovery(self):
        tx = self.manager.apply()['backup_id']
        path = self.manager.state / 'backups' / tx / 'receipt.json'
        record = json.loads(path.read_text())
        record['status'] = 'prepared'
        path.write_text(json.dumps(record))
        self.assertTrue(self.manager.status()['pending'])
        with self.assertRaises(PurgeError):
            self.manager.apply(prompt='new')
        self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), self.original)

    def test_write_failure_preserves_original_and_recovers(self):
        from hermes_purge import core
        original_writer = core.atomic_write
        def fail_config(path, data):
            if path == self.manager.config:
                raise OSError('injected write failure')
            original_writer(path, data)
        with patch.object(core, 'atomic_write', fail_config), self.assertRaises(OSError):
            self.manager.apply()
        self.assertEqual(self.manager.config.read_bytes(), self.original)
        self.assertTrue(self.manager.status()['pending'])
        self.manager.revert()
        self.assertEqual(self.manager.config.read_bytes(), self.original)

    def test_existing_prompt_is_not_reset_by_mode_change(self):
        self.manager.apply(preset='developer', prompt='custom prompt')
        self.manager.apply(preset='developer', approval_mode='smart')
        self.assertEqual(self.manager.status()['prompt'], 'custom prompt')
        self.assertEqual(self.manager.apply(preset='developer')['status'], 'unchanged')

    def test_yaml_aliases_do_not_mutate_unmanaged_tree(self):
        self.manager.config.write_bytes(b'defaults: &defaults\n  execution_guidance: false\nagent: *defaults\n')
        self.manager.apply(preset='developer')
        _, cfg = load_yaml(self.manager.config.read_bytes())
        self.assertFalse(cfg['defaults']['execution_guidance'])
        self.assertTrue(cfg['agent']['execution_guidance'])

    def test_status_excludes_unmanaged_secrets(self):
        self.assertNotIn('DO_NOT_EXPOSE', json.dumps(self.manager.status()))
        self.assertFalse(self.manager.status()['runtime_verified'])


if __name__ == '__main__':
    unittest.main()
