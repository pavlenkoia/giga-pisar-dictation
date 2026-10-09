import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from giga_pisar_dictation.api import ApiClient, ApiError


class Button:
    def __init__(self, label):
        self.label = label
        self.connections = []

    def connect(self, signal, callback, *args):
        self.connections.append((signal, callback, args))


class Box:
    def __init__(self, *args, **kwargs): self.children = []
    def set_border_width(self, *_args): pass
    def pack_start(self, widget, *_args): self.children.append(widget)


class Window:
    def __init__(self, **kwargs): self.title = kwargs.get("title"); self.root = None
    def set_default_size(self, *_args): pass
    def add(self, widget): self.root = widget
    def connect(self, *_args): pass


class TextView:
    def set_wrap_mode(self, *_args): pass
    def set_editable(self, *_args): pass


class Label:
    def __init__(self, **kwargs): self.text = kwargs.get("label", "")
    def set_text(self, text): self.text = text


class RussianUiTests(unittest.TestCase):
    def test_button_connect_payloads_are_machine_commands_not_translated_labels(self):
        from giga_pisar_dictation import gui

        class GtkFake:
            Window = Window
            Box = Box
            Label = Label
            TextView = TextView
            Button = Button
            class Orientation: VERTICAL = 1
            class WrapMode: WORD_CHAR = 1

        class Watcher:
            def __init__(self, callback): self.callback = callback

        with patch.object(gui, "Gtk", GtkFake), patch.object(gui.DesktopWindow, "_create_indicator"), \
             patch.object(gui, "TrayWatcher", Watcher):
            view = gui.DesktopWindow()

        controls = view.window.root.children[-1]
        buttons = controls.children
        expected = [("Начать", "start"), ("Остановить", "stop"), ("Отменить", "cancel"),
                    ("Копировать", "copy"), ("Проверить сервер", "health"),
                    ("Настройки", "settings"), ("Выйти", "quit")]
        self.assertEqual(view.window.title, "Гига Писарь")
        self.assertEqual([(button.label, button.connections[0][2][0]) for button in buttons], expected)
        self.assertTrue(all(button.connections[0][0] == "clicked" for button in buttons))

    def test_indicator_refresh_uses_russian_state_description_and_display_title(self):
        from giga_pisar_dictation import gui
        from giga_pisar_dictation.controller import State
        class Indicator:
            def set_icon_full(self, icon, description): self.icon = icon; self.description = description
            def set_title(self, title): self.title = title
        class Buffer:
            def set_text(self, _text): pass
        class Output:
            def get_buffer(self): return Buffer()
        class Status:
            def set_text(self, _text): pass
        view = gui.DesktopWindow.__new__(gui.DesktopWindow)
        view.controller = type("Controller", (), {"state": State.RECORDING, "message": "Запись", "text": None})()
        view.output = Output(); view.status = Status(); view.indicator = Indicator()
        view.refresh()
        self.assertEqual(view.indicator.icon, "giga-pisar-dictation-recording")
        self.assertEqual(view.indicator.description, "Запись")
        self.assertEqual(view.indicator.title, "Гига Писарь — Запись")

    def test_all_captured_button_callbacks_execute_their_command(self):
        from giga_pisar_dictation import gui
        class Buffer:
            def get_bounds(self): return (0, 1)
            def get_text(self, *_args): return "готовый текст"
        class Output:
            def get_buffer(self): return Buffer()
        class Status:
            def set_text(self, value): self.text = value
        class Clipboard:
            def copy_text(self, text, x11): calls.append(("copy", text, x11)); return True
        class Effects:
            clipboard = Clipboard(); x11 = None
            def command(self, command): calls.append(("command", command))
            def health(self): calls.append(("health",))
        calls = []
        with patch.object(gui, "Gtk", type("GtkFake", (), {
            "Window": Window, "Box": Box, "Label": Label, "TextView": TextView,
            "Button": Button, "Orientation": type("Orientation", (), {"VERTICAL": 1}),
            "WrapMode": type("WrapMode", (), {"WORD_CHAR": 1}),
        })), patch.object(gui.DesktopWindow, "_create_indicator"), patch.object(gui, "TrayWatcher", lambda _cb: object()):
            view = gui.DesktopWindow()
        view.effects = Effects(); view.output = Output(); view.status = Status()
        view.settings_dialog = lambda: calls.append(("settings",))
        view.quit = lambda: calls.append(("quit",))
        for button in view.window.root.children[-1].children:
            _signal, callback, args = button.connections[0]
            callback(button, *args)
        self.assertEqual(calls, [
            ("command", "start"), ("command", "stop"), ("command", "cancel"),
            ("copy", "готовый текст", None), ("health",), ("settings",), ("quit",)])

    def test_tray_menu_visible_labels_keep_original_action_identifiers(self):
        from giga_pisar_dictation import gui

        class Menu:
            def __init__(self): self.items = []
            def append(self, item): self.items.append(item)
            def show_all(self): pass
        class MenuItem:
            def __init__(self, label): self.label = label; self.connected = None
            def connect(self, signal, callback, command): self.connected = (signal, callback, command)
        class Separator:
            label = None
        class IndicatorObject:
            def set_status(self, *_args): pass
            def connect(self, *_args): pass
            def set_menu(self, menu): self.menu = menu
            def set_secondary_activate_target(self, item): self.target = item
        class Factory:
            @staticmethod
            def new(*_args): return IndicatorObject()
        namespace = type("Indicator", (), {
            "Indicator": Factory,
            "IndicatorCategory": type("Category", (), {"APPLICATION_STATUS": 1}),
            "IndicatorStatus": type("Status", (), {"ACTIVE": 1}),
        })
        view = gui.DesktopWindow.__new__(gui.DesktopWindow)
        with patch.object(gui.Gtk, "Menu", Menu), patch.object(gui.Gtk, "MenuItem", MenuItem), patch.object(gui.Gtk, "SeparatorMenuItem", Separator):
            view._create_indicator(namespace)
        self.assertEqual([(item.label, getattr(item, "connected", None)[2] if getattr(item, "connected", None) else None) for item in view.indicator.menu.items], [
            ("Показать окно", "show"), (None, None), ("Начать", "start"),
            ("Остановить", "stop"), ("Отменить", "cancel"), ("Переключить запись", "toggle"), (None, None), ("Выйти", "quit")])

    def test_quit_dialog_uses_explicit_russian_button_labels(self):
        from giga_pisar_dictation import gui
        from giga_pisar_dictation.controller import State
        captured = {}
        class Dialog:
            def __init__(self, **kwargs): captured.update(kwargs); self.buttons = []
            def format_secondary_text(self, *_args): pass
            def add_button(self, label, response):
                self.buttons.append((label, response))
                captured["button_labels"] = [name for name, _response in self.buttons]
            def run(self): return gui.Gtk.ResponseType.CANCEL
            def destroy(self): pass
        view = gui.DesktopWindow.__new__(gui.DesktopWindow)
        view.window = object(); view.controller = type("Controller", (), {"state": State.REQUESTING})()
        view._shutdown = False; view.indicator = None; view.tray_watcher = None
        fake_type = type("Buttons", (), {"NONE": 0})
        with patch.object(gui.Gtk, "MessageDialog", Dialog), patch.object(gui.Gtk, "main_quit"):
            with patch.object(gui.Gtk, "ButtonsType", fake_type):
                self.assertFalse(view.quit())
        self.assertEqual(captured["buttons"], fake_type.NONE)
        self.assertEqual(captured["button_labels"], ["Продолжить", "Выйти"])

    def test_real_glib_errors_use_only_matching_gio_domain_and_code(self):
        domain = Gio.io_error_quark()
        cases = (
            (domain, Gio.IOErrorEnum.CANCELLED, "Операция отменена", "Запрос отменён"),
            (domain, Gio.IOErrorEnum.CANCELLED, "Operation was cancelled", "Запрос отменён"),
            (domain, Gio.IOErrorEnum.TIMED_OUT, "Истекло время ожидания", "Время ожидания запроса истекло"),
            (domain, Gio.IOErrorEnum.TIMED_OUT, "Connection timed out", "Время ожидания запроса истекло"),
        )
        for error_domain, code, message, expected in cases:
            error = GLib.Error.new_literal(error_domain, message, code)
            self.assertEqual(str(ApiClient._io_error(error)), expected)

        wrong_domain = GLib.quark_from_string("unrelated-error-domain")
        structured_errors = (
            GLib.Error.new_literal(wrong_domain, "operation cancelled", Gio.IOErrorEnum.CANCELLED),
            GLib.Error.new_literal(domain, "connection timeout detail", Gio.IOErrorEnum.FAILED),
            GLib.Error.new_literal(domain, "подробности ошибки соединения", Gio.IOErrorEnum.FAILED),
        )
        for error in structured_errors:
            self.assertEqual(str(ApiClient._io_error(error)), "Сервер недоступен")

    def test_io_error_ordinary_exception_fallback_and_cli_help_under_c_locale(self):
        self.assertEqual(str(ApiClient._io_error(Exception("operation cancelled"))), "Запрос отменён")
        self.assertEqual(str(ApiClient._io_error(Exception("unrelated failure"))), "Сервер недоступен")
        env = dict(os.environ, LANG="C", PYTHONPATH="src")
        result = subprocess.run([sys.executable, "-m", "giga_pisar_dictation", "--help"],
                                capture_output=True, text=True, env=env, check=True)
        self.assertIn("использование:", result.stdout)
        self.assertIn("позиционные аргументы:", result.stdout)
        self.assertIn("параметры:", result.stdout)
        self.assertIn("start,stop,cancel,status,toggle", result.stdout)

    def test_application_parser_errors_are_russian_under_c_locale(self):
        from giga_pisar_dictation.__main__ import main
        stderr = StringIO()
        with patch.dict(os.environ, {"LANG": "C"}), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as exit_info:
                main(["bogus", "--help"])
        self.assertEqual(exit_info.exception.code, 2)
        self.assertIn("использование:", stderr.getvalue())
        self.assertIn("ошибка:", stderr.getvalue())

    def test_build_deb_help_under_c_locale_is_russian(self):
        env = dict(os.environ, LANG="C")
        result = subprocess.run([sys.executable, "scripts/build-deb.py", "--help"],
                                capture_output=True, text=True, env=env, check=True)
        self.assertIn("использование:", result.stdout)
        self.assertIn("каталог для пакета", result.stdout)
        self.assertIn("параметры:", result.stdout)

    def test_build_deb_invalid_arguments_have_russian_usage_and_error_under_c_locale(self):
        env = dict(os.environ, LANG="C")
        result = subprocess.run([sys.executable, "scripts/build-deb.py", "--unknown"],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("использование:", result.stderr)
        self.assertIn("ошибка:", result.stderr)


if __name__ == "__main__":
    unittest.main()
