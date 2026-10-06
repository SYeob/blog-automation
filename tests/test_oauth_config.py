import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(__file__).resolve().parents[1] / 'wordpress_draft_test.py'
spec = importlib.util.spec_from_file_location('wp', SOURCE)
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)

class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / '.env'
        self.env.write_text('WP_CLIENT_ID=123\nWP_CLIENT_SECRET="dummy-file-secret"\n')

    def config(self, env=None):
        return patch.multiple(wp, ENV_FILE=self.env), patch.dict(os.environ, env or {}, clear=True)

    def test_script_relative_path(self):
        self.assertEqual(wp.ENV_FILE, SOURCE.parent / '.env')
        before = os.getcwd()
        try:
            os.chdir(self.tmp.name)
            with self.config()[0], self.config()[1]:
                self.assertEqual(wp.load_credentials(), ('123', 'dummy-file-secret'))
        finally:
            os.chdir(before)

    def test_environment_wins(self):
        contexts = self.config({'WP_CLIENT_ID':'456', 'WP_CLIENT_SECRET':'dummy-env-secret'})
        with contexts[0], contexts[1]:
            self.assertEqual(wp.load_credentials(), ('456', 'dummy-env-secret'))

    def test_noninteractive_missing_secret_before_server(self):
        self.env.write_text('WP_CLIENT_ID=123\nWP_CLIENT_SECRET=\n')
        with self.config()[0], self.config()[1], patch.object(wp.sys.stdin, 'isatty', return_value=False), patch.object(wp, 'HTTPServer') as server, patch.object(wp.getpass, 'getpass') as prompt:
            with self.assertRaisesRegex(RuntimeError, 'WP_CLIENT_SECRET'):
                wp.authenticate()
            server.assert_not_called()
            prompt.assert_not_called()

    def test_interactive_fallback(self):
        self.env.write_text('WP_CLIENT_SECRET=\n')
        with self.config()[0], self.config()[1], patch.object(wp.sys.stdin, 'isatty', return_value=True), patch.object(wp.getpass, 'getpass', return_value='dummy-input-secret'):
            self.assertEqual(wp.load_credentials(), ('149833', 'dummy-input-secret'))

    def test_oauth_callback_and_exchange(self):
        captured = {}
        def browser(url):
            captured.update(parse_qs(urlsplit(url).query))
        class Server:
            def __init__(self, address, handler):
                self.handler = handler
                self.address = address
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def handle_request(self):
                request = self.handler.__new__(self.handler)
                request.send_response = Mock()
                request.send_header = Mock()
                request.end_headers = Mock()
                request.wfile = io.BytesIO()
                request.path = '/callback/?state=wrong&code=dummy-code'
                request.do_GET()
                request.send_response.assert_called_with(400)
                request.path = '/callback/?state=' + captured['state'][0] + '&code=dummy-code'
                request.do_GET()
                request.send_response.assert_called_with(200)
        with self.config()[0], self.config()[1], patch.object(wp, 'HTTPServer', Server), patch.object(wp.webbrowser, 'open', side_effect=browser), patch.object(wp, 'request_json', return_value={'access_token':'dummy-token'}) as api, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(wp.authenticate(), 'dummy-token')
            self.assertEqual(captured['client_id'], ['123'])
            self.assertEqual(captured['blog'], [wp.SITE])
            self.assertEqual(captured['redirect_uri'], [wp.REDIRECT])
            body = api.call_args.args[1]
            self.assertEqual(body['client_secret'], 'dummy-file-secret')
            self.assertEqual(body['code'], 'dummy-code')
            self.assertNotIn('dummy-file-secret', output.getvalue())
            self.assertNotIn('dummy-code', output.getvalue())
            self.assertNotIn('dummy-token', output.getvalue())

    def run_main(self, responses):
        api = Mock(side_effect=responses)
        output = io.StringIO()
        with patch.object(wp, 'authenticate', return_value='dummy-token'), patch.object(wp, 'request_json', api), contextlib.redirect_stdout(output):
            wp.main()
        self.assertNotIn('dummy-token', output.getvalue())
        return api

    def test_draft_create_and_verify(self):
        api = self.run_main([{'URL':'https://' + wp.SITE}, {'posts':[]}, {'ID':42}, {'status':'draft'}])
        self.assertEqual(api.call_count, 4)
        self.assertEqual(api.call_args_list[2].args[1]['status'], 'draft')
        self.assertEqual(api.call_args_list[2].args[1]['slug'], wp.SLUG)
        self.assertTrue(api.call_args_list[3].args[0].endswith('/posts/42'))

    def test_existing_post_reused(self):
        api = self.run_main([{'URL':'https://' + wp.SITE}, {'posts':[{'slug':wp.SLUG, 'ID':42, 'status':'draft'}]}])
        self.assertEqual(api.call_count, 2)
        self.assertFalse(any('/posts/new' in call.args[0] for call in api.call_args_list))

    def test_site_mismatch_stops(self):
        with self.assertRaisesRegex(RuntimeError, '대상 사이트'):
            self.run_main([{'URL':'https://other.wordpress.com'}])

    def test_non_draft_verification_fails(self):
        with self.assertRaisesRegex(RuntimeError, 'draft'):
            self.run_main([{'URL':'https://' + wp.SITE}, {'posts':[]}, {'ID':42}, {'status':'publish'}])

if __name__ == '__main__':
    unittest.main(verbosity=2)
