import unittest
from types import SimpleNamespace
from unittest.mock import patch

from giga_pisar_dictation.audio_devices import list_audio_sources


class Device:
    def __init__(self, pulse_id, name, device_class="sound", properties=True):
        self.pulse_id = pulse_id; self.name = name; self.device_class = device_class; self.properties = properties
    def get_properties(self):
        return Structure(device_class=self.device_class) if self.properties else None
    def get_display_name(self): return self.name
    def create_element(self, _name): return SourceElement(self.pulse_id)


class Structure:
    def __init__(self, **values): self.values = values
    def get_string(self, key): return self.values.get(key.replace(".", "_"))


class SourceElement:
    def __init__(self, device_id): self.device_id = device_id
    def get_factory(self): return SimpleNamespace(get_name=lambda: "pulsesrc")
    def get_property(self, key): return self.device_id if key == "device" else None


class Monitor:
    def __init__(self, devices, starts=True): self.devices = devices; self.starts = starts; self.stopped = False; self.filters = []
    def add_filter(self, *args): self.filters.append(args)
    def start(self): return self.starts
    def get_devices(self): return self.devices
    def stop(self): self.stopped = True


def fake_gst(monitor):
    class Caps:
        @staticmethod
        def from_string(value): return value
    return SimpleNamespace(DeviceMonitor=SimpleNamespace(new=lambda: monitor), Caps=Caps)


class AudioDeviceTests(unittest.TestCase):
    def test_device_ids_and_duplicate_labels_are_preserved_and_disambiguated(self):
        monitor = Monitor([Device("alsa_input.one", "Microphone"), Device("alsa_input.two", "Microphone")])
        result = list_audio_sources(fake_gst(monitor))
        self.assertEqual(result, [("alsa_input.one", "Microphone (alsa_input.one)"), ("alsa_input.two", "Microphone (alsa_input.two)")])
        self.assertTrue(monitor.stopped)
        self.assertEqual(monitor.filters, [("Audio/Source", "audio/x-raw")])

    def test_real_gst_caps_filter_contract_offline_without_starting_monitor(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        monitor = Gst.DeviceMonitor.new()
        from giga_pisar_dictation.audio_devices import _add_audio_source_filter
        _add_audio_source_filter(Gst, monitor)
        self.assertIsInstance(Gst.Caps.from_string("audio/x-raw"), Gst.Caps)
        monitor = None

    def test_real_gst_structure_get_string_contract_offline(self):
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        structure = Gst.Structure.new_empty("device")
        structure.set_value("device.class", "sound")
        self.assertIsNone(structure.get_string("device"))
        self.assertEqual(structure.get_string("device.class"), "sound")
        self.assertEqual(list_audio_sources(fake_gst(Monitor([Device("alsa_input.example", "Microphone")])),),
                         [("alsa_input.example", "Microphone")])

    def test_monitor_sources_incompatible_elements_and_duplicate_ids_are_excluded(self):
        monitor_source = Device("monitor-id", "Monitor", "monitor")
        incompatible = Device("alsa_input.bad", "Other")
        incompatible.create_element = lambda _name: SimpleNamespace(get_factory=lambda: SimpleNamespace(get_name=lambda: "alsasrc"), get_property=lambda _key: "alsa_input.bad")
        duplicate = Device("alsa_input.good", "Duplicate")
        monitor = Monitor([monitor_source, incompatible, Device("alsa_input.good", "Good"), duplicate])
        self.assertEqual(list_audio_sources(fake_gst(monitor)), [("alsa_input.good", "Good")])
        self.assertTrue(monitor.stopped)

    def test_missing_pulsesrc_device_property_is_not_offered(self):
        device = Device(None, "No identifier", properties=False)
        monitor = Monitor([device])
        self.assertEqual(list_audio_sources(fake_gst(monitor)), [])
        self.assertTrue(monitor.stopped)

    def test_monitor_start_failure_is_reported_without_capture(self):
        monitor = Monitor([], starts=False)
        with self.assertRaisesRegex(RuntimeError, "перечислить"):
            list_audio_sources(fake_gst(monitor))
        self.assertFalse(monitor.stopped)

    def test_settings_selector_saves_selection_and_retains_unknown_on_failure(self):
        from giga_pisar_dictation import gui

        class FakeWidget:
            def __init__(self, *args, **kwargs): self.text = kwargs.get("label", ""); self.active = False; self.value = 120; self.items = []
            def set_text(self, value): self.text = value
            def get_text(self): return self.text
            def append(self, item_id, label): self.items.append((item_id, label))
            def set_active_id(self, item_id): self.active_id = item_id if any(i == item_id for i, _ in self.items) else None
            def get_active_id(self): return getattr(self, "active_id", None)
            def set_visibility(self, *_): pass
            def set_placeholder_text(self, *_): pass
            def set_active(self, value): self.active = value
            def get_active(self): return self.active
            def set_sensitive(self, *_): pass
            def set_value(self, value): self.value = value
            def get_value_as_int(self): return int(self.value)
            def attach(self, *_): pass
            def add(self, *_): pass
            def show_all(self): pass
            def destroy(self): pass
        class FakeSettingsDialog(FakeWidget):
            response = 1
            def __init__(self, **kwargs): super().__init__(**kwargs); self.content = FakeWidget(); self.buttons = []
            def add_button(self, *args): self.buttons.append(args)
            def get_content_area(self): return self.content
            def run(self): return self.response
        class Config:
            base_url = "http://example.invalid"; timeout_seconds = 120; audio_source = "saved-id"; auto_insert = True
            hotkey_enabled = False; hotkey_accelerator = "Ctrl+Space"
        class Effects:
            config = Config(); key = ""; shortcut_status = "test"
            def __init__(self): self.saved = []
            autostart = SimpleNamespace(is_enabled=lambda: False)
            def save_settings(self, *args, **kwargs): self.saved.append((args, kwargs))
        class FakeComboBox(FakeWidget):
            instances = []
            def __init__(self, *args, **kwargs): super().__init__(*args, **kwargs); self.instances.append(self)
        GtkFake = type("GtkFake", (), {"Dialog": FakeSettingsDialog, "Grid": FakeWidget, "Label": FakeWidget,
            "Entry": FakeWidget, "ComboBoxText": FakeComboBox,
            "SpinButton": SimpleNamespace(new_with_range=lambda *_: FakeWidget()), "CheckButton": FakeWidget,
            "ResponseType": SimpleNamespace(CANCEL=0, OK=1)})
        cases = [
            ("default", "", [("compatible-id", "Microphone")], ""),
            ("changed", "saved-id", [("compatible-id", "Microphone")], "compatible-id"),
            ("missing", "saved-id", [("compatible-id", "Microphone")], "saved-id"),
        ]
        for case, initial, available, expected in cases:
            Effects.config.audio_source = initial
            FakeSettingsDialog.response = 1
            effects = Effects(); view = gui.DesktopWindow.__new__(gui.DesktopWindow)
            view.effects = effects; view.window = object(); view.status = FakeWidget()
            if case == "changed":
                original_run = FakeSettingsDialog.run
                def choose_other(dialog):
                    FakeComboBox.instances[-1].set_active_id("compatible-id")
                    return original_run(dialog)
                FakeSettingsDialog.run = choose_other
            try:
                with patch.object(gui, "Gtk", GtkFake), patch.object(gui, "list_audio_sources", return_value=available):
                    view.settings_dialog()
            finally:
                FakeSettingsDialog.run = lambda _dialog: 1
            self.assertEqual(effects.saved[0][0][2], expected, case)
        Effects.config.audio_source = "saved-id"
        FakeSettingsDialog.response = 1; effects = Effects(); view = gui.DesktopWindow.__new__(gui.DesktopWindow)
        view.effects = effects; view.window = object(); view.status = FakeWidget()
        with patch.object(gui, "Gtk", GtkFake), patch.object(gui, "list_audio_sources", side_effect=RuntimeError("offline")):
            view.settings_dialog()
        self.assertEqual(effects.saved[0][0][2], "saved-id")

    def test_settings_reenumerates_each_opening(self):
        from giga_pisar_dictation import gui

        class FakeWidget:
            def __init__(self, *args, **kwargs): self.text = kwargs.get("label", ""); self.active = False; self.value = 120; self.items = []
            def set_text(self, value): self.text = value
            def get_text(self): return self.text
            def append(self, item_id, label): self.items.append((item_id, label))
            def set_active_id(self, item_id): self.active_id = item_id if any(i == item_id for i, _ in self.items) else None
            def get_active_id(self): return getattr(self, "active_id", None)
            def set_visibility(self, *_): pass
            def set_placeholder_text(self, *_): pass
            def set_active(self, value): self.active = value
            def get_active(self): return self.active
            def set_sensitive(self, *_): pass
            def set_value(self, value): self.value = value
            def get_value_as_int(self): return int(self.value)
            def attach(self, *_): pass
            def add(self, *_): pass
            def show_all(self): pass
            def destroy(self): pass
        class FakeSettingsDialog(FakeWidget):
            response = 1
            def __init__(self, **kwargs): super().__init__(**kwargs); self.content = FakeWidget()
            def add_button(self, *_): pass
            def get_content_area(self): return self.content
            def run(self): return self.response
        class Effects:
            config = SimpleNamespace(base_url="http://example.invalid", timeout_seconds=120, audio_source="", auto_insert=True, hotkey_enabled=False, hotkey_accelerator="Ctrl+Space")
            key = ""; shortcut_status = "test"; autostart = SimpleNamespace(is_enabled=lambda: False)
            def save_settings(self, *_args, **_kwargs): pass
        class GtkFake:
            Dialog = FakeSettingsDialog; Grid = FakeWidget; Label = FakeWidget; Entry = FakeWidget; ComboBoxText = FakeWidget
            SpinButton = SimpleNamespace(new_with_range=lambda *_: FakeWidget()); CheckButton = FakeWidget
            ResponseType = SimpleNamespace(CANCEL=0, OK=1)
        effects = Effects(); view = gui.DesktopWindow.__new__(gui.DesktopWindow)
        view.effects = effects; view.window = object(); view.status = FakeWidget()
        with patch.object(gui, "Gtk", GtkFake), patch.object(gui, "list_audio_sources", return_value=[]) as enumerate_sources:
            view.settings_dialog(); view.settings_dialog()
        self.assertEqual(enumerate_sources.call_count, 2)
