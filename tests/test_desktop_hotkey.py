import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from giga_pisar_dictation.config import Config
from giga_pisar_dictation.desktop import DesktopEffects
from giga_pisar_dictation.controller import Controller, State
from giga_pisar_dictation.hotkey import X11Hotkey
from tests.test_hotkey import FakeBackend, FakeGLib


class Label:
    def set_text(self,text): self.text=text
class View:
    def __init__(self): self.status=Label(); self.shortcut_status=Label(); self.external_window=41
    def refresh(self): pass
class FakeX:
    def active_window(self): return 91
    def close(self): pass
class Clipboard:
    def shutdown(self): pass
class Hotkey:
    def __init__(self, accelerator="Ctrl+Space", fail=None): self.accelerator=accelerator; self.fail=fail; self.closed=False; self.rebinds=[]
    def prepare_rebind(self,value):
        self.rebinds.append(value)
        if self.fail==value: raise RuntimeError("conflict")
        if value==self.accelerator:return False
        self.prepared=value; return True
    def commit_rebind(self): self.accelerator=self.prepared; del self.prepared
    def rollback_rebind(self):
        if hasattr(self,"prepared"):del self.prepared
    def rebind(self,value):
        changed=self.prepare_rebind(value)
        if changed:self.commit_rebind()
        return changed
    def close(self):self.closed=True

class DesktopSettingsTests(unittest.TestCase):
    def make(self,config=None,hotkey=None,saver=None):
        effects=DesktopEffects.__new__(DesktopEffects)
        effects.config=config or Config(); effects.hotkey=hotkey; effects.hotkey_factory=None
        effects.shortcut_healthy=getattr(hotkey,"healthy",bool(hotkey))
        effects.config_saver=saver or (lambda cfg:None); effects.key_saver=lambda key:None
        effects.view=View(); effects.x11=FakeX(); effects.glib=object(); effects.shortcut_status="old"
        effects.monotonic_clock_ns=lambda:10_000_000_000
        effects.client=None; effects.key=""
        return effects
    @patch("giga_pisar_dictation.desktop.load_api_key",return_value="")
    def test_ptt_mode_switch_commits_and_failed_save_rolls_back_actual_binding(self,_):
        class GLib:
            IO_IN=1; PRIORITY_DEFAULT=0
            def io_add_watch(self,*args):return 1
            def timeout_add(self,*args):return 2
            def source_remove(self,*args):pass
        backend=FakeBackend(); glib=GLib()
        hotkey=X11Hotkey("Ctrl+Space",lambda *_:None,glib=glib,backend=backend)
        effects=self.make(config=Config(),hotkey=hotkey); effects.glib=glib
        effects.view.controller=type("Controller",(),{"state":State.IDLE})()
        effects.config_saver=lambda _config:None
        effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space",hotkey_mode="push_to_talk")
        self.assertEqual(hotkey.mode,"push_to_talk")
        self.assertEqual(backend.grabs,{(105,mask) for mask in range(256)})
        effects.config_saver=lambda _config:(_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):
            effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space",hotkey_mode="toggle")
        self.assertEqual(effects.config.hotkey_mode,"push_to_talk")
        self.assertEqual(hotkey.mode,"push_to_talk")
        self.assertEqual(backend.grabs,{(105,mask) for mask in range(256)})
        effects.config_saver=lambda _config:None
        effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space",hotkey_mode="toggle")
        self.assertEqual(effects.config.hotkey_mode,"toggle")
        self.assertEqual(backend.grabs,{(65,mask) for mask in (4,6,20,22)})
        hotkey.close()

    @patch("giga_pisar_dictation.desktop.load_api_key",return_value="")
    def test_successful_rebind_disable_enable_and_same_binding(self,_):
        old=Hotkey(); e=self.make(hotkey=old)
        e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space")
        self.assertEqual(old.rebinds,[])
        e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a")
        self.assertEqual(old.accelerator,"Ctrl+a"); self.assertEqual(e.config.hotkey_accelerator,"Ctrl+a")
        e.save_settings(Config().base_url,120,"","",True,False,"Ctrl+a")
        self.assertTrue(old.closed); self.assertIsNone(e.hotkey)
        e.hotkey_factory=lambda accelerator,*args,**kwargs:Hotkey(accelerator)
        e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a")
        self.assertEqual(e.hotkey.accelerator,"Ctrl+a")
    @patch("giga_pisar_dictation.desktop.load_api_key",return_value="")
    def test_save_failure_and_commit_preserve_overlapping_physical_grabs(self,_):
        class GLib:
            IO_IN=1; PRIORITY_DEFAULT=0
            def io_add_watch(self,*args):return 1
            def timeout_add(self,*args):return 2
            def source_remove(self,*args):pass
        class Backend:
            def __init__(self):self.grabs=set();self.masks=(0,2,16,18);self.mapping={ord("1"):65,ord("!"):65}
            def keycode(self,sym):return self.mapping.get(sym,65 if sym==32 else 0)
            def modifier_mask(self,names):return 4
            def lock_masks(self):return self.masks
            def active_window(self):return 73
            def grab_entries(self,entries):self.grabs.update(entries)
            def ungrab_entries(self,entries):self.grabs.difference_update(entries)
            def sync(self):pass
            def pending(self):return False
            def select_mapping(self):pass
            def fd(self):return 9
            def close(self):pass
        backend=Backend(); hotkey=X11Hotkey("Ctrl+1",lambda *_:None,glib=GLib(),backend=backend)
        original=backend.grabs.copy(); e=self.make(config=Config(hotkey_accelerator="Ctrl+1"),hotkey=hotkey)
        e.glib=GLib()
        backend.masks=(0,2,32,34)
        e.config_saver=lambda _config:(_ for _ in ()).throw(OSError("disk full"))
        with self.assertRaises(OSError):e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+!")
        self.assertEqual(backend.grabs,original); self.assertEqual(hotkey.accelerator,"Ctrl+1")
        e.config_saver=lambda _config:None
        e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+!")
        self.assertEqual(backend.grabs,{(65,4),(65,6),(65,36),(65,38)})
        self.assertEqual(hotkey.accelerator,"Ctrl+!")
        hotkey.close()

    def test_prepare_conflict_and_save_rollback_clear_old_cycle_and_allow_fresh_chord(self):
        backend=FakeBackend(); dispatch=[]
        hotkey=X11Hotkey("Ctrl+Space",dispatch.append,glib=FakeGLib(),backend=backend)
        effects=self.make(config=Config(),hotkey=hotkey); effects.glib=FakeGLib()
        effects.config_saver=lambda _config:(_ for _ in ()).throw(OSError("disk full"))
        backend.on_sync=lambda b:b.events.append(b.event(3,65))
        hotkey.gate.press(4,4)
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            with self.assertRaises(OSError):effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+!")
        self.assertFalse(hotkey.gate.down); self.assertFalse(hotkey.gate.wait_release)
        del backend.on_sync
        backend.events=[backend.event(2,65),backend.event(3,65)]; hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(dispatch,[17])
        hotkey.gate.press(4,4); backend.external.add((38,4))
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            with self.assertRaises(RuntimeError):effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a")
        self.assertFalse(hotkey.gate.down); self.assertFalse(hotkey.gate.wait_release)
        backend.external.clear(); backend.events=[backend.event(2,65),backend.event(3,65)]
        hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(dispatch,[17,17]); hotkey.close()

    def test_mapping_health_survives_unchanged_save_and_recovers_after_successful_mapping(self):
        backend=FakeBackend(); effects=self.make(config=Config())
        hotkey=X11Hotkey("Ctrl+Space",lambda *_:None,glib=FakeGLib(),backend=backend,
                         on_error=effects._hotkey_error,on_status=effects._hotkey_status_changed)
        effects.hotkey=hotkey; effects.shortcut_healthy=True; effects.shortcut_status="Global shortcut active: Ctrl+Space"
        backend.mapping[32]=66; backend.external.add((66,4)); backend.events=[backend.event(34)]
        hotkey._ready(9,1)
        self.assertFalse(hotkey.healthy); self.assertFalse(effects.shortcut_healthy)
        self.assertIn("недоступна",effects.shortcut_status)
        effects.config_saver=lambda _config:None
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space")
        self.assertFalse(effects.shortcut_healthy); self.assertIn("недоступна",effects.shortcut_status)
        backend.external.clear(); backend.events=[backend.event(34)]; hotkey._ready(9,1)
        self.assertTrue(hotkey.healthy); self.assertTrue(effects.shortcut_healthy)
        self.assertEqual(effects.shortcut_status,"Глобальная клавиша включена: Ctrl+Space")
        hotkey.close()

    @patch("giga_pisar_dictation.desktop.load_api_key",return_value="")
    def test_conflicting_rebind_and_save_failure_restore_working_binding(self,_):
        old=Hotkey(fail="Ctrl+a"); e=self.make(hotkey=old)
        with self.assertRaises(RuntimeError):e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a")
        self.assertEqual(e.config.hotkey_accelerator,"Ctrl+Space"); self.assertFalse(old.closed)
        old.fail=None
        def fail_save(cfg):raise OSError("disk full")
        e.config_saver=fail_save
        with self.assertRaises(OSError):e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a")
        self.assertEqual(old.accelerator,"Ctrl+Space"); self.assertEqual(e.config.hotkey_accelerator,"Ctrl+Space")
    def test_hotkey_target_is_captured_from_keypress_and_not_replaced_by_startup_probe(self):
        effects=self.make(hotkey=Hotkey())
        effects.view.controller=type("Controller",(),{"state":State.IDLE})()
        calls=[]; effects.command=lambda name:(calls.append(name) or {"ok":True})
        effects._hotkey_toggle(73)
        self.assertEqual(effects.target,73); self.assertTrue(effects._hotkey_target_pending)
        effects.view.controller.state=State.RECORDING
        effects._hotkey_toggle(88)
        self.assertEqual(effects.target,73); self.assertFalse(effects._hotkey_target_pending)
        effects.view.controller.state=State.REQUESTING
        effects._hotkey_toggle(99)
        self.assertEqual(effects.target,73); self.assertFalse(effects._hotkey_target_pending)
        self.assertEqual(calls,["toggle","toggle","toggle"])
    def test_response_inserts_only_to_press_target_and_refuses_after_focus_switch(self):
        class Controller:
            state=State.REQUESTING; _request_generation=7
            def response(self,text,generation):self.text=text;self.state=State.RESULT;return True
        class Paste:
            def __init__(self):self.targets=[]
            def paste_safely(self,text,x11,target,modifiers):
                self.targets.append(target);return x11.active_window()==target
        class TargetX:
            current=73
            def active_window(self):return self.current
        effects=self.make(hotkey=Hotkey()); effects.config=Config(auto_insert=True)
        effects.view.controller=Controller(); effects.view.modifiers_down=lambda:False
        effects.x11=TargetX(); effects.target=73; effects.clipboard=Paste()
        effects._response("dictation",None,7)
        self.assertEqual(effects.clipboard.targets,[73])
        effects.view.controller.state=State.REQUESTING; effects.view.controller._request_generation=8
        effects.target=73; effects.x11.current=88
        effects._response("later",None,8)
        self.assertEqual(effects.clipboard.targets,[73,73])
        self.assertIn("не вставлена",effects.view.status.text)
    def test_start_recording_keeps_hotkey_press_target(self):
        effects=self.make(hotkey=Hotkey()); effects.client=object(); effects.target=73; effects._hotkey_target_pending=True
        effects.recording_generation=0
        effects.x11=FakeX()
        effects.audio_directory=Path("/tmp")
        effects.wav_factory=lambda _directory:type("Wav",(),{"path":"unused"})()
        effects.recorder_factory=lambda *args:type("Recorder",(),{"cancel":lambda self:None})()
        effects.glib=type("GLib",(),{"timeout_add_seconds":lambda self,seconds,callback:1})()
        effects.start_recording()
        self.assertEqual(effects.target,73); self.assertFalse(effects._hotkey_target_pending)
    def test_failed_enable_does_not_report_uncommitted_candidate_active(self):
        e=self.make(config=Config(hotkey_enabled=False)); e.shortcut_healthy=False
        e.shortcut_status="Global shortcut disabled"
        candidate=Hotkey()
        def factory(accelerator,*args,on_status=None,**kwargs):
            if on_status:on_status(True,accelerator)
            return candidate
        e.hotkey_factory=factory
        e.config_saver=lambda _config:(_ for _ in ()).throw(OSError("disk full"))
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            with self.assertRaises(OSError):e.save_settings(Config().base_url,120,"","",True,True,"Ctrl+Space")
        self.assertTrue(candidate.closed); self.assertIsNone(e.hotkey)
        self.assertEqual(e.shortcut_status,"Global shortcut disabled")
        self.assertFalse(e.shortcut_healthy)
    def test_first_right_ctrl_press_from_result_reaches_controller_start(self):
        class StartEffects:
            def start_recording(self): pass
            def remove_audio(self): pass
        effects=self.make()
        controller=Controller(StartEffects()); controller.state=State.RESULT
        effects.view.controller=controller; effects.recording_generation=3; effects._shutdown=False
        effects.glib=FakeGLib()
        hotkey=X11Hotkey("Ctrl+Space",lambda *_:None,glib=FakeGLib(),backend=FakeBackend(),
            mode="push_to_talk",on_start=effects._push_to_talk_start,
            on_stop=effects._push_to_talk_stop,on_invalidate=effects._invalidate_hold)
        backend=hotkey.backend
        backend.down=True
        backend.events=[backend.event(34,request=2),backend.event(2,105)]
        hotkey._ready(9,1)
        self.assertEqual(controller.state,State.RECORDING)
        self.assertEqual(effects._push_to_talk_owner,3)
        self.assertFalse(hotkey.gate.wait_release)
        for generation in range(3,6):
            backend.down=False; backend.events=[backend.event(3,105)]
            hotkey._ready(9,1); hotkey._poll_release()
            controller.state=State.RESULT
            if generation<5:
                effects.recording_generation=generation+1
                backend.down=True
                backend.events=[backend.event(34,request=2),backend.event(2,105)]
                hotkey._ready(9,1)
                self.assertEqual(controller.state,State.RECORDING)
                self.assertEqual(effects._push_to_talk_owner,generation+1)
        hotkey.close()

    def test_push_to_talk_owns_only_its_recording_generation_and_ignores_stale_release(self):
        effects=self.make(hotkey=Hotkey())
        class Controller:
            state=State.IDLE
        effects.view.controller=Controller(); effects.recording_generation=10; effects._shutdown=False
        clock=[10_000_000_000]; effects.monotonic_clock_ns=lambda:clock[0]
        commands=[]
        def command(name):
            commands.append(name)
            if name=="start":effects.view.controller.state=State.RECORDING
            return {"ok":True}
        effects.command=command
        effects.glib=FakeGLib()
        self.assertEqual(effects._push_to_talk_start(73),10)
        self.assertEqual(effects.target,73); self.assertEqual(commands,["start"])
        effects._push_to_talk_stop(9)
        self.assertEqual(commands,["start"])
        effects.view.controller.state=State.RECORDING
        clock[0]=10_700_000_000
        effects._push_to_talk_stop(10)
        self.assertEqual(commands,["start"])
        effects.glib.timers[next(reversed(effects.glib.timers))]()
        self.assertEqual(commands,["start","stop"])
        effects._push_to_talk_stop(10)
        self.assertEqual(commands,["start","stop"])

    def test_push_to_talk_busy_manual_start_error_cancel_and_new_generation(self):
        effects=self.make(hotkey=Hotkey())
        class Controller:
            state=State.REQUESTING
        effects.view.controller=Controller(); effects.recording_generation=2; effects._shutdown=False
        effects.target=51; effects._hotkey_target_pending=False
        commands=[]
        effects.command=lambda name:(commands.append(name) or {"ok":False})
        self.assertIsNone(effects._push_to_talk_start(73))
        self.assertIsNone(getattr(effects,"_push_to_talk_owner",None))
        self.assertEqual((effects.target,effects._hotkey_target_pending),(51,False))
        effects.view.controller.state=State.RECORDING
        self.assertIsNone(effects._push_to_talk_start(99))
        self.assertEqual((effects.target,effects._hotkey_target_pending),(51,False))
        effects.view.controller.state=State.IDLE
        # Busy work completing while held cannot auto-start; a new press is required.
        effects.view.controller.state=State.IDLE
        self.assertEqual(commands,["start","start"])
        def start_command(name):
            commands.append(name)
            if name=="start":effects.view.controller.state=State.RECORDING
            return {"ok":True}
        effects.command=start_command
        self.assertEqual(effects._push_to_talk_start(74),2)
        effects.view.controller.state=State.RECORDING
        effects._push_to_talk_owner=2
        effects._invalidate_hold()
        self.assertIsNone(effects._push_to_talk_owner)
        self.assertEqual(commands[-1],"cancel")
        effects.recording_generation=3
        effects._push_to_talk_stop(2)
        self.assertNotEqual(commands[-1],"stop")

    def test_real_recording_cancel_audio_error_and_limit_drop_hold_ownership(self):
        for terminal in ("cancel", "error", "limit"):
            with self.subTest(terminal=terminal):
                effects=self.make(hotkey=Hotkey()); effects._shutdown=False
                effects.recording_generation=5; effects._push_to_talk_owner=5
                effects._ptt_hold_total_ns=250_000_000; effects._ptt_hold_started_ns=10_000_000_000
                effects.view.controller=Controller(effects); effects.view.controller.state=State.RECORDING
                effects.limit_source=None; effects.recorder=None; effects.wav=None
                effects._push_to_talk_stop=lambda _owner:None
                if terminal=="cancel":effects.view.controller.cancel()
                elif terminal=="error":effects._audio_error(5)
                else:effects._recording_limit(5)
                self.assertIsNone(effects._push_to_talk_owner)
                self.assertEqual(effects._ptt_hold_total_ns,0)
                self.assertIsNone(effects._ptt_hold_started_ns)
                self.assertNotEqual(effects.view.controller.state,State.RECORDING)

    def test_push_to_talk_cancel_invalidation_and_shutdown_ignore_stale_generation(self):
        effects=self.make(hotkey=Hotkey()); effects._shutdown=False; effects.recording_generation=5
        class Controller:
            state=State.RECORDING
        effects.view.controller=Controller(); effects._push_to_talk_owner=5
        commands=[]
        effects.command=lambda name:(commands.append(name) or {"ok":True})
        # Audio error / limit cancellation invalidates the owned generation; a late release is stale.
        effects._invalidate_hold()
        self.assertEqual(commands,["cancel"]); self.assertIsNone(effects._push_to_talk_owner)
        effects._push_to_talk_stop(5); self.assertEqual(commands,["cancel"])
        effects._shutdown=True
        self.assertIsNone(effects._push_to_talk_start(91))
        self.assertEqual(commands,["cancel"])

    def test_mode_change_rejected_while_recording_and_legacy_toggle_binding_is_retained(self):
        effects=self.make(config=Config(hotkey_mode="toggle",hotkey_accelerator="Ctrl+a"),hotkey=Hotkey())
        effects.view.controller=type("Controller",(),{"state":State.RECORDING})()
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            with self.assertRaisesRegex(RuntimeError,"Нельзя менять глобальную клавишу"):
                effects.save_settings(Config().base_url,120,"","",True,True,"Ctrl+a",hotkey_mode="push_to_talk")
        self.assertEqual(effects.config.hotkey_mode,"toggle")
        self.assertEqual(effects.config.hotkey_accelerator,"Ctrl+a")

    def test_disabled_config_save_failure_does_not_close_hotkey(self):
        old=Hotkey(); e=self.make(hotkey=old,saver=lambda cfg:(_ for _ in ()).throw(OSError("disk")))
        with patch("giga_pisar_dictation.desktop.load_api_key",return_value=""):
            with self.assertRaises(OSError):e.save_settings(Config().base_url,120,"","",True,False,"Ctrl+Space")
        self.assertFalse(old.closed); self.assertTrue(e.config.hotkey_enabled)


if __name__=="__main__":unittest.main()
