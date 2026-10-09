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
                 x11_factory=X11Adapter, glib=GLib, thread_factory=threading.Thread,
                 hotkey_factory=None, config_saver=None, key_saver=None):
        self.view = view
        self.glib, self.thread_factory = glib, thread_factory
        self.hotkey_factory = hotkey_factory
        self.config_saver, self.key_saver = config_saver, key_saver
        self.shortcut_status = "Shortcut disabled"
        self.shortcut_healthy = False
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
        self.hotkey = None
        self._register_hotkey()
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)
        self.view.status.set_text("WARNING: HTTP does not encrypt the API key or audio; trusted LAN only; " + self.shortcut_status)

    def _register_hotkey(self):
        if not self.config.hotkey_enabled: return
        try:
            from .hotkey import X11Hotkey
            factory = self.hotkey_factory or X11Hotkey
            self.hotkey = factory(self.config.hotkey_accelerator, self._hotkey_toggle,
                                  glib=self.glib, target_at_press=lambda: self.x11.active_window() if self.x11 else None,
                                  on_error=self._hotkey_error, on_status=self._hotkey_status_changed)
            self.shortcut_healthy = getattr(self.hotkey, "healthy", True)
            self.shortcut_status = ("Global shortcut active: " + self.config.hotkey_accelerator
                                    if self.shortcut_healthy else "Global shortcut unavailable after X11 keymap change")
        except Exception:
            self.hotkey = None
            self.shortcut_healthy = False
            self.shortcut_status = "Global shortcut unavailable; choose another shortcut in Settings"

    def _hotkey_status_changed(self, healthy, accelerator=None):
        self.shortcut_healthy = bool(healthy)
        if self.shortcut_healthy:
            self.shortcut_status = "Global shortcut active: " + (accelerator or self.config.hotkey_accelerator)
        else:
            self.shortcut_status = "Global shortcut unavailable after X11 keymap change"
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)

    def _hotkey_error(self, _message):
        self._hotkey_status_changed(False)

    def _hotkey_toggle(self, target=None):
        starting = self.view.controller.state in (State.IDLE, State.RESULT, State.ERROR)
        if starting:
            self.target = target
        self._hotkey_target_pending = starting
        result = self.command("toggle")
        if not result.get("ok"): self._hotkey_target_pending = False
        return GLib.SOURCE_REMOVE

    def start_recording(self):
        if not self.client: raise RuntimeError("API key is not configured")
        target_captured = getattr(self, "_hotkey_target_pending", False)
        active = None if target_captured else (self.x11.active_window() if self.x11 else None)
        self._hotkey_target_pending = False
        own = None
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            own = self.view.window.get_window().get_xid()
        except Exception: pass
        if not target_captured:
            self.target = active if active and active != own else self.view.external_window
        self.wav = self.wav_factory(self.audio_directory)
        self.recording_generation += 1
        generation = self.recording_generation
        self.recorder = self.recorder_factory(self.wav.path, self.config.audio_source,
                                              lambda: self._audio_error(generation))
        self.limit_source = self.glib.timeout_add_seconds(300, lambda: self._recording_limit(generation))
        self.view.status.set_text("WARNING: plain HTTP exposes the Bearer key on trusted LAN; recording; " + self.shortcut_status)

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

    def save_settings(self, url, timeout, source, key, auto_insert, hotkey_enabled=True, hotkey_accelerator="Ctrl+Space"):
        from .config import save_api_key, save_config
        saver = self.config_saver or save_config
        key_saver = self.key_saver or save_api_key
        new_config = replace(self.config, base_url=url.strip(), timeout_seconds=timeout,
                             audio_source=source.strip(), auto_insert=bool(auto_insert),
                             hotkey_enabled=bool(hotkey_enabled), hotkey_accelerator=hotkey_accelerator.strip())
        new_config.validate()
        old_config = self.config
        old_hotkey = self.hotkey
        changed_registration = False
        new_registration = None
        if new_config.hotkey_enabled:
            if old_hotkey:
                if new_config.hotkey_accelerator != old_config.hotkey_accelerator:
                    changed_registration = old_hotkey.prepare_rebind(new_config.hotkey_accelerator)
            elif self.hotkey_factory:
                new_registration = self.hotkey_factory(new_config.hotkey_accelerator, self._hotkey_toggle,
                    glib=self.glib, target_at_press=lambda: self.x11.active_window() if self.x11 else None,
                    on_error=None, on_status=None)
            else:
                from .hotkey import X11Hotkey
                new_registration = X11Hotkey(new_config.hotkey_accelerator, self._hotkey_toggle,
                    glib=self.glib, target_at_press=lambda: self.x11.active_window() if self.x11 else None,
                    on_error=None, on_status=None)
        try:
            if key: key_saver(key)
            saver(new_config)
        except Exception:
            if changed_registration and old_hotkey:
                old_hotkey.rollback_rebind()
            if new_registration: new_registration.close()
            raise
        if changed_registration and old_hotkey: old_hotkey.commit_rebind()
        if not new_config.hotkey_enabled and old_hotkey:
            old_hotkey.close(); self.hotkey = None
        elif new_registration:
            self.hotkey = new_registration
            if hasattr(new_registration,"on_error"): new_registration.on_error=self._hotkey_error
            if hasattr(new_registration,"on_status"): new_registration.on_status=self._hotkey_status_changed
        self.config = new_config
        if not new_config.hotkey_enabled:
            self.shortcut_healthy = False
            self.shortcut_status = "Global shortcut disabled"
        elif new_registration:
            self.shortcut_healthy = getattr(new_registration,"healthy",True)
            self.shortcut_status = ("Global shortcut active: " + new_config.hotkey_accelerator
                                    if self.shortcut_healthy else "Global shortcut unavailable after X11 keymap change")
        elif changed_registration:
            self.shortcut_healthy = True
            self.shortcut_status = "Global shortcut active: " + new_config.hotkey_accelerator
        elif old_hotkey:
            self.shortcut_healthy = getattr(old_hotkey,"healthy",self.shortcut_healthy)
            self.shortcut_status = ("Global shortcut active: " + new_config.hotkey_accelerator
                                    if self.shortcut_healthy else "Global shortcut unavailable after X11 keymap change")
        else:
            self.shortcut_healthy = False
            self.shortcut_status = "Global shortcut unavailable; choose another shortcut in Settings"
        self.key = load_api_key()
        self.client = ApiClient(self.config.base_url, self.key, self.config.timeout_seconds) if self.key else None
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)
        self.view.status.set_text("Settings saved; WARNING: HTTP sends the Bearer key in cleartext on trusted LAN; " + self.shortcut_status)

    def shutdown(self):
        if self.cancellable: self.cancellable.cancel()
        if self.view.controller.state not in (State.IDLE, State.RESULT, State.ERROR):
            self.view.controller.cancel()
        self.remove_audio()
        if self.hotkey:
            self.hotkey.close(); self.hotkey = None
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
