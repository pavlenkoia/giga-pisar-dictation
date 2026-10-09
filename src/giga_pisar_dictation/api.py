"""Soup 3 asynchronous client for the Giga Pisar HTTP API."""
from __future__ import annotations
import json


class ApiError(Exception):
    """Safe user-facing API error without response bodies or credentials."""


class RequestOperation:
    """Observable lifetime token for one Soup request and its overall deadline."""
    def __init__(self, cancellable):
        self.cancellable = cancellable
        self.timer_id = None
        self.finished = False
        self.timed_out = False
        self.stream = None


class ApiClient:
    _boundary = "----GigaPisarDictationBoundary7MA4YWxk"
    MAX_RESPONSE = 65536
    CHUNK = 8192

    def __init__(self, base_url, key, timeout=120, session=None, timer_add=None, timer_remove=None):
        from .config import Config
        Config(base_url=base_url, timeout_seconds=timeout).validate()
        if not key: raise ValueError("API key is required")
        self.base_url, self.key, self.timeout = base_url.rstrip("/"), key, timeout
        self.session = session
        self._timer_add = timer_add
        self._timer_remove = timer_remove

    def _soup(self):
        import gi
        gi.require_version("Soup", "3.0"); gi.require_version("GLib", "2.0"); gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib, Soup
        session = self.session or Soup.Session.new()
        session.set_timeout(self.timeout)
        return Gio, GLib, Soup, session

    def _message(self, Soup, method, path):
        message = Soup.Message.new(method, self.base_url + path)
        message.set_flags(Soup.MessageFlags.NO_REDIRECT)
        message.get_request_headers().append("Authorization", "Bearer " + self.key)
        return message

    def health_async(self, callback, cancellable=None):
        Gio, GLib, Soup, session = self._soup()
        message = self._message(Soup, "GET", "/health")
        return self._send_bounded(Gio, GLib, session, message, cancellable,
            lambda status, data, error: self._finish_health(status, data, error, callback))

    def transcribe_async(self, wav_path, callback, cancellable=None):
        Gio, GLib, Soup, session = self._soup()
        message = self._message(Soup, "POST", "/v1/audio/transcriptions")
        prefix = (f'--{self._boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.wav"\r\n'
                  "Content-Type: audio/wav\r\n\r\n").encode("ascii")
        from pathlib import Path
        multipart = prefix + Path(wav_path).read_bytes() + f"\r\n--{self._boundary}--\r\n".encode("ascii")
        message.set_request_body_from_bytes("multipart/form-data; boundary=" + self._boundary, GLib.Bytes.new(multipart))
        return self._send_bounded(Gio, GLib, session, message, cancellable,
            lambda status, data, error: self._finish_text(status, data, error, callback))

    def _send_bounded(self, Gio, GLib, session, message, cancellable, done):
        cancellable = cancellable or Gio.Cancellable()
        operation = RequestOperation(cancellable)
        in_deadline = False

        def finish(status, data, error):
            nonlocal in_deadline
            if operation.finished: return
            operation.finished = True
            if operation.timer_id is not None and not in_deadline:
                self._remove_timer(GLib, operation.timer_id)
            operation.timer_id = None
            done(status, data, error)

        def timeout():
            nonlocal in_deadline
            if operation.finished: return False
            in_deadline = True
            operation.timed_out = True
            operation.cancellable.cancel()
            if operation.stream is not None:
                try: operation.stream.close(None)
                except Exception: pass
            finish(message.get_status(), b"", ApiError("Request timed out"))
            in_deadline = False
            return False

        operation.timer_id = self._add_timer(GLib, self.timeout * 1000, timeout)

        def fail(error): finish(message.get_status(), b"", error)
        def on_response(sess, result):
            if operation.finished: return
            try: stream = sess.send_finish(result)
            except Exception as exc:
                fail(ApiError("Request timed out") if operation.timed_out else self._io_error(exc)); return
            operation.stream = stream
            chunks = bytearray()
            def read_next():
                if not operation.finished:
                    stream.read_bytes_async(self.CHUNK, GLib.PRIORITY_DEFAULT, operation.cancellable, on_chunk)
            def on_chunk(input_stream, read_result):
                if operation.finished: return
                try: chunk = input_stream.read_bytes_finish(read_result).get_data()
                except Exception as exc:
                    fail(ApiError("Request timed out") if operation.timed_out else self._io_error(exc)); return
                if isinstance(chunk, tuple): chunk = chunk[0]
                if not chunk:
                    finish(message.get_status(), bytes(chunks), None); return
                chunks.extend(chunk)
                if len(chunks) > self.MAX_RESPONSE:
                    operation.cancellable.cancel()
                    try: stream.close(None)
                    except Exception: pass
                    fail(ApiError("Server response is too large")); return
                read_next()
            read_next()
        try: session.send_async(message, GLib.PRIORITY_DEFAULT, operation.cancellable, on_response)
        except Exception as exc: fail(self._io_error(exc))
        return operation

    def _add_timer(self, GLib, milliseconds, callback):
        if self._timer_add: return self._timer_add(milliseconds, callback)
        return GLib.timeout_add(milliseconds, callback)

    def _remove_timer(self, GLib, source_id):
        if self._timer_remove: self._timer_remove(source_id)
        else: GLib.source_remove(source_id)

    @staticmethod
    def _io_error(exc):
        message = str(exc).lower()
        if "cancel" in message: return ApiError("Request cancelled")
        if "timed out" in message or "timeout" in message: return ApiError("Request timed out")
        return ApiError("Server is unavailable")

    @staticmethod
    def _status_error(status):
        if status in (401, 403): return ApiError("API authorization failed")
        if status == 413: return ApiError("Audio exceeds server size limit")
        if status in (301, 302, 303, 307, 308): return ApiError("Redirect refused")
        if status < 200 or status >= 300: return ApiError(f"Server returned HTTP {status}")
        return None

    def _finish_health(self, status, data, error, callback):
        if error: callback(None, error); return
        if self._status_error(status): callback(None, self._status_error(status)); return
        try: result = json.loads(data)
        except (ValueError, UnicodeDecodeError): callback(None, ApiError("Server returned invalid JSON")); return
        if not isinstance(result, dict): callback(None, ApiError("Server returned invalid health data")); return
        callback(result, None)

    def _finish_text(self, status, data, error, callback):
        if error: callback(None, error); return
        status_error = self._status_error(status)
        if status_error: callback(None, status_error); return
        try: result = json.loads(data)
        except (ValueError, UnicodeDecodeError): callback(None, ApiError("Server returned invalid JSON")); return
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            callback(None, ApiError("Server returned invalid transcription")); return
        if not result["text"].strip(): callback(None, ApiError("Server returned an empty transcription")); return
        callback(result["text"], None)
