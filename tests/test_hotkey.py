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
        self.mapping={32:65,ord("a"):38,ord("1"):65,ord("!"):65}; self.on_query=None
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
    def event(self,kind,code=65,state=4): return SimpleNamespace(type=kind,xkey=SimpleNamespace(keycode=code,state=state),xmapping=SimpleNamespace())


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
