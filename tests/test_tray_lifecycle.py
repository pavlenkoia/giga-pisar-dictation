import unittest
import tempfile
from pathlib import Path
import gi
from unittest.mock import patch

from giga_pisar_dictation.config import Config
from giga_pisar_dictation.controller import State
from giga_pisar_dictation.tray import TrayPolicy, icon_for_state, requires_quit_confirmation
from giga_pisar_dictation.desktop import DesktopEffects
from giga_pisar_dictation.tray import TrayWatcher


class FakeWindow:
    def __init__(self): self.visible = False
    def show_all(self): self.visible = True
    def hide(self): self.visible = False
    def present(self): self.visible = True
    def get_visible(self): return self.visible


class FakeStatus:
    def set_text(self, text): self.text = text


class FakeEffects:
    def __init__(self, key="configured"): self.key = key; self.shutdown_calls = 0
    def shutdown(self): self.shutdown_calls += 1


class FakeDialog:
    response = 0
    def __init__(self, **_): pass
    def format_secondary_text(self, _): pass
    def add_button(self, *_): pass
    def run(self): return self.response
    def destroy(self): pass


class TrayPolicyTests(unittest.TestCase):
    def setUp(self):
        gi.require_version("Gtk", "3.0"); gi.require_version("GLib", "2.0"); gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        from giga_pisar_dictation import gui
        self.Gio, self.GLib, self.gui = Gio, GLib, gui

    def test_unknown_and_unavailable_hosts_never_allow_hiding(self):
        policy = TrayPolicy()
        self.assertFalse(policy.may_hide())
        self.assertFalse(policy.may_start_hidden())
        policy.update(False)
        self.assertFalse(policy.may_hide())
        policy.update(True)
        self.assertTrue(policy.may_hide())
        self.assertTrue(policy.may_start_hidden())

    def test_loss_restoration_and_shutdown_observer_release(self):
        policy = TrayPolicy(True)
        events = []
        policy.subscribe(events.append)
        policy.update(False)
        self.assertEqual(events, [False])
        self.assertFalse(policy.may_hide())
        policy.update(True)
        self.assertEqual(events, [False, True])
        policy.close()
        policy.update(False)
        self.assertEqual(events, [False, True])

    def test_exit_confirmation_only_for_active_operations(self):
        for state in (State.RECORDING, State.FINALIZING, State.REQUESTING):
            self.assertTrue(requires_quit_confirmation(state), state)
        for state in (State.IDLE, State.RESULT, State.ERROR):
            self.assertFalse(requires_quit_confirmation(state), state)

    def _fake_view(self):
        view = self.gui.DesktopWindow.__new__(self.gui.DesktopWindow)
        view.window = FakeWindow(); view.status = FakeStatus(); view.effects = FakeEffects()
        view.tray_policy = TrayPolicy(); view.tray_policy.subscribe(view._tray_lost); view._host_available = None
        view._launch_mode_applied = False
        view._shutdown = False; view.indicator = None; view.Indicator = None
        view.tray_watcher = None
        return view

    def test_autostart_with_unknown_host_stays_visible_even_if_host_later_appears(self):
        view = self._fake_view()
        view.indicator = type("Indicator", (), {"get_property": lambda _self, name: name == "connected"})()
        with patch.object(self.gui.GLib, "idle_add", side_effect=lambda callback: callback()):
            view.apply_launch_mode("autostart")
        self.assertTrue(view.window.visible)
        self.assertTrue(view._launch_mode_applied)
        view._tray_changed(True)
        self.assertTrue(view.window.visible, "host restoration must not hide an already shown window")

    def test_confirmed_host_and_connected_indicator_allow_autostart_hidden(self):
        view = self._fake_view()
        view.indicator = type("Indicator", (), {"get_property": lambda _self, _name: True})()
        view._tray_changed(True)
        with patch.object(self.gui.GLib, "idle_add", side_effect=lambda callback: callback()):
            view.apply_launch_mode("autostart")
        self.assertFalse(view.window.visible)

    def test_host_loss_restores_window_and_restoration_does_not_hide_it(self):
        view = self._fake_view()
        view.indicator = type("Indicator", (), {"get_property": lambda _self, _name: True})()
        view._tray_changed(True); view.window.hide()
        view._tray_changed(False)
        self.assertTrue(view.window.visible)
        view._tray_changed(True)
        self.assertTrue(view.window.visible)

    def test_first_run_autostart_fallback_opens_visible_settings(self):
        view = self._fake_view(); view.effects.key = ""
        scheduled = []
        view.settings_dialog = lambda: scheduled.append(True)
        view.indicator = type("Indicator", (), {"get_property": lambda _self, _name: True})()
        view._tray_changed(True)
        with patch.object(self.gui.GLib, "idle_add", side_effect=lambda callback: (scheduled.append("idle"), 1)[1]):
            view.apply_launch_mode("autostart")
        self.assertTrue(view.window.visible)
        self.assertEqual(scheduled, ["idle"])

    def test_first_run_opens_settings_on_idle_and_no_tray_close_keeps_window(self):
        view = self._fake_view(); view.effects.key = ""
        settings = []
        view.settings_dialog = lambda: settings.append("settings")
        with patch.object(self.gui.GLib, "idle_add", side_effect=lambda callback: (settings.append("scheduled"), 1)[1]):
            view.apply_launch_mode("ordinary")
        self.assertTrue(view.window.visible)
        self.assertEqual(settings, ["scheduled"])
        view._hide()
        self.assertTrue(view.window.visible)
        self.assertIn("Трей недоступен", view.status.text)

    def test_indicator_secondary_activation_targets_show_menu_item(self):
        created = []
        class Menu:
            def __init__(self): self.items = []
            def append(self, item): self.items.append(item)
            def show_all(self): pass
        class MenuItem:
            def __init__(self, label): self.label = label; self.handlers = []
            def connect(self, signal, callback, *args): self.handlers.append((signal, callback, args))
        class IndicatorObject:
            def __init__(self): self.handlers = []; self.menu = None; self.target = None
            def set_status(self, _status): pass
            def connect(self, signal, callback):
                if signal != "notify::connected": raise TypeError(f"unsupported signal: {signal}")
                self.handlers.append((signal, callback))
            def set_menu(self, menu): self.menu = menu
            def set_secondary_activate_target(self, item): self.target = item
        class IndicatorFactory:
            @staticmethod
            def new(*_args):
                indicator = IndicatorObject(); created.append(indicator); return indicator
        namespace = type("IndicatorNamespace", (), {
            "Indicator": IndicatorFactory,
            "IndicatorCategory": type("Category", (), {"APPLICATION_STATUS": 1}),
            "IndicatorStatus": type("Status", (), {"ACTIVE": 1}),
        })
        window = self.gui.DesktopWindow.__new__(self.gui.DesktopWindow)
        window.indicator = None
        with patch.object(self.gui.Gtk, "Menu", Menu), patch.object(self.gui.Gtk, "MenuItem", MenuItem):
            window._create_indicator(namespace)
        indicator = created[0]
        show_item = next(item for item in indicator.menu.items if item.label == "Показать окно")
        self.assertIs(indicator.target, show_item)
        self.assertIn(("activate", window._menu_action, ("show",)), show_item.handlers)
        self.assertEqual([name for name, _callback in indicator.handlers], ["notify::connected"])

    def test_default_tray_watcher_constructor_and_cleanup_use_real_gio(self):
        class Connection:
            def signal_subscribe(self, *args): self.signal_args = args; return 17
            def signal_unsubscribe(self, identifier): self.unsubscribed = identifier
        connection = Connection()
        with patch.object(self.Gio, "bus_get_sync", return_value=connection) as get_bus, \
             patch.object(self.Gio, "bus_watch_name", return_value=23) as watch_name, \
             patch.object(self.Gio, "bus_unwatch_name") as unwatch_name:
            watcher = TrayWatcher(lambda _available: None)
            get_bus.assert_called_once_with(self.Gio.BusType.SESSION, None)
            watch_name.assert_called_once()
            self.assertEqual(connection.signal_args[0:4],
                ("org.kde.StatusNotifierWatcher", "org.kde.StatusNotifierWatcher", None, "/StatusNotifierWatcher"))
            watcher.close()
            unwatch_name.assert_called_once_with(23)
            self.assertEqual(connection.unsubscribed, 17)

    def test_status_notifier_host_query_uses_real_glib_dbus_property_types(self):
        glib = self.GLib
        class Connection:
            def call_sync(self, *args):
                self.args = args
                return glib.Variant("(v)", (glib.Variant("b", True),))
        watcher = TrayWatcher.__new__(TrayWatcher)
        watcher.Gio = type("Gio", (), {"DBusCallFlags": type("Flags", (), {"NONE": 0})})
        watcher.GLib = self.GLib
        watcher.connection = Connection(); observed = []; watcher.callback = observed.append
        watcher._query()
        args = watcher.connection.args
        self.assertEqual(args[2:4], ("org.freedesktop.DBus.Properties", "Get"))
        self.assertEqual(args[4].get_type_string(), "(ss)")
        self.assertEqual(args[4].unpack(), ("org.kde.StatusNotifierWatcher", "IsStatusNotifierHostRegistered"))
        self.assertEqual(args[5].dup_string(), "(v)")
        self.assertEqual(observed, [True])

    def test_wayland_limitation_is_visible_with_shortcut_enabled_or_disabled(self):
        class View:
            def __init__(self): self.status = FakeStatus(); self.shortcut_status = FakeStatus(); self.controller = type("Controller", (), {"state": State.IDLE})()
            def refresh(self): pass
        class Clipboard:
            def shutdown(self): pass
        with tempfile.TemporaryDirectory() as temp, patch.dict("os.environ", {"XDG_SESSION_TYPE": "wayland"}):
            for enabled in (True, False):
                effects = DesktopEffects(View(), config=Config(hotkey_enabled=enabled), key="", audio_directory=Path(temp),
                    clipboard=Clipboard(), x11_factory=lambda: self.fail("must not open X11"))
                self.assertIsNone(effects.x11)
                self.assertIn("сеанс X11 недоступен", effects.view.status.text)
                effects.shutdown()

    def test_no_x11_shortcuts_are_not_registered(self):
        effects = DesktopEffects.__new__(DesktopEffects)
        effects.config = type("Config", (), {"hotkey_enabled": True})()
        effects.x11 = None; effects.hotkey_factory = lambda *_args, **_kwargs: self.fail("hotkey attempted without X11")
        effects._register_hotkey()
        self.assertFalse(effects.shortcut_healthy)
        self.assertIsNone(effects.hotkey)
        self.assertIn("требуется сеанс X11", effects.shortcut_status)

    def test_quit_refusal_preserves_work_and_confirmed_quit_shuts_down_once(self):
        for state in (State.RECORDING, State.FINALIZING, State.REQUESTING):
            view = self._fake_view()
            view.controller = type("Controller", (), {"state": state})()
            FakeDialog.response = self.gui.Gtk.ResponseType.CANCEL
            with patch.object(self.gui.Gtk, "MessageDialog", FakeDialog), patch.object(self.gui.Gtk, "main_quit") as quit_loop:
                self.assertFalse(view.quit())
                self.assertEqual(view.effects.shutdown_calls, 0)
                quit_loop.assert_not_called()
            FakeDialog.response = self.gui.Gtk.ResponseType.OK
            with patch.object(self.gui.Gtk, "MessageDialog", FakeDialog), patch.object(self.gui.Gtk, "main_quit"):
                self.assertTrue(view.quit())
                self.assertTrue(view.quit())
            self.assertEqual(view.effects.shutdown_calls, 1)
        FakeDialog.response = self.gui.Gtk.ResponseType.CANCEL

    def test_each_controller_state_has_safe_generic_icon(self):
        expected = {
            State.IDLE: "giga-pisar-dictation-idle",
            State.RESULT: "giga-pisar-dictation-idle",
            State.RECORDING: "giga-pisar-dictation-recording",
            State.FINALIZING: "giga-pisar-dictation-processing",
            State.REQUESTING: "giga-pisar-dictation-processing",
            State.ERROR: "giga-pisar-dictation-error",
        }
        for state, icon in expected.items():
            with self.subTest(state=state):
                self.assertEqual(icon_for_state(state), icon)
                self.assertNotIn("transcript", icon)


if __name__ == "__main__":
    unittest.main()
