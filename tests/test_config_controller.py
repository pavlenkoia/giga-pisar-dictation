import os
import stat
import tempfile
import unittest
from pathlib import Path

from giga_pisar_dictation.config import Config, load_api_key, load_config, save_api_key, save_config
from giga_pisar_dictation.controller import Controller, State


class FakeEffects:
    def __init__(self): self.calls = []; self.fail = None
    def _call(self, name):
        self.calls.append(name)
        if self.fail == name: raise RuntimeError("private detail")
    def start_recording(self): self._call("start")
    def finalize_recording(self): self._call("finalize")
    def cancel_recording(self): self._call("cancel-recording")
    def submit_audio(self): self._call("submit")
    def cancel_request(self): self._call("cancel-request")
    def remove_audio(self): self._call("remove")


class ConfigTests(unittest.TestCase):
    def test_private_atomic_config_and_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "cfg"
            save_config(Config(), d); save_api_key("fictional-test-key", d)
            self.assertEqual(stat.S_IMODE((d / "config.json").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((d / "api-key").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)
            self.assertEqual(load_config(d), Config())
            self.assertEqual(load_api_key(d), "fictional-test-key")
            self.assertNotIn("api_key", (d / "config.json").read_text())

    def test_legacy_config_defaults_shortcut_fields_and_invalid_shortcuts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)/"cfg"; d.mkdir(mode=0o700)
            (d/"config.json").write_text('{"base_url":"http://192.168.0.30:8737","timeout_seconds":120,"audio_source":"","auto_insert":true}')
            os.chmod(d/"config.json",0o600)
            legacy=load_config(d)
            self.assertTrue(legacy.hotkey_enabled); self.assertEqual(legacy.hotkey_accelerator,"Ctrl+Space")
            self.assertEqual(legacy.hotkey_mode,"toggle")
            with self.assertRaises(ValueError):Config(hotkey_accelerator=42).validate()
            with self.assertRaises(ValueError):Config(hotkey_accelerator="Space").validate()
            with self.assertRaises(ValueError):Config(hotkey_mode="unknown").validate()
            ptt=Config(hotkey_mode="push_to_talk",hotkey_accelerator="Ctrl+a")
            ptt.validate(); self.assertEqual(ptt.hotkey_accelerator,"Ctrl+a")

    def test_rejects_permissions_symlinks_unsafe_parent_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "cfg"; save_api_key("fictional-test-key", d)
            os.chmod(d / "api-key", 0o644)
            with self.assertRaises(PermissionError): load_api_key(d)
            with self.assertRaises(PermissionError): save_api_key("replacement", d)
            os.chmod(d / "api-key", 0o600); os.chmod(d, 0o755)
            with self.assertRaises(PermissionError): load_config(d)
            for url in ("https://user:pass@example.test", "file:///tmp/x", "http://host/a?x=1"):
                with self.assertRaises(ValueError): Config(base_url=url).validate()
            os.chmod(d, 0o700); (d / "api-key").unlink()
            (d / "api-key").symlink_to(Path(tmp) / "missing")
            with self.assertRaises(OSError): load_api_key(d)
            (d / "api-key").unlink()
            parent = Path(tmp) / "alias"; parent.symlink_to(d, target_is_directory=True)
            with self.assertRaises(OSError): load_api_key(parent)


class ControllerTests(unittest.TestCase):
    def test_busy_flow_late_response_after_cancel(self):
        fx = FakeEffects(); c = Controller(fx)
        self.assertFalse(c.stop()); self.assertFalse(c.cancel())
        self.assertTrue(c.start()); self.assertFalse(c.start()); self.assertTrue(c.stop())
        self.assertTrue(c.audio_finalized(True)); generation = c._request_generation
        self.assertFalse(c.start()); self.assertFalse(c.stop()); self.assertTrue(c.cancel())
        self.assertFalse(c.response("private transcript", generation))
        self.assertIsNone(c.text); self.assertEqual(c.state, State.IDLE)

    def test_empty_audio_result_failure_and_callbacks_in_wrong_states(self):
        fx = FakeEffects(); c = Controller(fx)
        self.assertFalse(c.response("late")); self.assertFalse(c.audio_finalized(True))
        self.assertTrue(c.start()); self.assertFalse(c.response("late")); c.stop()
        self.assertFalse(c.audio_finalized(False)); self.assertEqual(c.state, State.ERROR)
        self.assertTrue(c.start()); c.stop(); c.audio_finalized(True)
        self.assertFalse(c.audio_finalized(True)); self.assertFalse(c.response("  "))
        self.assertEqual(c.state, State.ERROR); self.assertNotIn("private detail", c.message)

    def test_effect_failures_are_sanitized(self):
        fx = FakeEffects(); fx.fail = "start"; c = Controller(fx)
        self.assertFalse(c.start()); self.assertNotIn("private detail", c.message)
        fx.fail = None; c.start(); fx.fail = "finalize"
        self.assertFalse(c.stop()); self.assertNotIn("private detail", c.message)
        fx.fail = None; c.start(); c.stop(); fx.fail = "submit"
        self.assertFalse(c.audio_finalized(True)); self.assertEqual(c.state, State.ERROR)
        self.assertNotIn("private detail", c.message)


if __name__ == "__main__": unittest.main()
