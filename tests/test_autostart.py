import os
import stat
import tempfile
import unittest
from pathlib import Path

from giga_pisar_dictation.autostart import AutostartFile, DESKTOP_CONTENT, LEGACY_DESKTOP_CONTENT
from giga_pisar_dictation.config import Config
from giga_pisar_dictation.desktop import DesktopEffects


class Label:
    def set_text(self, _text): pass


class View:
    def __init__(self): self.status = Label(); self.shortcut_status = Label()


class FakeAutostart:
    def __init__(self): self.enabled = False; self.calls = []
    def is_enabled(self): return self.enabled
    def set_enabled(self, enabled): self.calls.append(bool(enabled)); self.enabled = bool(enabled)


class FakeX11:
    def close(self): pass


class FakeWidget:
    def __init__(self, *args, **kwargs): self.text = kwargs.get("label", ""); self.active = False; self.value = 120; self.sensitive = True
    def set_text(self, value): self.text = value
    def get_text(self): return self.text
    def append(self, item_id, label):
        if not hasattr(self, "items"): self.items = []
        self.items.append((item_id, label))
    def set_active_id(self, item_id):
        self.active_id = item_id if any(entry_id == item_id for entry_id, _ in getattr(self, "items", [])) else None
    def get_active_id(self): return getattr(self, "active_id", None)
    def set_visibility(self, _value): pass
    def set_placeholder_text(self, _value): pass
    def set_active(self, value): self.active = value
    def get_active(self): return self.active
    def set_sensitive(self, value): self.sensitive = value
    def set_value(self, value): self.value = value
    def get_value_as_int(self): return int(self.value)
    def attach(self, *_args): pass
    def add(self, _widget): pass
    def show_all(self): pass
    def destroy(self): pass


class FakeSettingsDialog(FakeWidget):
    response = 1
    instances = []
    def __init__(self, **kwargs):
        super().__init__(**kwargs); self.content = FakeWidget(); self.buttons = []; self.instances.append(self)
    def add_button(self, label, response): self.buttons.append((label, response))
    def get_content_area(self): return self.content
    def run(self): return self.response


class SettingsDialogFallbackTests(unittest.TestCase):
    def test_unavailable_autostart_still_saves_other_settings_without_autostart_access(self):
        from unittest.mock import patch
        from giga_pisar_dictation import gui
        class Config:
            base_url = "http://example.invalid"; timeout_seconds = 120; audio_source = ""; auto_insert = True
            hotkey_enabled = False; hotkey_accelerator = "Ctrl+Space"
        class Autostart:
            def __init__(self, error): self.error = error; self.calls = 0
            def is_enabled(self): self.calls += 1; raise self.error
        class Effects:
            config = Config(); key = ""; shortcut_status = "Unavailable"
            def __init__(self, error): self.autostart = Autostart(error); self.saved = []
            def save_settings(self, *args, **kwargs): self.saved.append((args, kwargs))
        class Grid(FakeWidget): pass
        class GtkFake:
            Dialog = FakeSettingsDialog; Label = FakeWidget; Entry = FakeWidget; ComboBoxText = FakeWidget
            SpinButton = type("Spin", (), {"new_with_range": staticmethod(lambda *_: FakeWidget())})
            CheckButton = FakeWidget
            ResponseType = type("Response", (), {"CANCEL": 0, "OK": 1})
        GtkFake.Grid = FakeWidget
        for error in (PermissionError("unsafe directory"), OSError("unsafe entry")):
            FakeSettingsDialog.instances.clear(); FakeSettingsDialog.response = 1
            effects = Effects(error)
            view = gui.DesktopWindow.__new__(gui.DesktopWindow)
            view.effects = effects; view.window = object(); view.status = FakeWidget()
            with patch.object(gui, "Gtk", GtkFake), patch.object(gui, "list_audio_sources", return_value=[]):
                view.settings_dialog()
            self.assertEqual(FakeSettingsDialog.instances[-1].buttons[:2], [("Отменить", 0), ("Сохранить", 1)])
            self.assertEqual(effects.autostart.calls, 1)
            self.assertEqual(len(effects.saved), 1)
            self.assertIsNone(effects.saved[0][1]["autostart_enabled"])

    def test_cancel_does_not_save_settings_when_autostart_unavailable(self):
        from unittest.mock import patch
        from giga_pisar_dictation import gui
        class Config:
            base_url = "http://example.invalid"; timeout_seconds = 120; audio_source = ""; auto_insert = True
            hotkey_enabled = False; hotkey_accelerator = "Ctrl+Space"
        class Effects:
            config = Config(); key = ""; shortcut_status = "Unavailable"
            autostart = type("Unsafe", (), {"is_enabled": lambda _self: (_ for _ in ()).throw(PermissionError("unsafe"))})()
            def __init__(self): self.saved = []
            def save_settings(self, *args, **kwargs): self.saved.append((args, kwargs))
        class GtkFake:
            Dialog = FakeSettingsDialog; Grid = FakeWidget; Label = FakeWidget; Entry = FakeWidget; ComboBoxText = FakeWidget
            SpinButton = type("Spin", (), {"new_with_range": staticmethod(lambda *_: FakeWidget())})
            CheckButton = FakeWidget; ResponseType = type("Response", (), {"CANCEL": 0, "OK": 1})
        FakeSettingsDialog.response = 0
        view = gui.DesktopWindow.__new__(gui.DesktopWindow); view.effects = Effects(); view.window = object(); view.status = FakeWidget()
        with patch.object(gui, "Gtk", GtkFake), patch.object(gui, "list_audio_sources", return_value=[]): view.settings_dialog()
        self.assertEqual(view.effects.saved, [])


class AutostartFileTests(unittest.TestCase):
    def test_default_disabled_does_not_create_entry_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            config_home = Path(temp) / "config"
            config_home.mkdir()
            store = AutostartFile(config_home)
            self.assertFalse(store.is_enabled())
            self.assertFalse(store.directory.exists())

    def test_enable_disable_repeat_and_preserve_directory_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            config_home = Path(temp) / "config"
            config_home.mkdir()
            directory = config_home / "autostart"
            directory.mkdir(mode=0o750)
            original_mode = stat.S_IMODE(directory.stat().st_mode)
            store = AutostartFile(config_home)
            self.assertFalse(store.is_enabled())
            store.set_enabled(True)
            entry = directory / "org.gigapisar.Dictation.desktop"
            self.assertTrue(store.is_enabled())
            self.assertEqual(entry.read_bytes(), DESKTOP_CONTENT)
            self.assertEqual(stat.S_IMODE(entry.stat().st_mode), 0o644)
            store.set_enabled(True)
            self.assertEqual(entry.read_bytes(), DESKTOP_CONTENT)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), original_mode)
            store.set_enabled(False)
            self.assertFalse(store.is_enabled())
            self.assertFalse(entry.exists())
            store.set_enabled(False)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), original_mode)

    def test_legacy_and_current_exact_entries_are_recognized_without_read_migration(self):
        with tempfile.TemporaryDirectory() as temp:
            config_home = Path(temp) / "config"; config_home.mkdir()
            directory = config_home / "autostart"; directory.mkdir(mode=0o700)
            entry = directory / "org.gigapisar.Dictation.desktop"
            store = AutostartFile(config_home)
            for content in (LEGACY_DESKTOP_CONTENT, DESKTOP_CONTENT):
                entry.write_bytes(content)
                entry.chmod(0o644)
                self.assertTrue(store.is_enabled())
                self.assertEqual(entry.read_bytes(), content)
                store.set_enabled(True)
                self.assertEqual(entry.read_bytes(), content)
            entry.write_bytes(LEGACY_DESKTOP_CONTENT)
            entry.chmod(0o644)
            store.set_enabled(False)
            self.assertFalse(entry.exists())

    def test_foreign_file_symlink_and_unsafe_directory_are_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            config_home = Path(temp) / "config"
            config_home.mkdir()
            directory = config_home / "autostart"
            directory.mkdir()
            entry = directory / "org.gigapisar.Dictation.desktop"
            entry.write_text("[Desktop Entry]\nName=foreign\n")
            store = AutostartFile(config_home)
            with self.assertRaises(PermissionError): store.is_enabled()
            with self.assertRaises(PermissionError): store.set_enabled(False)
            self.assertIn("foreign", entry.read_text())
            entry.unlink()
            foreign = directory / "foreign.desktop"
            foreign.write_text("keep")
            entry.symlink_to(foreign)
            with self.assertRaises(OSError): store.is_enabled()
            with self.assertRaises(OSError): store.set_enabled(True)
            self.assertEqual(foreign.read_text(), "keep")

    def test_fifo_and_oversized_entries_are_rejected_without_blocking_or_unbounded_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            config_home = Path(temp) / "config"; config_home.mkdir()
            directory = config_home / "autostart"; directory.mkdir()
            entry = directory / "org.gigapisar.Dictation.desktop"
            store = AutostartFile(config_home)
            os.mkfifo(entry)
            with self.assertRaises(PermissionError): store.is_enabled()
            entry.unlink()
            entry.write_bytes(b"x" * (len(DESKTOP_CONTENT) + 10000))
            with self.assertRaises(PermissionError): store.is_enabled()

    def test_config_failure_rolls_back_autostart_and_does_not_silently_succeed(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeAutostart()
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=False), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store,
                config_saver=lambda _config: (_ for _ in ()).throw(OSError("fake config failure")))
            with self.assertRaises(OSError):
                effects.save_settings(Config().base_url, 120, "", "", True, False, "Ctrl+Space", autostart_enabled=True)
            self.assertEqual(store.calls, [True, False])
            self.assertFalse(store.enabled)

    def test_disabling_enabled_entry_rolls_back_after_config_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeAutostart(); store.enabled = True
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=False), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store,
                config_saver=lambda _config: (_ for _ in ()).throw(OSError("config failure")))
            with self.assertRaises(OSError):
                effects.save_settings(Config().base_url, 120, "", "", True, False, "Ctrl+Space", autostart_enabled=False)
            self.assertEqual(store.calls, [False, True])
            self.assertTrue(store.enabled)

    def test_key_write_failure_rolls_back_autostart_before_config_write(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeAutostart(); config_writes = []
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=False), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store,
                config_saver=lambda config: config_writes.append(config),
                key_saver=lambda _key: (_ for _ in ()).throw(OSError("key failure")))
            with self.assertRaises(OSError):
                effects.save_settings(Config().base_url, 120, "", "fictional-test-key", True, False, "Ctrl+Space", autostart_enabled=True)
            self.assertEqual(store.calls, [True, False])
            self.assertFalse(store.enabled)
            self.assertEqual(config_writes, [])

    def test_autostart_rollback_failure_still_rolls_back_old_hotkey(self):
        class Hotkey:
            healthy = True
            def __init__(self): self.events = []
            def prepare_rebind(self, _accelerator): self.events.append("prepare"); return True
            def rollback_rebind(self): self.events.append("rollback")
        class FailingRollback(FakeAutostart):
            def set_enabled(self, enabled):
                self.calls.append(bool(enabled))
                if not enabled: raise OSError("rollback failed")
                self.enabled = True
        with tempfile.TemporaryDirectory() as temp:
            store = FailingRollback(); hotkey = Hotkey()
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=True), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store, hotkey_factory=lambda *_args, **_kwargs: hotkey,
                config_saver=lambda _config: (_ for _ in ()).throw(OSError("config failure")))
            with self.assertRaises(RuntimeError):
                effects.save_settings(Config().base_url, 120, "", "", True, True, "Ctrl+Alt+Space", autostart_enabled=True)
            self.assertEqual(hotkey.events, ["prepare", "rollback"])
            self.assertEqual(store.calls, [True, False])

    def test_autostart_rollback_failure_still_closes_new_hotkey_registration(self):
        class Registration:
            healthy = True
            def __init__(self): self.closed = False
            def close(self): self.closed = True
        class FailingRollback(FakeAutostart):
            def set_enabled(self, enabled):
                self.calls.append(bool(enabled))
                if not enabled: raise OSError("rollback failed")
                self.enabled = True
        with tempfile.TemporaryDirectory() as temp:
            store = FailingRollback(); registration = Registration()
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=False), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store,
                hotkey_factory=lambda *_args, **_kwargs: registration,
                config_saver=lambda _config: (_ for _ in ()).throw(OSError("config failure")))
            with self.assertRaises(RuntimeError):
                effects.save_settings(Config().base_url, 120, "", "", True, True, "Ctrl+Space", autostart_enabled=True)
            self.assertTrue(registration.closed)

    def test_autostart_write_failure_prevents_other_settings_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            store = FakeAutostart()
            def fail_enable(_enabled): raise PermissionError("unsafe entry")
            store.set_enabled = fail_enable
            writes = []
            effects = DesktopEffects(View(), config=Config(hotkey_enabled=False), key="", client=object(),
                audio_directory=Path(temp), clipboard=type("Clipboard", (), {"shutdown": lambda _self: None})(),
                x11_factory=FakeX11, autostart_store=store,
                config_saver=lambda config: writes.append("config"), key_saver=lambda key: writes.append("key"))
            with self.assertRaises(PermissionError):
                effects.save_settings(Config().base_url, 120, "", "", True, False, "Ctrl+Space", autostart_enabled=True)
            self.assertEqual(writes, [])


if __name__ == "__main__": unittest.main()
