import ctypes
import unittest
from types import SimpleNamespace
from giga_pisar_dictation.hotkey import EventGate, NativeX11Backend, X11Hotkey, XKeyEvent, XEvent, lock_mask_variants, parse_accelerator
from giga_pisar_dictation.desktop import DesktopEffects


class FakeGLib:
    IO_IN=1; SOURCE_REMOVE=False; PRIORITY_DEFAULT=0
    def __init__(self): self.watches={}; self.timers={}; self.removed=[]; self.i=0
    def io_add_watch(self,fd,priority,condition,callback): self.i+=1; self.watches[self.i]=callback; return self.i
    def timeout_add(self,ms,callback): self.i+=1; self.timers[self.i]=callback; return self.i
    def source_remove(self,i): self.removed.append(i)
    def idle_add(self,callback,*args): return callback(*args)


class FakeBackend:
    def __init__(self):
        self.events=[]; self.grabs=set(); self.external=set(); self.fail=None
        self.down=False; self.mods=False; self.closed=False; self.window=17; self.masks=(0,2,16,18)
        self.mapping={32:65,ord("a"):38,ord("1"):65,ord("!"):65,0xffe3:37,0xffe4:105}; self.on_query=None
        self.last_additions=set(); self.last_removals=set(); self.update_calls=[]; self.grab_calls=0
    def keycode(self,sym): return self.mapping.get(sym,0)
    def lock_masks(self): return self.masks
    def modifier_mask(self,names): return parse_accelerator("+".join(names)+"+Space")[1]
    def grab_entries(self,entries):
        self.grab_calls+=1
        entries=set(entries); self.last_additions=entries.copy(); acquired=set()
        for entry in sorted(entries):
            if entry in self.external or entry==self.fail:
                # Match NativeX11Backend: roll back only entries requested by this grab.
                self.grabs.difference_update(acquired)
                raise RuntimeError("BadAccess")
            acquired.add(entry)
        self.grabs.update(acquired)
    def ungrab_entries(self,entries):
        self.last_removals=set(entries); self.grabs.difference_update(entries)
    def grab(self,code,mods,masks): self.grab_entries({(code,mods|lock) for lock in masks})
    def ungrab(self,code,mods,masks): self.ungrab_entries({(code,mods|lock) for lock in masks})
    def update_grabs(self,oldcode,oldmods,oldmasks,newcode,newmods,newmasks):
        old={(oldcode,oldmods|m) for m in oldmasks}; new={(newcode,newmods|m) for m in newmasks}
        self.update_calls.append((old.copy(),new.copy()))
        adds=new-old; removes=old-new
        self.grab_entries(adds); self.ungrab_entries(removes)
    def select_mapping(self): pass
    def sync(self):
        if hasattr(self,"on_sync"): self.on_sync(self)
    def fd(self): return 9
    def pending(self): return bool(self.events)
    def next_event(self): return self.events.pop(0)
    def active_window(self): return self.window
    def key_is_down(self,key):
        if self.on_query:self.on_query(self,"key")
        return self.down
    def modifiers_down(self):
        if self.on_query:self.on_query(self,"mods")
        return self.mods
    def refresh_mapping(self,event): pass
    def close(self): self.closed=True; self.grabs.clear()
    def event(self,kind,code=65,state=4,request=1,first_keycode=0,count=0):
        return SimpleNamespace(type=kind,xkey=SimpleNamespace(keycode=code,state=state),
            xmapping=SimpleNamespace(request=request,first_keycode=first_keycode,count=count))


class AcceleratorTests(unittest.TestCase):
    def test_default_shortcut_and_modifiers(self):
        self.assertEqual(parse_accelerator("Ctrl+Space"),(0x20,4))
        self.assertEqual(parse_accelerator("Ctrl+Shift+a"),(ord("a"),5))
    def test_rejects_unsupported_or_unmodified_shortcuts(self):
        for value in ("Space","Ctrl+F1","Ctrl+","Hyper+Space"):
            with self.subTest(value=value),self.assertRaises(ValueError):parse_accelerator(value)
    def test_caps_num_and_combined_lock_variants(self):
        self.assertEqual(set(lock_mask_variants(2,16)),{0,2,16,18})
        self.assertEqual(set(lock_mask_variants(2|8,16)),{0,2,8,10,16,18,24,26})
    def test_native_event_structures_match_xlib_layout(self):
        self.assertEqual(XKeyEvent.keycode.offset,XKeyEvent.state.offset+4)
        self.assertEqual(XEvent.xkey.offset,0)
        self.assertGreaterEqual(ctypes.sizeof(XEvent),192)


class EventGateTests(unittest.TestCase):
    def test_target_captured_on_first_press_repeat_suppressed_and_waits_for_full_release(self):
        targets=[17]; calls=[]; gate=EventGate(lambda:targets[0],calls.append)
        gate.press(4,4); targets[0]=23
        gate.press(4,4)
        gate.release(); gate.press(4,4)
        self.assertFalse(gate.poll(False,True)); self.assertFalse(gate.poll(True,False))
        self.assertTrue(gate.poll(False,False)); self.assertEqual(calls,[17])
        gate.release(); gate.press(4,4); self.assertEqual(calls,[17])
        gate.close(); self.assertFalse(gate.poll(False,False))


class FakeCFunction:
    def __init__(self,call):self.call=call; self.argtypes=None; self.restype=None
    def __call__(self,*args):return self.call(*args)


class NativeGrabTests(unittest.TestCase):
    def test_modifier_masks_follow_live_server_mapping(self):
        class ModifierMap(ctypes.Structure):_fields_=[("max_keypermod",ctypes.c_int),("modifiermap",ctypes.POINTER(ctypes.c_ubyte))]
        codes=(ctypes.c_ubyte*24)(); codes[4*3]=37; codes[6*3]=64; mapping=ModifierMap(3,codes)
        class X:pass
        x=X(); x.XGetModifierMapping=FakeCFunction(lambda _display:ctypes.pointer(mapping))
        x.XFreeModifiermap=FakeCFunction(lambda _map:1)
        x.XKeysymToKeycode=FakeCFunction(lambda _display,sym:37 if sym in (0xffe3,0xffe4) else 64)
        native=NativeX11Backend.__new__(NativeX11Backend); native.x=x; native.display=1
        self.assertEqual(native.modifier_mask(("CTRL","ALT")),(1<<4)|(1<<6))

    def test_native_rejects_zero_keycode_before_any_grab(self):
        native=NativeX11Backend.__new__(NativeX11Backend); native.x=object()
        with self.assertRaisesRegex(Exception,"отсутствует в раскладке"):native.grab_entries({(0,4)})
        with self.assertRaisesRegex(Exception,"отсутствует в раскладке"):native.grab(0,4,(0,2))
        with self.assertRaisesRegex(Exception,"отсутствует в раскладке"):native.update_grabs(65,4,(0,),0,4,(0,))

    def test_badaccess_during_partial_grab_rolls_back_only_new_entries(self):
        from giga_pisar_dictation.hotkey import XErrorEvent
        class X:pass
        x=X(); x.grabs={(65,4)}; x.ungrabs=[]; x.handler=None; x.failed=False
        x.XGrabKey=FakeCFunction(lambda *args:x.grabs.add((args[1],args[2])))
        x.XUngrabKey=FakeCFunction(lambda *args:x.ungrabs.append((args[1],args[2])) or x.grabs.discard((args[1],args[2])))
        def sync(*args):
            if not x.failed:
                x.failed=True; err=XErrorEvent();err.error_code=10; x.handler(None,ctypes.pointer(err))
        x.XSync=FakeCFunction(sync)
        x.XSetErrorHandler=FakeCFunction(lambda cb:(setattr(x,"handler",cb) or None))
        native=NativeX11Backend.__new__(NativeX11Backend);native.x=x;native.display=1;native.root=3
        with self.assertRaisesRegex(Exception,"уже используется"):
            native.grab_entries({(65,6),(65,20),(65,22)})
        self.assertEqual(x.grabs,{(65,4)})
        self.assertEqual(set(x.ungrabs),{(65,6),(65,20),(65,22)})


class PushToTalkHotkeyTests(unittest.TestCase):
    def make_hotkey(self, backend=None, **kwargs):
        backend=backend or FakeBackend(); glib=FakeGLib(); calls=[]
        hotkey=X11Hotkey("Ctrl+Space",lambda *_args:None,glib=glib,backend=backend,
                         target_at_press=lambda:backend.window,mode="push_to_talk",**kwargs)
        return hotkey,backend,glib,calls

    def test_binding_is_right_control_only_with_all_256_modifier_masks(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        self.assertEqual(hotkey.keysym,0xffe4); self.assertEqual(hotkey.keycode,105)
        self.assertEqual(hotkey.entries,{(105,mask) for mask in range(256)})
        self.assertFalse(any(code==37 for code,_mask in backend.grabs))
        hotkey.close()

    def test_physical_release_autorepeat_and_left_control_exclusion(self):
        starts=[]; stops=[]
        hotkey,backend,_glib,_calls=self.make_hotkey(on_start=lambda target:starts.append(target) or 4,
            on_stop=stops.append)
        backend.window=17
        hotkey._ready(9,1) if not backend.events else None
        backend.events=[backend.event(2,37),backend.event(3,37)]
        hotkey._ready(9,1); self.assertEqual(starts,[])
        backend.events=[backend.event(2,105)]; backend.down=True; backend.window=23
        hotkey._ready(9,1); backend.window=99
        self.assertEqual(starts,[23])
        backend.events=[backend.event(3,105),backend.event(2,105)]; backend.down=True
        hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(stops,[]); self.assertTrue(hotkey.gate.wait_release)
        backend.events=[backend.event(3,105)]; backend.down=False; hotkey._ready(9,1)
        hotkey._poll_release(); self.assertEqual(stops,[4])
        hotkey.close()

    def test_release_without_press_short_tap_busy_ownerless_and_start_failure(self):
        starts=[]; stops=[]
        hotkey,backend,_glib,_calls=self.make_hotkey(on_start=lambda target:starts.append(target) or None,
            on_stop=stops.append)
        backend.events=[backend.event(3,105)]; hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual((starts,stops),([],[]))
        backend.events=[backend.event(2,105),backend.event(3,105)]; backend.down=False
        hotkey._ready(9,1); self.assertEqual(len(starts),1); hotkey._poll_release()
        self.assertEqual(stops,[])
        hotkey.close()
        starts=[]
        hotkey,backend,_glib,_calls=self.make_hotkey(on_start=lambda _target:starts.append(1) or None)
        backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
        backend.events=[backend.event(3,105)]; backend.down=False; hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(starts,[1]); hotkey.close()

    def test_activate_rechecks_physical_key_and_suppresses_buffered_repeat(self):
        starts=[]
        backend=FakeBackend(); hotkey=X11Hotkey("Ctrl+Space",lambda *_args:None,glib=FakeGLib(),backend=backend,
            mode="push_to_talk",on_start=lambda target:starts.append(target) or 1)
        backend.down=True
        hotkey.activate(lambda *_args:None,on_start=lambda target:starts.append(target) or 2)
        backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
        self.assertEqual(starts,[])
        backend.down=False; hotkey._poll_release()
        backend.down=True; backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
        self.assertEqual(starts,[17])
        hotkey.close()

    def test_held_key_on_enable_and_sync_or_query_buffered_events_wait_for_new_press(self):
        starts=[]
        backend=FakeBackend(); backend.down=True
        backend.on_sync=lambda b:b.events.append(b.event(2,105))
        hotkey=X11Hotkey("Ctrl+Space",lambda *_args:None,glib=FakeGLib(),backend=backend,
            mode="push_to_talk",on_start=lambda target:starts.append(target) or 1)
        self.assertEqual(starts,[])
        hotkey._poll_release(); self.assertEqual(starts,[])
        backend.down=False; hotkey._poll_release()
        self.assertEqual(starts,[])
        # A subsequent physical press is the only event that can own a cycle.
        backend.down=True; backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
        self.assertEqual(starts,[17]); hotkey.close()

    def test_irrelevant_mapping_notify_before_press_does_not_consume_first_ptt_press(self):
        starts=[]; stops=[]
        hotkey,backend,_glib,_calls=self.make_hotkey(on_start=lambda target:starts.append(target) or len(starts),
            on_stop=stops.append)
        # MappingPointer does not describe keyboard state. The physical key is already down
        # when the queued notification is drained, as in the first-press regression.
        backend.down=True; backend.events=[backend.event(34,request=2),backend.event(2,105)]
        hotkey._ready(9,1)
        self.assertEqual(starts,[17]); self.assertTrue(hotkey.gate.down)
        self.assertFalse(hotkey.gate.wait_release)
        # Unrelated keyboard notification during the hold must not invalidate ownership.
        backend.events=[backend.event(34,request=1,first_keycode=20,count=1)]
        hotkey._ready(9,1)
        self.assertTrue(hotkey.gate.down); self.assertEqual(stops,[])
        backend.down=False; backend.events=[backend.event(3,105)]; hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(stops,[1])
        # Repeated RESULT -> RECORDING cycles remain first-press responsive.
        for generation in range(2,5):
            backend.down=True; backend.events=[backend.event(34,request=2),backend.event(2,105)]
            hotkey._ready(9,1)
            self.assertEqual(starts,[17]*generation)
            backend.down=False; backend.events=[backend.event(3,105)]; hotkey._ready(9,1); hotkey._poll_release()
        self.assertEqual(stops,[1,2,3,4])
        hotkey.close()

    def test_real_mapping_change_during_ptt_release_tail_invalidates_owner(self):
        starts=[]; stops=[]; invalidations=[]
        hotkey,backend,_glib,_calls=self.make_hotkey(
            on_start=lambda target:starts.append(target) or 7,
            on_stop=stops.append,on_invalidate=lambda:invalidations.append(True))
        backend.down=True; backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
        backend.down=False; backend.events=[backend.event(3,105)]; hotkey._ready(9,1); hotkey._poll_release()
        self.assertFalse(hotkey.gate.wait_release); self.assertEqual(hotkey.gate.owner,7)
        self.assertEqual(stops,[7])
        backend.mapping[0xffe4]=106; backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertEqual(hotkey.keycode,106); self.assertEqual(invalidations,[True])
        self.assertFalse(hotkey.gate.wait_release); self.assertIsNone(hotkey.gate.owner)
        hotkey.close()

    def test_missing_keycode_invalidates_held_and_tail_ptt_ownership(self):
        for tail in (False,True):
            with self.subTest(tail=tail):
                invalidations=[]; stops=[]
                hotkey,backend,_glib,_calls=self.make_hotkey(
                    on_start=lambda _target:11,on_stop=stops.append,
                    on_invalidate=lambda:invalidations.append(True))
                backend.down=True; backend.events=[backend.event(2,105)]; hotkey._ready(9,1)
                if tail:
                    backend.down=False; backend.events=[backend.event(3,105)]
                    hotkey._ready(9,1); hotkey._poll_release()
                    self.assertEqual(stops,[11]); self.assertEqual(hotkey.gate.owner,11)
                backend.mapping[0xffe4]=0; backend.events=[backend.event(34,request=1)]
                hotkey._ready(9,1)
                self.assertFalse(hotkey.gate.down); self.assertFalse(hotkey.gate.wait_release)
                self.assertIsNone(hotkey.gate.owner); self.assertEqual(invalidations,[True])
                self.assertFalse(hotkey.healthy)
                hotkey.close()

    def test_missing_toggle_keycode_resets_unfinished_gate_before_failed_dispatch(self):
        backend=FakeBackend(); calls=[]
        hotkey=X11Hotkey("Ctrl+Space",calls.append,glib=FakeGLib(),backend=backend)
        hotkey.gate.press(4,4)
        backend.mapping[32]=0; backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertFalse(hotkey.gate.down); self.assertFalse(hotkey.gate.wait_release)
        hotkey.gate.release(); hotkey._poll_release()
        self.assertEqual(calls,[]); self.assertFalse(hotkey.healthy)
        hotkey.close()

    def test_unhealthy_binding_recovers_after_missing_keycode_or_grab_conflict(self):
        for failure in ("missing", "conflict"):
            with self.subTest(failure=failure):
                backend=FakeBackend(); hotkey=X11Hotkey("Ctrl+Space",lambda *_:None,
                    glib=FakeGLib(),backend=backend)
                if failure=="missing":backend.mapping[32]=0
                else:
                    backend.mapping[32]=66; backend.external.add((66,4))
                backend.events=[backend.event(34,request=1)]; hotkey._ready(9,1)
                self.assertFalse(hotkey.healthy)
                backend.mapping[32]=65; backend.external.clear()
                backend.events=[backend.event(34,request=1)]; hotkey._ready(9,1)
                self.assertTrue(hotkey.healthy); self.assertTrue(hotkey.verify_binding())
                self.assertTrue(backend.grabs.issuperset(hotkey.entries))
                hotkey.close()

    def test_prepared_candidate_mapping_change_away_and_back_stays_invalid(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
        backend.mapping[ord("a")]=45; backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertTrue(hotkey._prepared_invalid)
        backend.mapping[ord("a")]=38; backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertTrue(hotkey._prepared_invalid)
        with self.assertRaises(Exception):hotkey.commit_rebind()
        hotkey.rollback_rebind(); self.assertEqual(hotkey.mode,"push_to_talk")
        hotkey.close()

    def test_mapping_check_error_resets_gate_and_invalidates_prepared_candidate(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
        backend.mapping[ord("a")]=0; backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertTrue(hotkey._prepared_invalid); self.assertFalse(hotkey.healthy)
        self.assertFalse(hotkey.gate.down); self.assertFalse(hotkey.gate.wait_release)
        with self.assertRaises(Exception):hotkey.commit_rebind()
        hotkey.rollback_rebind(); hotkey.close()

    def test_unchanged_mapping_notify_preserves_prepared_candidate(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
        backend.events=[backend.event(34,request=1)]
        hotkey._ready(9,1)
        self.assertFalse(hotkey._prepared_invalid); self.assertTrue(hotkey.healthy)
        hotkey.commit_rebind()
        self.assertEqual(hotkey.accelerator,"Ctrl+a"); hotkey.close()

    def test_mapping_during_prepare_invalidates_and_commit_rechecks_current_binding(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
        backend.mapping[ord("a")]=45
        backend.events=[backend.event(34)]
        hotkey._ready(9,1)
        self.assertTrue(hotkey.healthy)
        with self.assertRaises(Exception):hotkey.commit_rebind()
        hotkey.rollback_rebind()
        self.assertTrue(backend.grabs.issuperset(hotkey.entries))
        hotkey.close()

    def test_mapping_change_during_commit_restores_old_grabs_and_rejects_candidate(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        old_entries=hotkey.entries.copy(); old_grabs=backend.grabs.copy()
        self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
        original_ungrab=backend.ungrab_entries; injected=[False]
        def ungrab(entries):
            original_ungrab(entries)
            if entries and not injected[0]:
                injected[0]=True; backend.mapping[ord("a")]=45
                backend.events.append(backend.event(34))
        backend.ungrab_entries=ungrab
        with self.assertRaises(Exception):hotkey.commit_rebind()
        self.assertEqual(backend.grabs,old_grabs)
        self.assertEqual(hotkey.entries,old_entries)
        hotkey.rollback_rebind(); hotkey.close()

    def test_mapping_remap_uses_all_256_ptt_masks_and_detects_any_conflict(self):
        hotkey,backend,_glib,_calls=self.make_hotkey()
        backend.mapping[0xffe4]=106; backend.events=[backend.event(34)]
        hotkey._ready(9,1)
        self.assertEqual(hotkey.entries,{(106,mask) for mask in range(256)})
        self.assertEqual(backend.grabs,hotkey.entries)
        self.assertEqual(backend.update_calls,[])
        backend.external.add((107,193)); backend.mapping[0xffe4]=107
        backend.events=[backend.event(34)]; hotkey._ready(9,1)
        self.assertEqual(backend.grabs,hotkey.entries)
        self.assertTrue(hotkey.healthy is False)
        self.assertNotIn((105,0),backend.grabs)
        hotkey.close()

    def test_zero_keycode_and_validation_exception_after_removal_restore_old_grabs(self):
        for failure in ("zero", "exception"):
            with self.subTest(failure=failure):
                hotkey,backend,_glib,_calls=self.make_hotkey()
                old_entries=hotkey.entries.copy(); old_grabs=backend.grabs.copy()
                self.assertTrue(hotkey.prepare_binding("toggle","Ctrl+a"))
                original_ungrab=backend.ungrab_entries; injected=[False]
                def ungrab(entries):
                    original_ungrab(entries)
                    if entries and not injected[0]:
                        injected[0]=True
                        if failure=="zero":backend.mapping[ord("a")]=0
                        else:
                            original_keycode=backend.keycode
                            def invalid_validation(sym):
                                if sym==ord("a"):raise RuntimeError("mapping validation failed")
                                return original_keycode(sym)
                            backend.keycode=invalid_validation
                backend.ungrab_entries=ungrab
                with self.assertRaises(Exception):hotkey.commit_rebind()
                self.assertEqual(backend.grabs,old_grabs)
                self.assertEqual(hotkey.entries,old_entries)
                hotkey.rollback_rebind(); hotkey.close()

    def test_grab_conflict_partial_prepare_rolls_back_and_close_releases_everything(self):
        hotkey,backend,glib,_calls=self.make_hotkey()
        old=backend.grabs.copy(); backend.fail=(38,20)
        with self.assertRaises(RuntimeError):hotkey.prepare_binding("toggle","Ctrl+a")
        self.assertEqual(backend.grabs,old)
        source,poll=hotkey.source,hotkey.poll_source
        hotkey.close()
        self.assertFalse(backend.grabs); self.assertEqual(set(glib.removed),{source,poll})


class X11HotkeyTests(unittest.TestCase):
    def setUp(self):
        self.backend=FakeBackend(); self.glib=FakeGLib(); self.calls=[]
        self.hotkey=X11Hotkey("Ctrl+Space",self.calls.append,glib=self.glib,backend=self.backend)
    def tearDown(self): self.hotkey.close()
    def test_startup_sync_drains_buffered_key_cycle_before_io_watch_dispatch(self):
        backend=FakeBackend(); backend.on_sync=lambda b:b.events.extend((b.event(2),b.event(3)))
        glib=FakeGLib(); calls=[]
        hotkey=X11Hotkey("Ctrl+Space",calls.append,glib=glib,backend=backend)
        self.assertEqual(calls,[]); self.assertFalse(backend.events); self.assertTrue(hotkey.gate.wait_release)
        hotkey._poll_release(); self.assertEqual(calls,[17]); hotkey.close()

    def test_buffered_events_after_sync_query_drain_without_io_watch(self):
        self.hotkey.gate.press(4,4); self.hotkey.gate.release()
        injected=[False]
        def query(backend,which):
            if which=="mods" and not injected[0]:
                injected[0]=True
                backend.events.append(backend.event(3)); backend.down=False
        self.backend.on_query=query
        self.hotkey._poll_release()
        self.assertEqual(self.calls,[]); self.assertFalse(self.backend.events)
        self.backend.on_query=None
        self.hotkey._poll_release()
        self.assertEqual(self.calls,[17])
        self.backend.events.append(self.backend.event(2)); self.backend.down=True
        self.hotkey._poll_release(); self.assertTrue(self.hotkey.gate.down)
        self.backend.events.append(self.backend.event(3)); self.backend.down=False
        self.hotkey._poll_release(); self.assertEqual(self.calls,[17])
        self.hotkey._poll_release(); self.assertEqual(self.calls,[17,17])
    def test_conflicting_rebind_keeps_old_and_unchanged_physical_entries(self):
        old=self.backend.grabs.copy()
        self.assertFalse(self.hotkey.rebind("Ctrl+Space")); self.assertEqual(self.backend.grabs,old)
        self.backend.fail=(38,20)  # Fail after two newly attempted variants.
        with self.assertRaises(RuntimeError):self.hotkey.rebind("Ctrl+a")
        self.assertEqual(self.backend.grabs,old)
    def test_overlapping_physical_binding_sets_commit_and_rollback_by_delta(self):
        self.backend.mapping[ord("!")]=65
        old=self.backend.grabs.copy()
        # Different keysyms can resolve to one physical X keycode: no grab/ungrab churn.
        old_calls=self.backend.grab_calls
        self.assertTrue(self.hotkey.prepare_rebind("Ctrl+!"))
        self.assertEqual(self.backend.grab_calls,old_calls)
        self.hotkey.commit_rebind()
        self.assertEqual(self.backend.grabs,old)
        # A changed lock mapping adds only the two missing physical variants.
        self.backend.masks=(0,2,32,34)
        old=self.backend.grabs.copy()
        self.assertTrue(self.hotkey.prepare_rebind("Ctrl+1"))
        self.assertEqual(self.backend.last_additions,{(65,36),(65,38)})
        self.hotkey.commit_rebind()
        self.assertEqual(self.backend.grabs,{(65,4),(65,6),(65,36),(65,38)})
        committed=self.backend.grabs.copy()
        self.backend.mapping[ord("!")]=65; self.backend.masks=(0,2,16,18)
        self.assertTrue(self.hotkey.prepare_rebind("Ctrl+!"))
        self.hotkey.rollback_rebind()
        self.assertEqual(self.backend.grabs,committed)
        self.assertEqual(self.hotkey.keycode,65)
    def test_zero_keycode_start_rebind_mapping_change_never_grabs_zero(self):
        backend=FakeBackend(); backend.mapping[32]=0
        with self.assertRaisesRegex(Exception,"отсутствует в раскладке"):X11Hotkey("Ctrl+Space",lambda *_:None,glib=FakeGLib(),backend=backend)
        self.assertFalse(any(code==0 for code,_mask in backend.grabs))
        backend=FakeBackend(); hotkey=X11Hotkey("Ctrl+Space",lambda *_:None,glib=FakeGLib(),backend=backend)
        old=backend.grabs.copy(); backend.mapping[ord("a")]=0
        with self.assertRaisesRegex(Exception,"отсутствует в раскладке"):hotkey.rebind("Ctrl+a")
        self.assertEqual(backend.grabs,old); self.assertFalse(any(code==0 for code,_mask in backend.grabs))
        errors=[]; hotkey.on_error=errors.append; backend.mapping[32]=0
        backend.events=[backend.event(34)]; hotkey._ready(9,1)
        self.assertEqual(hotkey.grabs if hasattr(hotkey,"grabs") else backend.grabs,old)
        self.assertTrue(errors); self.assertFalse(any(code==0 for code,_mask in backend.grabs)); hotkey.close()
    def test_mapping_change_cancels_old_cycle_and_accepts_fresh_full_chord(self):
        self.hotkey.gate.press(4,4); self.assertTrue(self.hotkey.gate.down)
        self.backend.mapping[32]=66; self.backend.window=88
        self.backend.events=[self.backend.event(34),self.backend.event(3,65)]
        self.hotkey._ready(9,1)
        self.assertFalse(self.hotkey.gate.down); self.assertFalse(self.hotkey.gate.wait_release)
        self.assertEqual(self.calls,[])
        self.backend.events=[self.backend.event(2,66),self.backend.event(3,66)]
        self.hotkey._ready(9,1); self.hotkey._poll_release()
        self.assertEqual(self.calls,[88])

    def test_mapping_notify_changes_grab_and_conflict_keeps_old_status(self):
        class Status:
            text=""
            def set_text(self,value):self.text=value
        effects=SimpleNamespace(shortcut_status="active",view=SimpleNamespace(shortcut_status=Status()))
        self.hotkey.on_error=lambda message:DesktopEffects._hotkey_status_changed(effects,False); old=self.backend.grabs.copy()
        self.backend.mapping[32]=66; self.backend.events=[self.backend.event(34)]; self.hotkey._ready(9,1)
        self.assertEqual(self.hotkey.keycode,66); self.assertNotEqual(self.backend.grabs,old)
        self.assertEqual(len(self.backend.update_calls),1)
        self.assertEqual(effects.shortcut_status,"active")
        current=self.backend.grabs.copy(); self.backend.mapping[32]=67
        self.backend.external.add((67,4)); self.backend.events=[self.backend.event(34)]; self.hotkey._ready(9,1)
        self.assertEqual(self.hotkey.keycode,66); self.assertEqual(self.backend.grabs,current)
        self.assertEqual(len(self.backend.update_calls),2)
        self.assertEqual(effects.shortcut_status,"Глобальная клавиша недоступна после изменения раскладки X11")
        self.assertEqual(effects.view.shortcut_status.text,effects.shortcut_status)
    def test_close_removes_glib_sources_and_late_callback_is_ignored(self):
        callback=self.glib.watches[self.hotkey.source]; self.hotkey.close()
        self.assertTrue(self.backend.closed); self.assertEqual(len(self.glib.removed),2)
        self.assertFalse(callback(9,1)); self.assertEqual(self.calls,[])


if __name__=="__main__":unittest.main()
