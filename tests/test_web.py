import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from hermes_purge.core import Manager
from hermes_purge.web import make_server


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = Manager(self.tmp.name)
        self.manager.config.write_text('model: sample\n')
        self.server, self.token = make_server(self.manager)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.worker.join()
        self.server.server_close()

    def request(self, method='GET', path='/api/status', body=None, token=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        hdr = {'Content-Type': 'application/json'}
        if token:
            hdr['Authorization'] = 'Bearer ' + self.token
        hdr.update(headers or {})
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=hdr)
        response = connection.getresponse()
        data = response.read()
        status = response.status
        connection.close()
        return status, data

    def test_api_requires_token(self):
        self.assertEqual(self.request(token=False)[0], 401)
        self.assertEqual(self.request()[0], 200)

    def test_cross_origin_and_host_rejected(self):
        self.assertEqual(self.request(headers={'Origin': 'https://example.com'})[0], 403)
        self.assertEqual(self.request(headers={'Host': 'example.com'})[0], 403)

    def test_home_page_has_no_token(self):
        status, data = self.request(path='/', token=False)
        self.assertEqual(status, 200)
        self.assertNotIn(self.token.encode(), data)
        self.assertIn(b'HERMES / PURGE', data)

    def test_plan_apply_revert(self):
        before = self.manager.config.read_bytes()
        opts = {'preset': 'prompt-only', 'prompt': 'test rules'}
        status, data = self.request('POST', '/api/plan', opts)
        self.assertEqual(status, 200)
        plan = json.loads(data)
        status, data = self.request('POST', '/api/apply', {**opts, 'expected_sha256': plan['before_sha256']})
        self.assertEqual(status, 200, data)
        self.assertEqual(self.manager.status()['prompt'], 'test rules')
        self.assertEqual(self.request('POST', '/api/revert', {})[0], 200)
        self.assertEqual(self.manager.config.read_bytes(), before)

    def test_apply_without_preview_rejected(self):
        self.assertEqual(self.request('POST', '/api/apply', {'prompt': 'rules'})[0], 409)

    def test_unknown_fields_and_invalid_types_rejected(self):
        for body in ({'home': '/tmp/other'}, {'prompt': 1}, {'max_iterations': True}, ['not object']):
            with self.subTest(body=body):
                self.assertEqual(self.request('POST', '/api/plan', body)[0], 409)

    def test_stale_preview_preserves_edit(self):
        _, data = self.request('POST', '/api/plan', {'prompt': 'rules'})
        plan = json.loads(data)
        modified = b'edited: true\n'
        self.manager.config.write_bytes(modified)
        self.assertEqual(self.request('POST', '/api/apply', {'prompt': 'rules', 'expected_sha256': plan['before_sha256']})[0], 409)
        self.assertEqual(self.manager.config.read_bytes(), modified)

    def test_server_only_loopback(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')


if __name__ == '__main__':
    unittest.main()
