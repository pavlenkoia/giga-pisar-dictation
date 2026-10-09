"""Desktop command/effect wiring; platform effects are invoked only on user commands."""
from __future__ import annotations
import threading
from dataclasses import replace
import gi
gi.require_version("GLib", "2.0"); gi.require_version("Gio", "2.0")
from gi.repository import GLib, Gio
from .api import ApiClient
from .audio import GstRecorder, PrivateWav, private_audio_directory
from .config import load_api_key, load_config
from .controller import Controller, State
from .clipboard import GtkClipboardAdapter
from .x11 import X11Adapter


class DesktopEffects:
    def __init__(self, view, *, config=None, key=None, client=None, audio_directory=None,
                 wav_factory=PrivateWav, recorder_factory=GstRecorder, clipboard=None,
                 x11_factory=X11Adapter, glib=GLib, thread_factory=threading.Thread):
        self.view = view
        self.glib, self.thread_factory = glib, thread_factory
        self.wav_factory, self.recorder_factory = wav_factory, recorder_factory
        self.config = config or load_config()
        self.key = load_api_key() if key is None else key
        self.audio_directory = audio_directory or private_audio_directory()
        PrivateWav.cleanup_stale(self.audio_directory)
        self.client = client if client is not None else (ApiClient(self.config.base_url, self.key, self.config.timeout_seconds) if self.key else None)
        self.clipboard = clipboard or GtkClipboardAdapter()
        try: self.x11 = x11_factory()
        except RuntimeError: self.x11 = None
        self.target = None; self.wav = None; self.recorder = None; self.cancellable = None
        self.recording_generation = 0
        self.view.status.set_text("WARNING: HTTP does not encrypt the API key or audio; trusted LAN only")

    def start_recording(self):
        if not self.client: raise RuntimeError("API key is not configured")
        active = self.x11.active_window() if self.x11 else None
        own = None
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            own = self.view.window.get_window().get_xid()
        except Exception: pass
        self.target = active if active and active != own else self.view.external_window
        self.wav = self.wav_factory(self.audio_directory)
        self.recording_generation += 1
        generation = self.recording_generation
        self.recorder = self.recorder_factory(self.wav.path, self.config.audio_source,
                                              lambda: self._audio_error(generation))
        self.limit_source = self.glib.timeout_add_seconds(300, lambda: self._recording_limit(generation))
        self.view.status.set_text("WARNING: plain HTTP exposes the Bearer key on trusted LAN; recording")

    def _audio_error(self, generation):
        if generation == self.recording_generation and self.view.controller.state == State.RECORDING:
            self.view.controller.fail("Audio device or file error")
            self.view.refresh()

    def _recording_limit(self, generation):
        if generation == self.recording_generation and self.view.controller.state == State.RECORDING:
            self.view.controller.cancel()
            self.view.status.set_text("Five-minute recording limit reached; audio discarded")
        return GLib.SOURCE_REMOVE

    def finalize_recording(self):
        generation = self.recording_generation
        recorder, wav = self.recorder, self.wav
        if getattr(self, "limit_source", None):
            self.glib.source_remove(self.limit_source); self.limit_source = None
        def finalize():
            try:
                recorder.stop()
                valid, error = wav.path.stat().st_size > 44, None
            except Exception:
                valid, error = False, True
            def complete():
                if generation != self.recording_generation or self.view.controller.state != State.FINALIZING:
                    return GLib.SOURCE_REMOVE
                if error: self.view.controller.fail("Audio finalization failed")
                else: self.view.controller.audio_finalized(valid)
                self.view.refresh()
                return GLib.SOURCE_REMOVE
            self.glib.idle_add(complete)
        self.thread_factory(target=finalize, daemon=True).start()

    def cancel_recording(self):
        if getattr(self, "limit_source", None):
            self.glib.source_remove(self.limit_source); self.limit_source = None
        if self.recorder:
            self.recorder.cancel()
        self.view.refresh()

    def submit_audio(self):
        self.cancellable = Gio.Cancellable()
        generation, wav = self.view.controller._request_generation, self.wav
        self.request_generation = generation
        self.client.transcribe_async(wav.path,
            lambda text, error, request_generation=generation: self._response(text, error, request_generation),
            self.cancellable)
        self.view.refresh()

    def _response(self, text, error, generation):
        if self.view.controller.state != State.REQUESTING or generation != self.view.controller._request_generation:
            return
        delivery_status = None
        if error: self.view.controller.fail(str(error))
        else:
            self.view.controller.response(text, generation)
            inserted = False
            if self.config.auto_insert and self.target and self.x11:
                try: inserted = self.clipboard.paste_safely(text, self.x11, self.target, self.view.modifiers_down())
                except Exception: inserted = False
            if not inserted: delivery_status = "Transcription ready; not inserted. Review and copy manually."
            else: delivery_status = "Paste sent; delivery is not confirmed. Review the target window."
        self.view.refresh()
        if delivery_status: self.view.status.set_text(delivery_status)

    def cancel_request(self):
        if self.cancellable: self.cancellable.cancel()

    def remove_audio(self):
        self.recording_generation = getattr(self, "recording_generation", 0) + 1
        if self.recorder:
            try: self.recorder.cancel()
            except Exception: pass
        if self.wav:
            folder = self.wav.directory
            try: self.wav.remove()
            except OSError: self.view.status.set_text("Could not remove temporary audio file")
            try: folder.rmdir()
            except OSError: pass
        self.recorder = None
        self.view.refresh()

    def health(self):
        if not self.client:
            self.view.status.set_text("WARNING: plain HTTP on trusted LAN only; configure key to check server")
            return
        self.client.health_async(lambda data, error: self.view.status.set_text(
            "WARNING: unencrypted HTTP; server reachable" if not error else
            "WARNING: unencrypted HTTP; " + str(error)))

    def save_settings(self, url, timeout, source, key, auto_insert):
        from .config import save_api_key, save_config
        from .config import config_dir
        new_config = replace(self.config, base_url=url.strip(), timeout_seconds=timeout,
                             audio_source=source.strip(), auto_insert=bool(auto_insert))
        new_config.validate()
        save_config(new_config)
        if key: save_api_key(key)
        self.config = new_config
        self.key = load_api_key()
        self.client = ApiClient(self.config.base_url, self.key, self.config.timeout_seconds) if self.key else None
        self.view.status.set_text("Settings saved; WARNING: HTTP sends the Bearer key in cleartext on trusted LAN")

    def shutdown(self):
        if self.cancellable: self.cancellable.cancel()
        if self.view.controller.state not in (State.IDLE, State.RESULT, State.ERROR):
            self.view.controller.cancel()
        self.remove_audio()
        self.clipboard.shutdown()
        if self.x11:
            self.x11.close(); self.x11 = None

    def command(self, command):
        if command == "start": result = self.view.controller.start()
        elif command == "stop": result = self.view.controller.stop()
        elif command == "cancel": result = self.view.controller.cancel()
        elif command == "toggle": result = self.view.controller.toggle()
        else: return {"status": self.view.controller.state.name.lower()}
        self.view.refresh()
        return {"ok": result, "status": self.view.controller.state.name.lower()}


class DesktopController:
    def __init__(self, view):
        self.view = view
        self.effects = DesktopEffects(view)
        self.controller = Controller(self.effects)
        view.controller = self.controller
        view.effects = self.effects
        self.effects.health()
