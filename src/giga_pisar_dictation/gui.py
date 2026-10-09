"""GTK3 window with Ayatana/AppIndicator tray and visible fallback quit."""
import gi
gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
from .controller import State
from .audio_devices import list_audio_sources
from .tray import TrayPolicy, TrayWatcher, icon_for_state, requires_quit_confirmation


class DesktopWindow:
    def __init__(self):
        self.window = Gtk.Window(title="Гига Писарь")
        self.window.set_default_size(460, 340)
        self.shortcut_status = Gtk.Label(label="Состояние глобальной клавиши: запуск")
        self.status = Gtk.Label(label="Готово"); self.output = Gtk.TextView()
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR); self.output.set_editable(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(12)
        box.pack_start(self.status, False, False, 0); box.pack_start(self.shortcut_status, False, False, 0); box.pack_start(self.output, True, True, 0)
        controls = Gtk.Box(spacing=6)
        for label, command in (("Начать", "start"), ("Остановить", "stop"), ("Отменить", "cancel"),
                               ("Копировать", "copy"), ("Проверить сервер", "health"),
                               ("Настройки", "settings"), ("Выйти", "quit")):
            button = Gtk.Button(label=label); button.connect("clicked", self._button, command)
            controls.pack_start(button, True, True, 0)
        box.pack_start(controls, False, False, 0); self.window.add(box)
        self.window.connect("delete-event", self._hide)
        self.window.connect("focus-out-event", self._focus_lost)
        self.external_window = None; self.indicator = None
        self.tray_policy = TrayPolicy()
        self._host_available = None
        self._launch_mode_applied = False
        self._shutdown = False
        self._create_indicator()
        try: self.tray_watcher = TrayWatcher(self._tray_changed)
        except Exception: self.tray_watcher = None; self.tray_policy.update(False)
        self.tray_policy.subscribe(self._tray_lost)

    def _create_indicator(self, indicator_namespace=None):
        if indicator_namespace is None:
            try:
                gi.require_version("AyatanaAppIndicator3", "0.1")
                from gi.repository import AyatanaAppIndicator3 as Indicator
            except (ImportError, ValueError):
                try:
                    gi.require_version("AppIndicator3", "0.1")
                    from gi.repository import AppIndicator3 as Indicator
                except (ImportError, ValueError): return
        else:
            Indicator = indicator_namespace
        try:
            self.Indicator = Indicator
            self.indicator = Indicator.Indicator.new("giga-pisar-dictation", "audio-input-microphone",
                                                      Indicator.IndicatorCategory.APPLICATION_STATUS)
            self.indicator.set_status(Indicator.IndicatorStatus.ACTIVE)
            try: self.indicator.connect("notify::connected", self._indicator_status_changed)
            except (TypeError, AttributeError): pass
        except Exception:
            self.indicator = None
            self.Indicator = None
            return
        menu = Gtk.Menu()
        show_item = None
        for title, command in (("Показать окно", "show"), ("Переключить запись", "toggle"), ("Начать", "start"),
                               ("Остановить", "stop"), ("Отменить", "cancel"), ("Состояние", "status"), ("Выйти", "quit")):
            item = Gtk.MenuItem(label=title); item.connect("activate", self._menu_action, command); menu.append(item)
            if command == "show": show_item = item
        menu.show_all(); self.indicator.set_menu(menu)
        try: self.indicator.set_secondary_activate_target(show_item)
        except (AttributeError, TypeError): pass

    def _focus_lost(self, *_):
        GLib.timeout_add(120, self._remember_external_window)
        return False

    def _remember_external_window(self):
        x11 = None
        try:
            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11
            own = self.window.get_window().get_xid()
            from .x11 import X11Adapter
            x11 = X11Adapter(); target = x11.active_window()
            if target and target != own: self.external_window = target
        except Exception: pass
        finally:
            if x11: x11.close()
        return GLib.SOURCE_REMOVE

    def refresh(self):
        self.status.set_text(self.controller.message)
        self.output.get_buffer().set_text(self.controller.text or "")
        if self.indicator:
            state = self.controller.state
            icon = icon_for_state(state)
            try:
                state_label = {"IDLE": "Ожидание", "RECORDING": "Запись", "FINALIZING": "Завершение",
                               "REQUESTING": "Распознавание", "RESULT": "Готово", "ERROR": "Ошибка"}.get(state.name, "Состояние")
                self.indicator.set_icon_full(icon, state_label)
                self.indicator.set_title("Гига Писарь — " + state_label)
            except Exception: pass

    def _indicator_connected(self):
        if self.indicator is None:
            return False
        try: return bool(self.indicator.get_property("connected"))
        except Exception: return False

    def _indicator_status_changed(self, *_):
        self._tray_changed(self._host_available)

    def _tray_changed(self, available):
        self._host_available = available
        connected = self._indicator_connected()
        self.tray_policy.update(None if available is None else bool(available and connected))

    def _tray_lost(self, available):
        if available is False and not self.window.get_visible():
            self.window.show_all()
            self.status.set_text("Трей недоступен; окно восстановлено")

    def _finish_launch(self, mode):
        if mode == "autostart" and self.tray_policy.may_start_hidden():
            self.window.hide()
        else:
            self.window.show_all()
        if not getattr(self.effects, "key", ""):
            self.window.show_all()
            GLib.idle_add(self.settings_dialog)

    def apply_launch_mode(self, mode):
        if self._launch_mode_applied: return GLib.SOURCE_REMOVE
        self._launch_mode_applied = True
        # An unresolved host is not evidence that hiding is safe; keep launch visible.
        self._finish_launch("ordinary" if mode == "autostart" and self.tray_policy.available is None else mode)
        return GLib.SOURCE_REMOVE

    def modifiers_down(self):
        return self.effects.x11.modifiers_down() if self.effects.x11 else True

    def _show_window(self, *_):
        self.window.show_all()
        self.window.present()

    def _menu_action(self, _item, command):
        if command == "show": self._show_window()
        elif command == "quit": self.quit()
        else: self._action(command)

    def _hide(self, *_):
        if self.tray_policy.may_hide():
            self.window.hide()
        else:
            self.status.set_text("Трей недоступен; оставьте окно открытым или нажмите «Выйти»")
        return True

    def _action(self, command):
        if hasattr(self, "effects"): self.effects.command(command)

    def quit(self):
        if hasattr(self, "controller") and requires_quit_confirmation(self.controller.state):
            dialog = Gtk.MessageDialog(transient_for=self.window, flags=0, message_type=Gtk.MessageType.WARNING,
                                      buttons=Gtk.ButtonsType.NONE, text="Выполняется операция")
            dialog.format_secondary_text("Выйти и отменить текущую операцию? Временная аудиозапись будет удалена.")
            dialog.add_button("Продолжить", Gtk.ResponseType.CANCEL)
            dialog.add_button("Выйти", Gtk.ResponseType.OK)
            response = dialog.run(); dialog.destroy()
            if response != Gtk.ResponseType.OK: return False
        if not self._shutdown:
            self._shutdown = True
            if hasattr(self, "effects"): self.effects.shutdown()
            if self.indicator: self.indicator.set_status(self.Indicator.IndicatorStatus.PASSIVE)
            if getattr(self, "tray_watcher", None): self.tray_watcher.close(); self.tray_watcher = None
        Gtk.main_quit()
        return True

    def _button(self, _, command):
        if command == "copy":
            buffer = self.output.get_buffer(); start, end = buffer.get_bounds()
            text = buffer.get_text(start, end, True)
            success = bool(getattr(self, "effects", None) and
                           self.effects.clipboard.copy_text(text, self.effects.x11))
            self.status.set_text("Текст скопирован" if success else "Не удалось подтвердить копирование")
        elif command == "health": self.effects.health()
        elif command == "settings": self.settings_dialog()
        elif command == "quit": self.quit()
        else: self._action(command)

    def settings_dialog(self):
        autostart_available = True
        try: autostart_enabled = self.effects.autostart.is_enabled()
        except (OSError, ValueError):
            autostart_available = False
            autostart_enabled = False
        dialog = Gtk.Dialog(title="Настройки", transient_for=self.window, flags=0)
        dialog.add_button("Отменить", Gtk.ResponseType.CANCEL); dialog.add_button("Сохранить", Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        shortcut_state = Gtk.Label(label=self.effects.shortcut_status)
        url = Gtk.Entry(); url.set_text(self.effects.config.base_url)
        timeout = Gtk.SpinButton.new_with_range(1, 3600, 1); timeout.set_value(self.effects.config.timeout_seconds)
        source = Gtk.ComboBoxText()
        source.append("", "Системный по умолчанию")
        source_error = None
        try:
            audio_sources = list_audio_sources()
        except Exception:
            audio_sources = []
            source_error = Gtk.Label(label="Не удалось получить список микрофонов; текущая настройка сохранена.")
        current_source = self.effects.config.audio_source
        for device_id, display_name in audio_sources:
            source.append(device_id, display_name)
        if current_source and current_source not in {device_id for device_id, _ in audio_sources}:
            source.append(current_source, "Недоступный микрофон")
        source.set_active_id(current_source)
        key = Gtk.Entry(); key.set_visibility(False); key.set_placeholder_text("Оставьте пустым, чтобы сохранить прежний ключ")
        auto = Gtk.CheckButton(label="Вставлять автоматически только в исходное активное окно X11")
        auto.set_active(self.effects.config.auto_insert)
        autostart = Gtk.CheckButton(label="Запускать при входе в систему")
        autostart.set_active(autostart_enabled)
        autostart.set_sensitive(autostart_available)
        hotkey_enabled = Gtk.CheckButton(label="Включить глобальную клавишу X11")
        hotkey_enabled.set_active(self.effects.config.hotkey_enabled)
        hotkey = Gtk.Entry(); hotkey.set_text(self.effects.config.hotkey_accelerator)
        settings_rows = [("Состояние клавиши", shortcut_state), ("Базовый URL API", url), ("Тайм-аут (секунды)", timeout), ("Микрофон", source)]
        if source_error:
            settings_rows.append(("", source_error))
        settings_rows.extend((("Ключ API", key), ("", auto), ("", autostart)))
        if not autostart_available:
            settings_rows.append(("", Gtk.Label(label="Не удалось проверить автозапуск; его состояние не изменено.")))
        settings_rows.extend((("", hotkey_enabled), ("Клавиша (например, Ctrl+Space)", hotkey)))
        for row, (label, widget) in enumerate(settings_rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1); grid.attach(widget, 1, row, 1, 1)
        dialog.get_content_area().add(grid); dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            try: self.effects.save_settings(url.get_text(), timeout.get_value_as_int(), source.get_active_id() or "", key.get_text(), auto.get_active(), hotkey_enabled.get_active(), hotkey.get_text(), autostart_enabled=autostart.get_active() if autostart_available else None)
            except (ValueError, PermissionError, OSError, RuntimeError): self.status.set_text("Настройки отклонены: сочетание недоступно или неверны права доступа к настройкам")
        dialog.destroy()


def launch_window():
    from .desktop import DesktopController
    window = DesktopWindow(); DesktopController(window); Gtk.main(); return window
