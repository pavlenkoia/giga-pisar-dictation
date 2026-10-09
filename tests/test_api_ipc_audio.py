import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import gi
gi.require_version("GLib", "2.0")
gi.require_version("Gio", "2.0")
from gi.repository import GLib, Gio

from giga_pisar_dictation.api import ApiClient, ApiError
from giga_pisar_dictation.app import parse_command
from giga_pisar_dictation.audio import PrivateWav


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body, headers=()):
        self.send_response(status)
        for k, v in headers: self.send_header(k, v)
        self.end_headers()
        try: self.wfile.write(body)
        except BrokenPipeError: pass
    def do_GET(self):
        self.server.seen_auth = self.headers.get("Authorization")
        if self.path.startswith("/redirect"): self.respond(302, b"", [("Location", "http://127.0.0.1:1/stolen")])
        elif self.path.startswith("/large"): self.respond(200, b"x" * 70000)
        elif self.path.startswith("/bad-json"): self.respond(200, b"no json")
        elif self.path.startswith("/unauthorized"): self.respond(401, b"private")
        elif self.path.startswith("/forbidden"): self.respond(403, b"private")
        elif self.path.startswith("/too-large"): self.respond(413, b"private")
        elif self.path.startswith("/slow"): threading.Event().wait(1.3); self.respond(200, b'{"status":"ok"}')
        elif self.path.startswith("/trickle"):
            self.send_response(200); self.send_header("Content-Length", "40"); self.end_headers()
            try:
                for _ in range(40):
                    self.wfile.write(b" "); self.wfile.flush(); time.sleep(0.2)
            except OSError: pass
        else: self.respond(200, b'{"status":"ok"}')
    def do_POST(self):
        self.server.body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.seen_auth = self.headers.get("Authorization")
        response = self.server.response
        self.respond(response[0], response[1])
    def log_message(self, *args): pass


class AsyncSoupTests(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.response = (200, b'{"text":"\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442"}')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.client = ApiClient(self.base, "fictional-test-key", timeout=1)
    def tearDown(self): self.server.shutdown(); self.thread.join(); self.server.server_close()
    def wait(self, invoke):
        loop = GLib.MainLoop(); result = []
        invoke(lambda value, error: (result.append((value, error)), loop.quit()))
        GLib.timeout_add_seconds(4, lambda: (loop.quit(), False)[1])
        loop.run()
        self.assertTrue(result, "Soup callback did not complete")
        return result[0]
    def test_soup_health_and_multipart(self):
        value, error = self.wait(lambda cb: self.client.health_async(cb))
        self.assertIsNone(error); self.assertEqual(value["status"], "ok")
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "selected.wav"; wav.write_bytes(b"RIFFfake")
            text, error = self.wait(lambda cb: self.client.transcribe_async(wav, cb))
        self.assertIsNone(error); self.assertEqual(text, "Привет")
        self.assertEqual(self.server.seen_auth, "Bearer fictional-test-key")
        self.assertIn(b'name="file"; filename="recording.wav"', self.server.body)
        self.assertIn(b"RIFFfake", self.server.body)
    def test_soup_status_json_size_cancel_timeout_and_redirect(self):
        for path, expect in (("/unauthorized", "authorization"), ("/forbidden", "authorization"),
                             ("/too-large", "size limit"), ("/redirect", "Redirect"),
                             ("/bad-json", "invalid JSON"), ("/large", "too large")):
            client = ApiClient(self.base + path, "fictional-test-key", timeout=1)
            _, error = self.wait(lambda cb: client.health_async(cb))
            self.assertIsInstance(error, ApiError); self.assertIn(expect.lower(), str(error).lower())
        cancelled = Gio.Cancellable(); cancelled.cancel()
        _, error = self.wait(lambda cb: self.client.health_async(cb, cancelled))
        self.assertIsInstance(error, ApiError); self.assertIn("cancel", str(error).lower())
        client = ApiClient("http://127.0.0.1:1", "fictional-test-key", timeout=1)
        _, error = self.wait(lambda cb: client.health_async(cb))
        self.assertIsInstance(error, ApiError); self.assertIn("unavailable", str(error).lower())
        client = ApiClient(self.base + "/slow", "fictional-test-key", timeout=1)
        _, error = self.wait(lambda cb: client.health_async(cb))
        self.assertIsInstance(error, ApiError)
        self.assertIn("timed out", str(error).lower())
        client = ApiClient(self.base + "/trickle", "fictional-test-key", timeout=1)
        started = time.monotonic(); operation = []
        _, error = self.wait(lambda cb: operation.append(client.health_async(cb)))
        self.assertIsInstance(error, ApiError)
        self.assertIn("timed out", str(error).lower())
        self.assertTrue(operation[0].timed_out); self.assertTrue(operation[0].finished)
        self.assertIsNone(operation[0].timer_id)
        self.assertLess(time.monotonic() - started, 2.5)
    def test_deadline_timer_is_removed_and_completion_is_single_shot(self):
        timers = {}; removed = []
        client = ApiClient(self.base, "fictional-test-key", timer_add=lambda ms, cb: timers.setdefault(9, cb) and 9,
                           timer_remove=lambda source: removed.append(source))
        callbacks = []; operation = []
        self.wait(lambda cb: operation.append(client.health_async(lambda value, error: (callbacks.append((value, error)), cb(value, error)))))
        self.assertEqual(len(callbacks), 1)
        self.assertTrue(operation[0].finished); self.assertIsNone(operation[0].timer_id)
        self.assertEqual(removed, [9])
        timers[9]()
        self.assertEqual(len(callbacks), 1)

    def test_bad_transcription_types_empty(self):
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "a.wav"; wav.write_bytes(b"RIFF")
            for body in (b'{"text":2}', b'{"text":"  "}', b'{"unexpected":true}'):
                self.server.response = (200, body)
                _, error = self.wait(lambda cb: self.client.transcribe_async(wav, cb))
                self.assertIsInstance(error, ApiError)


class IpcAudioTests(unittest.TestCase):
    def test_commands_and_private_file_lifecycle(self):
        self.assertEqual(parse_command(["status"]), "status")
        with self.assertRaises(ValueError): parse_command(["unknown"])
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "private"; wav = PrivateWav(folder); wav.path.write_bytes(b"audio")
            self.assertEqual(wav.path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(wav.path.exists()); wav.remove(); self.assertFalse(wav.path.exists())
            stale = folder / "recording-stale.wav"; stale.write_bytes(b"old")
            PrivateWav.cleanup_stale(folder)
            self.assertFalse(stale.exists())


if __name__ == "__main__": unittest.main()
