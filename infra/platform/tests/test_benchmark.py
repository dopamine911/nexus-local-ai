import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/benchmark.py'


class BenchmarkTests(unittest.TestCase):
    def test_real_http_requests_record_usage_without_storing_content(self):
        """Exercise the CLI and concurrent network path against a local API fixture."""
        received = []
        class API(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, payload, self.headers.get('Authorization')))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': 'private completion'}}],
                                             'usage': {'completion_tokens': 4}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), API)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                key = root / 'key'
                key.write_text('private-api-key')
                key.chmod(0o600)
                prompt = root / 'prompt'
                prompt.write_text('private prompt')
                report = root / 'report.json'
                subprocess.run([sys.executable, str(SCRIPT), '--url', f'http://127.0.0.1:{server.server_port}/v1',
                                '--model', 'local-fast', '--api-key-file', str(key), '--prompt-file', str(prompt),
                                '--runs', '3', '--concurrency', '2', '--output', str(report)], check=True, capture_output=True)
                data = json.loads(report.read_text())
                self.assertEqual(len(data['runs']), 3)
                self.assertTrue(all(item['seconds'] > 0 and item['completion_tokens'] == 4 for item in data['runs']))
                self.assertEqual(len(received), 3)
                self.assertTrue(all(item[0] == '/v1/chat/completions' and item[2] == 'Bearer private-api-key' for item in received))
                for private in ('private prompt', 'private completion', 'private-api-key'):
                    self.assertNotIn(private, report.read_text())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_remote_provider_is_refused_before_credentials_are_read(self):
        """A benchmark typo cannot send prompts to a remote paid API."""
        result = subprocess.run([sys.executable, str(SCRIPT), '--url', 'https://openrouter.ai/api/v1',
                                 '--model', 'model', '--api-key-file', '/missing/key', '--prompt-file', '/missing/prompt',
                                 '--output', '/missing/report'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Use a loopback', result.stderr)


if __name__ == '__main__':
    unittest.main()
