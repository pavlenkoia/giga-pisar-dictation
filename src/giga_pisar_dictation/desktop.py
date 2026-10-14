"""Desktop command/effect wiring; platform effects are invoked only on user commands."""
from __future__ import annotations
import threading
import os
import time
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
    PTT_RELEASE_TAIL_MS = 300
    PTT_MINIMUM_HOLD_NS = 700_000_000
    def __init__(self, view, *, config=None, key=None, client=None, audio_directory=None,
                 wav_factory=PrivateWav, recorder_factory=GstRecorder, clipboard=None,
                 x11_factory=X11Adapter, glib=GLib, thread_factory=threading.Thread,
                 hotkey_factory=None, config_saver=None, key_saver=None, autostart_store=None,
                 monotonic_clock_ns=time.monotonic_ns):
        self.view = view
        self.glib, self.thread_factory = glib, thread_factory
        self.monotonic_clock_ns = monotonic_clock_ns
        self.hotkey_factory = hotkey_factory
        self.config_saver, self.key_saver = config_saver, key_saver
        from .autostart import AutostartFile
        self.autostart = autostart_store or AutostartFile()
        self.shortcut_status = "Клавиша отключена"
        self.shortcut_healthy = False
        self.wav_factory, self.recorder_factory = wav_factory, recorder_factory
        self.config = config or load_config()
        self.key = load_api_key() if key is None else key
        self.audio_directory = audio_directory or private_audio_directory()
        PrivateWav.cleanup_stale(self.audio_directory)
        self.client = client if client is not None else (ApiClient(self.config.base_url, self.key, self.config.timeout_seconds) if self.key else None)
        self.clipboard = clipboard or GtkClipboardAdapter()
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            self.x11 = None
        else:
            try: self.x11 = x11_factory()
            except RuntimeError: self.x11 = None
        self.target = None; self.wav = None; self.recorder = None; self.cancellable = None
        self._shutdown = False
        self.recording_generation = 0
        self.hotkey = None
        self._register_hotkey()
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)
        platform_notice = ("; сеанс X11 недоступен; глобальная клавиша и вставка отключены"
                           if self.x11 is None else "")
        self.view.status.set_text("ПРЕДУПРЕЖДЕНИЕ: HTTP не шифрует ключ API и аудио; только доверенная локальная сеть; " +
                                  self.shortcut_status + platform_notice)

    def _register_hotkey(self):
        if not self.config.hotkey_enabled: return
        if self.x11 is None:
            self.hotkey = None
            self.shortcut_healthy = False
            self.shortcut_status = "Для глобальной клавиши и вставки требуется сеанс X11"
            return
        try:
            from .hotkey import X11Hotkey
            factory = self.hotkey_factory or X11Hotkey
            self.hotkey = factory(self.config.hotkey_accelerator, self._hotkey_toggle,
                                  glib=self.glib, target_at_press=lambda: self.x11.active_window() if self.x11 else None,
                                  on_error=self._hotkey_error, on_status=self._hotkey_status_changed,
                                  mode=self.config.hotkey_mode, on_start=self._push_to_talk_start,
                                  on_stop=self._push_to_talk_stop, on_invalidate=self._invalidate_hold)
            self.shortcut_healthy = getattr(self.hotkey, "healthy", True)
            self.shortcut_status = (self._active_hotkey_status()
                                    if self.shortcut_healthy else "Глобальная клавиша недоступна после изменения раскладки X11")
        except Exception:
            self.hotkey = None
            self.shortcut_healthy = False
            self.shortcut_status = "Глобальная клавиша недоступна; выберите другое сочетание в настройках"

    def _active_hotkey_status(self):
        if self.config.hotkey_mode == "push_to_talk":return "Рация — правый Ctrl включена"
        return "Глобальная клавиша включена: " + self.config.hotkey_accelerator

    def _hotkey_status_changed(self, healthy, accelerator=None):
        self.shortcut_healthy = bool(healthy)
        if self.shortcut_healthy:
            self.shortcut_status = self._active_hotkey_status()
        else:
            self.shortcut_status = "Глобальная клавиша недоступна после изменения раскладки X11"
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)

    def _hotkey_error(self, _message):
        self._invalidate_hold()
        self._hotkey_status_changed(False)

    def _clear_ptt_hold(self):
        self._ptt_hold_started_ns = None
        self._ptt_hold_total_ns = 0

    def _invalidate_hold(self):
        owner=getattr(self,"_push_to_talk_owner",None)
        self._push_to_talk_owner=None
        self._clear_ptt_hold()
        controller=getattr(self.view,"controller",None)
        if (owner is not None and owner==getattr(self,"recording_generation",None) and
                controller is not None and controller.state==State.RECORDING and not self._shutdown):
            self.command("cancel")

    def _push_to_talk_start(self, target):
        if self._shutdown:return None
        accepted_at_ns = self.monotonic_clock_ns()
        pending_owner=getattr(self,"_ptt_tail_owner",None)
        if (pending_owner is not None and pending_owner==self.recording_generation and
                self.view.controller.state==State.RECORDING):
            self._cancel_ptt_tail()
            self._ptt_hold_started_ns = accepted_at_ns
            return pending_owner
        previous_target=getattr(self,"target",None)
        previous_pending=getattr(self,"_hotkey_target_pending",False)
        self.target=target
        self._hotkey_target_pending=True
        result=self.command("start")
        if not result.get("ok") or self.view.controller.state!=State.RECORDING:
            self.target=previous_target
            self._hotkey_target_pending=previous_pending
            return None
        owner=self.recording_generation
        self._push_to_talk_owner=owner
        self._ptt_hold_total_ns=0
        self._ptt_hold_started_ns=accepted_at_ns
        return owner

    def _push_to_talk_stop(self, owner):
        if (owner is None or owner!=getattr(self,"_push_to_talk_owner",None) or
                owner!=self.recording_generation or self.view.controller.state!=State.RECORDING or
                getattr(self, "_ptt_hold_started_ns", None) is None):return
        released_at_ns = self.monotonic_clock_ns()
        started_at_ns = self._ptt_hold_started_ns
        if started_at_ns is not None:
            self._ptt_hold_total_ns = getattr(self, "_ptt_hold_total_ns", 0) + max(0, released_at_ns - started_at_ns)
            self._ptt_hold_started_ns = None
        self._cancel_ptt_tail()
        token=getattr(self,"_ptt_tail_token",0)+1
        self._ptt_tail_token=token
        self._ptt_tail_owner=owner
        def finish_tail():
            if token!=getattr(self,"_ptt_tail_token",None):return GLib.SOURCE_REMOVE
            self._ptt_tail_source=None
            if self._ptt_tail_owner==owner:self._ptt_tail_owner=None
            if (owner!=self.recording_generation or owner!=getattr(self,"_push_to_talk_owner",None) or
                    self.view.controller.state!=State.RECORDING):
                return GLib.SOURCE_REMOVE
            self._push_to_talk_owner=None
            held_ns = getattr(self, "_ptt_hold_total_ns", 0)
            self._clear_ptt_hold()
            self.command("stop" if held_ns >= self.PTT_MINIMUM_HOLD_NS else "cancel")
            return GLib.SOURCE_REMOVE
        self._ptt_tail_source=self.glib.timeout_add(self.PTT_RELEASE_TAIL_MS,finish_tail)

    def _cancel_ptt_tail(self):
        self._ptt_tail_token=getattr(self,"_ptt_tail_token",0)+1
        source=getattr(self,"_ptt_tail_source",None)
        self._ptt_tail_source=None
        self._ptt_tail_owner=None
        if source is not None:
            self.glib.source_remove(source)

    def _hotkey_toggle(self, target=None):
        starting = self.view.controller.state in (State.IDLE, State.RESULT, State.ERROR)
        if starting:
            self.target = target
        self._hotkey_target_pending = starting
        result = self.command("toggle")
        if not result.get("ok"): self._hotkey_target_pending = False
        return GLib.SOURCE_REMOVE

    def _cancel_pending_paste(self):
        cancel = getattr(getattr(self, "clipboard", None), "cancel_pending_paste", None)
        if cancel: cancel()

    def start_recording(self):
        if not self.client: raise RuntimeError("Ключ API не настроен")
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
        self._cancel_pending_paste()
        self.recording_generation += 1
        generation = self.recording_generation
        self.recorder = self.recorder_factory(self.wav.path, self.config.audio_source,
                                              lambda: self._audio_error(generation))
        self.limit_source = self.glib.timeout_add_seconds(300, lambda: self._recording_limit(generation))
        self.view.status.set_text("ПРЕДУПРЕЖДЕНИЕ: HTTP передаёт ключ Bearer открыто в доверенной локальной сети; идёт запись; " + self.shortcut_status)

    def _audio_error(self, generation):
        if generation == self.recording_generation and self.view.controller.state == State.RECORDING:
            self._cancel_ptt_tail()
            self._push_to_talk_owner=None
            self._clear_ptt_hold()
            self.view.controller.fail("Ошибка аудиоустройства или файла")
            self.view.refresh()

    def _recording_limit(self, generation):
        if generation == self.recording_generation and self.view.controller.state == State.RECORDING:
            self._cancel_ptt_tail()
            self._push_to_talk_owner=None
            self._clear_ptt_hold()
            self.view.controller.cancel()
            self.view.refresh()
            self.view.status.set_text("Достигнут лимит записи в пять минут; аудио удалено")
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
                if error:
                    self._push_to_talk_owner=None
                    self._clear_ptt_hold()
                    self.view.controller.fail("Не удалось завершить запись аудио")
                else: self.view.controller.audio_finalized(valid)
                self.view.refresh()
                return GLib.SOURCE_REMOVE
            self.glib.idle_add(complete)
        self.thread_factory(target=finalize, daemon=True).start()

    def cancel_recording(self):
        self._cancel_ptt_tail()
        self._push_to_talk_owner=None
        self._clear_ptt_hold()
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
        if getattr(self, "_shutdown", False) or self.view.controller.state != State.REQUESTING or generation != self.view.controller._request_generation:
            return
        self._cancel_pending_paste()
        delivery_status = None
        if error: self.view.controller.fail(str(error))
        else:
            self.view.controller.response(text, generation)
            inserted = False
            refusal = None
            if not self.config.auto_insert:
                refusal = "Автоматическая вставка выключена"
            elif self.x11 is None:
                refusal = "Сеанс X11 недоступен"
            elif not self.target:
                refusal = "Исходное окно не определено"
            elif hasattr(self.clipboard, "paste_safely_async"):
                operation = self.recording_generation
                def paste_complete(sent, reason):
                    if (self._shutdown or not self.config.auto_insert or
                            self.view.controller.state != State.RESULT or
                            operation != self.recording_generation or
                            self.view.controller._request_generation != generation):
                        return
                    self.view.status.set_text("Команда вставки отправлена, доставка не подтверждена. Проверьте целевое окно." if sent else
                        "Расшифровка готова, не вставлена: " + (reason or "неизвестная причина") + ". Проверьте и скопируйте вручную.")
                self.view.refresh()
                try:
                    self.clipboard.paste_safely_async(text, self.x11, self.target, self.view.modifiers_down, paste_complete)
                except Exception:
                    paste_complete(False, "Не удалось безопасно выполнить автоматическую вставку")
                return
            else:
                try:
                    diagnostic_paste = getattr(self.clipboard, "paste_safely_with_reason", None)
                    if diagnostic_paste:
                        inserted, refusal = diagnostic_paste(text, self.x11, self.target, self.view.modifiers_down())
                    else:
                        inserted = self.clipboard.paste_safely(text, self.x11, self.target, self.view.modifiers_down())
                        refusal = None if inserted else "Не удалось безопасно подтвердить вставку"
                except Exception:
                    refusal = "Не удалось безопасно выполнить автоматическую вставку"
            if not inserted: delivery_status = "Расшифровка готова, не вставлена: " + (refusal or "неизвестная причина") + ". Проверьте и скопируйте вручную."
            else: delivery_status = "Команда вставки отправлена, доставка не подтверждена. Проверьте целевое окно."
        self.view.refresh()
        if delivery_status: self.view.status.set_text(delivery_status)

    def cancel_request(self):
        if self.cancellable: self.cancellable.cancel()

    def remove_audio(self):
        self.recording_generation = getattr(self, "recording_generation", 0) + 1
        self._invalidate_hold()
        self._clear_ptt_hold()
        if self.recorder:
            try: self.recorder.cancel()
            except Exception: pass
        if self.wav:
            folder = self.wav.directory
            try: self.wav.remove()
            except OSError: self.view.status.set_text("Не удалось удалить временный аудиофайл")
            try: folder.rmdir()
            except OSError: pass
        self.recorder = None
        self.view.refresh()

    def health(self):
        if not self.client:
            self.view.status.set_text("ПРЕДУПРЕЖДЕНИЕ: HTTP допускается только в доверенной локальной сети; задайте ключ для проверки сервера")
            return
        self.client.health_async(lambda data, error: self.view.status.set_text(
            "ПРЕДУПРЕЖДЕНИЕ: HTTP не зашифрован; сервер доступен" if not error else
            "ПРЕДУПРЕЖДЕНИЕ: HTTP не зашифрован; " + str(error)))

    def save_settings(self, url, timeout, source, key, auto_insert, hotkey_enabled=True,
                      hotkey_accelerator="Ctrl+Space", autostart_enabled=None, hotkey_mode=None):
        from .config import save_api_key, save_config
        saver = self.config_saver or save_config
        key_saver = self.key_saver or save_api_key
        mode= self.config.hotkey_mode if hotkey_mode is None else hotkey_mode
        new_config = replace(self.config, base_url=url.strip(), timeout_seconds=timeout,
                             audio_source=source.strip(), auto_insert=bool(auto_insert),
                             hotkey_enabled=bool(hotkey_enabled), hotkey_accelerator=hotkey_accelerator.strip(),
                             hotkey_mode=mode)
        new_config.validate()
        old_config = self.config
        registration_changed=(new_config.hotkey_enabled != old_config.hotkey_enabled or
            new_config.hotkey_accelerator != old_config.hotkey_accelerator or
            new_config.hotkey_mode != old_config.hotkey_mode)
        if registration_changed and getattr(getattr(self.view,"controller",None),"state",State.IDLE) not in (State.IDLE,State.RESULT,State.ERROR):
            raise RuntimeError("Нельзя менять глобальную клавишу во время записи или распознавания")
        old_hotkey = self.hotkey
        changed_registration = False
        new_registration = None
        if new_config.hotkey_enabled:
            if old_hotkey:
                if (new_config.hotkey_accelerator != old_config.hotkey_accelerator or
                        new_config.hotkey_mode != old_config.hotkey_mode):
                    if new_config.hotkey_mode==old_config.hotkey_mode and hasattr(old_hotkey,"prepare_rebind"):
                        changed_registration=old_hotkey.prepare_rebind(new_config.hotkey_accelerator)
                    else:
                        changed_registration=old_hotkey.prepare_binding(new_config.hotkey_mode,new_config.hotkey_accelerator)
            elif self.x11 is not None:
                from .hotkey import X11Hotkey
                factory=self.hotkey_factory or X11Hotkey
                new_registration = factory(new_config.hotkey_accelerator, lambda *_args:None,
                    glib=self.glib, target_at_press=lambda: self.x11.active_window() if self.x11 else None,
                    on_error=None, on_status=None, mode=new_config.hotkey_mode,
                    on_start=lambda _target:None, on_stop=lambda _owner:None,on_invalidate=lambda:None)
        previous_autostart = None
        autostart_changed = False
        try:
            if autostart_enabled is not None:
                previous_autostart = self.autostart.is_enabled()
                if bool(autostart_enabled) != previous_autostart:
                    self.autostart.set_enabled(bool(autostart_enabled))
                    autostart_changed = True
            if key: key_saver(key)
            saver(new_config)
        except Exception as save_error:
            rollback_errors = []
            if autostart_changed:
                try: self.autostart.set_enabled(previous_autostart)
                except Exception as error: rollback_errors.append(error)
            if changed_registration and old_hotkey:
                try: old_hotkey.rollback_rebind()
                except Exception as error: rollback_errors.append(error)
            if new_registration:
                try: new_registration.close()
                except Exception as error: rollback_errors.append(error)
            if rollback_errors:
                raise RuntimeError("Не удалось сохранить настройки и отменить одно или несколько изменений") from save_error
            raise
        try:
            if new_registration and hasattr(new_registration,"verify_binding"):
                new_registration.verify_binding()
            if changed_registration and old_hotkey:old_hotkey.commit_rebind()
        except Exception as commit_error:
            rollback_errors=[]
            try:saver(old_config)
            except Exception as error:rollback_errors.append(error)
            if autostart_changed:
                try:self.autostart.set_enabled(previous_autostart)
                except Exception as error:rollback_errors.append(error)
            if changed_registration and old_hotkey:
                try:old_hotkey.rollback_rebind()
                except Exception as error:rollback_errors.append(error)
            if new_registration:
                try:new_registration.close()
                except Exception as error:rollback_errors.append(error)
            if rollback_errors:raise RuntimeError("Не удалось подтвердить регистрацию клавиши и восстановить настройки") from commit_error
            raise
        if not new_config.hotkey_enabled and old_hotkey:
            old_hotkey.close(); self.hotkey = None
        elif new_registration:
            self.hotkey = new_registration
            if hasattr(new_registration,"activate"):
                new_registration.activate(self._hotkey_toggle,on_start=self._push_to_talk_start,
                    on_stop=self._push_to_talk_stop,on_invalidate=self._invalidate_hold,
                    on_error=self._hotkey_error,on_status=self._hotkey_status_changed)
            else:
                if hasattr(new_registration,"on_error"): new_registration.on_error=self._hotkey_error
                if hasattr(new_registration,"on_status"): new_registration.on_status=self._hotkey_status_changed
        if not new_config.auto_insert:
            self._cancel_pending_paste()
        self.config = new_config
        if not new_config.hotkey_enabled:
            self.shortcut_healthy = False
            self.shortcut_status = "Глобальная клавиша отключена"
        elif new_registration:
            self.shortcut_healthy = getattr(new_registration,"healthy",True)
            self.shortcut_status = (self._active_hotkey_status()
                                    if self.shortcut_healthy else "Глобальная клавиша недоступна после изменения раскладки X11")
        elif changed_registration:
            self.shortcut_healthy = bool(getattr(old_hotkey,"healthy",True))
            self.shortcut_status = (self._active_hotkey_status() if self.shortcut_healthy
                                    else "Глобальная клавиша недоступна после изменения раскладки X11")
        elif old_hotkey:
            self.shortcut_healthy = getattr(old_hotkey,"healthy",self.shortcut_healthy)
            self.shortcut_status = (self._active_hotkey_status() if self.shortcut_healthy
                                    else "Глобальная клавиша недоступна после изменения раскладки X11")
        else:
            self.shortcut_healthy = False
            self.shortcut_status = "Глобальная клавиша недоступна; выберите другое сочетание в настройках"
        self.key = load_api_key()
        self.client = ApiClient(self.config.base_url, self.key, self.config.timeout_seconds) if self.key else None
        if hasattr(self.view, "shortcut_status"): self.view.shortcut_status.set_text(self.shortcut_status)
        self.view.status.set_text("Настройки сохранены; ПРЕДУПРЕЖДЕНИЕ: HTTP передаёт ключ Bearer открыто в доверенной локальной сети; " + self.shortcut_status)

    def shutdown(self):
        if self._shutdown: return
        self._shutdown = True
        if self.cancellable: self.cancellable.cancel()
        self._cancel_pending_paste()
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
