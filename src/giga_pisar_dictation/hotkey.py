"""Passive X11 hotkey registration and event dispatch."""
from __future__ import annotations
import ctypes
import ctypes.util
from .x11 import _ERROR_LOCK, _X_ERROR_HANDLER


class ShortcutError(RuntimeError): pass


def _require_keycode(keycode):
    if not keycode: raise ShortcutError("Shortcut key is not mapped by X11")


def parse_accelerator_details(value):
    parts=value.split("+")
    if len(parts)<2 or any(not p for p in parts): raise ValueError("Shortcut needs a modifier and a key")
    aliases={"CTRL":"CTRL","CONTROL":"CTRL","SHIFT":"SHIFT","ALT":"ALT","SUPER":"SUPER","META":"META"}
    try: modifiers=tuple(aliases[name.upper()] for name in parts[:-1])
    except KeyError: raise ValueError("Unsupported shortcut modifier") from None
    key=parts[-1]
    if len(key)==1: sym=ord(key.lower())
    elif key.lower()=="space": sym=0x20
    else: raise ValueError("Unsupported shortcut key")
    return sym,modifiers


def parse_accelerator(value):
    sym,names=parse_accelerator_details(value)
    masks={"CTRL":4,"SHIFT":1,"ALT":8,"SUPER":64,"META":64}
    mask=0
    for name in names: mask|=masks[name]
    return sym,mask


class XKeyEvent(ctypes.Structure):
    _fields_=[("type",ctypes.c_int),("serial",ctypes.c_ulong),("send_event",ctypes.c_int),("display",ctypes.c_void_p),
              ("window",ctypes.c_ulong),("root",ctypes.c_ulong),("subwindow",ctypes.c_ulong),("time",ctypes.c_ulong),
              ("x",ctypes.c_int),("y",ctypes.c_int),("x_root",ctypes.c_int),("y_root",ctypes.c_int),
              ("state",ctypes.c_uint),("keycode",ctypes.c_uint),("same_screen",ctypes.c_int)]
class XMappingEvent(ctypes.Structure):
    _fields_=[("type",ctypes.c_int),("serial",ctypes.c_ulong),("send_event",ctypes.c_int),("display",ctypes.c_void_p),
              ("window",ctypes.c_ulong),("request",ctypes.c_int),("first_keycode",ctypes.c_int),("count",ctypes.c_int)]
class XEvent(ctypes.Union):
    _fields_=[("type",ctypes.c_int),("xkey",XKeyEvent),("xmapping",XMappingEvent),("pad",ctypes.c_long*24)]
def lock_mask_variants(caps_mask=2, num_mask=None):
    lock_masks={0}
    for mask in (caps_mask,num_mask or 0):
        bit=1
        while bit<=mask:
            if mask & bit: lock_masks.add(bit)
            bit <<= 1
    variants={0}
    for mask in lock_masks-{0}: variants|={value|mask for value in tuple(variants)}
    return tuple(sorted(variants))


class XErrorEvent(ctypes.Structure):
    _fields_=[("type",ctypes.c_int),("display",ctypes.c_void_p),("resourceid",ctypes.c_ulong),
              ("serial",ctypes.c_ulong),("error_code",ctypes.c_ubyte),("request_code",ctypes.c_ubyte),("minor_code",ctypes.c_ubyte)]


class EventGate:
    """Suppress repeats and dispatch only after chord keys/modifiers are released."""
    def __init__(self, target_at_press, dispatch):
        self.target_at_press=target_at_press; self.dispatch=dispatch
        self.down=False; self.wait_release=False; self.target=None; self.closed=False
    def press(self, state, required):
        if self.closed or self.down or self.wait_release or state & required != required: return
        self.down=True; self.target=self.target_at_press()
    def release(self):
        if self.down: self.down=False; self.wait_release=True
    def poll(self, key_down, modifiers_down):
        if self.closed or not self.wait_release or key_down or modifiers_down: return False
        self.wait_release=False; target=self.target; self.target=None
        self.dispatch(target); return True
    def reset(self): self.down=False; self.wait_release=False; self.target=None
    def close(self): self.closed=True; self.reset()


class X11Hotkey:
    def __init__(self, accelerator, dispatch, glib=None, display=None, backend=None, target_at_press=None, on_error=None, on_status=None):
        import gi
        gi.require_version("GLib","2.0")
        from gi.repository import GLib
        self.glib=glib or GLib; self.dispatch=dispatch; self.on_error=on_error; self.on_status=on_status
        self.healthy=True; self.closed=False; self.source=None; self.poll_source=None
        self.backend=backend or NativeX11Backend(display)
        self.gate=None
        try:
            self.accelerator=accelerator
            self.keysym,self.modifier_names=parse_accelerator_details(accelerator)
            self.required=self._modifier_mask(self.modifier_names)
            self.gate=EventGate(target_at_press or self.backend.active_window,dispatch)
            self._bind()
            self._notify_status()
        except Exception:
            self.close(); raise

    def _modifier_mask(self,names):
        return self.backend.modifier_mask(names) if hasattr(self.backend,"modifier_mask") else parse_accelerator(self.accelerator)[1]

    def _notify_status(self):
        if self.on_status: self.on_status(self.healthy,self.accelerator)

    def _bind(self):
        self.keycode=self.backend.keycode(self.keysym)
        _require_keycode(self.keycode)
        self.lock_masks=self.backend.lock_masks()
        self.entries=self._binding_entries(self.keycode,self.required,self.lock_masks)
        self._grab_entries(self.entries)
        if hasattr(self.backend,"sync"): self.backend.sync()
        self._drain_events()
        self.backend.select_mapping()
        self.source=self.glib.io_add_watch(self.backend.fd(), self.glib.PRIORITY_DEFAULT, self.glib.IO_IN, self._ready)
        self.poll_source=self.glib.timeout_add(20,self._poll_release)

    @staticmethod
    def _binding_entries(keycode,required,masks):
        _require_keycode(keycode)
        return frozenset((keycode,required|lock) for lock in masks)

    def _grab_entries(self,entries):
        if entries: self.backend.grab_entries(entries)

    def _ungrab_entries(self,entries):
        if entries: self.backend.ungrab_entries(entries)

    def prepare_rebind(self, accelerator):
        sym,names=parse_accelerator_details(accelerator); mods=self.backend.modifier_mask(names) if hasattr(self.backend,"modifier_mask") else parse_accelerator(accelerator)[1]
        code=self.backend.keycode(sym); _require_keycode(code); masks=self.backend.lock_masks()
        if sym==self.keysym and mods==self.required: return False
        if getattr(self,"_prepared",None): raise RuntimeError("Shortcut rebind already in progress")
        desired=self._binding_entries(code,mods,masks)
        additions=desired-self.entries
        self.gate.reset()
        self._prepared=(accelerator,sym,mods,code,masks,names,desired,additions)
        try:
            self._grab_entries(additions)
            if hasattr(self.backend,"sync"): self.backend.sync()
            self._drain_events()
        except Exception:
            self._ungrab_entries(additions)
            if hasattr(self.backend,"sync"): self.backend.sync()
            self._prepared=None
            raise
        return True

    def commit_rebind(self):
        if not getattr(self,"_prepared",None): return
        accelerator,sym,mods,code,masks,names,desired,_additions=self._prepared
        removals=self.entries-desired
        self._ungrab_entries(removals)
        if hasattr(self.backend,"sync"): self.backend.sync()
        self._drain_events()
        self.accelerator,self.keysym,self.modifier_names,self.required,self.keycode,self.lock_masks=accelerator,sym,names,mods,code,masks
        self.entries=desired
        self._prepared=None
        self.gate.reset()
        self.healthy=True; self._notify_status()

    def rollback_rebind(self):
        if getattr(self,"_prepared",None):
            _accelerator,_sym,_mods,_code,_masks,_names,_desired,additions=self._prepared
            self._ungrab_entries(additions)
            if hasattr(self.backend,"sync"): self.backend.sync()
            self._drain_events()
            self._prepared=None

    def rebind(self, accelerator):
        changed=self.prepare_rebind(accelerator)
        if changed:
            try:self.commit_rebind()
            except Exception:self.rollback_rebind();raise
        return changed

    def _mapping_changed(self):
        # MappingNotify invalidates any in-flight physical cycle, even if remapping fails.
        self.gate.reset()
        newcode=self.backend.keycode(self.keysym)
        _require_keycode(newcode)
        required=self.backend.modifier_mask(self.modifier_names) if hasattr(self.backend,"modifier_mask") else self.required
        masks=self.backend.lock_masks()
        old=(self.keycode,self.required,self.lock_masks)
        desired=self._binding_entries(newcode,required,masks)
        old_entries=self.entries
        if desired==old_entries:
            self.healthy=True; self._notify_status()
            return
        self.gate.reset()
        if hasattr(self.backend,"update_grabs"):
            self.backend.update_grabs(old[0],old[1],old[2],newcode,required,masks)
        else:
            additions=desired-old_entries
            self._grab_entries(additions)
            try: self._ungrab_entries(old_entries-desired)
            except Exception:
                self._ungrab_entries(additions); raise
        self.keycode,self.required,self.lock_masks=newcode,required,masks
        self.entries=desired
        self.healthy=True; self._notify_status()

    def _drain_events(self):
        processed=False
        while self.backend.pending():
            processed=True
            event=self.backend.next_event()
            if event.type==34:
                try:
                    self.backend.refresh_mapping(event.xmapping)
                    self._mapping_changed()
                except Exception as error:
                    self.healthy=False; self._notify_status()
                    if self.on_error: self.on_error(str(error))
                continue
            if event.type not in (2,3) or getattr(self,"_prepared",None): continue
            e=event.xkey
            if e.keycode!=self.keycode: continue
            if event.type==2: self.gate.press(e.state,self.required)
            else: self.gate.release()
        return processed

    def _ready(self, _fd, condition):
        if self.closed: return False
        self._drain_events()
        return bool(condition & self.glib.IO_IN)

    def _poll_release(self):
        if self.closed:return False
        key_down=self.backend.key_is_down(self.keycode)
        modifiers_down=self.backend.modifiers_down()
        # XQueryKeymap/XSync may pull events into Xlib without keeping the fd readable.
        if self._drain_events(): return True
        self.gate.poll(key_down,modifiers_down)
        return True

    def close(self):
        if self.closed:return
        self.closed=True
        if self.gate: self.gate.close()
        for name in ("source","poll_source"):
            source=getattr(self,name,None)
            if source:
                try:self.glib.source_remove(source)
                except Exception:pass
                setattr(self,name,None)
        if self.backend:self.backend.close(); self.backend=None


class NativeX11Backend:
    def __init__(self, display=None):
        name=ctypes.util.find_library("X11")
        if not name:raise RuntimeError("X11 library unavailable")
        self.x=ctypes.CDLL(name); self._signatures(); self.display=self.x.XOpenDisplay(display)
        if not self.display:raise RuntimeError("Cannot connect to X11")
        self.root=self.x.XDefaultRootWindow(self.display)
    def _signatures(self):
        x=self.x
        for name,args,res in (
          ("XOpenDisplay",[ctypes.c_char_p],ctypes.c_void_p),("XCloseDisplay",[ctypes.c_void_p],ctypes.c_int),
          ("XDefaultRootWindow",[ctypes.c_void_p],ctypes.c_ulong),("XKeysymToKeycode",[ctypes.c_void_p,ctypes.c_ulong],ctypes.c_ubyte),
          ("XGrabKey",[ctypes.c_void_p,ctypes.c_int,ctypes.c_uint,ctypes.c_ulong,ctypes.c_int,ctypes.c_int,ctypes.c_int],ctypes.c_int),
          ("XUngrabKey",[ctypes.c_void_p,ctypes.c_int,ctypes.c_uint,ctypes.c_ulong],ctypes.c_int),
          ("XSync",[ctypes.c_void_p,ctypes.c_int],ctypes.c_int),("XConnectionNumber",[ctypes.c_void_p],ctypes.c_int),
          ("XPending",[ctypes.c_void_p],ctypes.c_int),("XNextEvent",[ctypes.c_void_p,ctypes.POINTER(XEvent)],ctypes.c_int),
          ("XGetModifierMapping",[ctypes.c_void_p],ctypes.c_void_p),("XFreeModifiermap",[ctypes.c_void_p],ctypes.c_int),
          ("XQueryKeymap",[ctypes.c_void_p,ctypes.c_void_p],ctypes.c_int),("XSetErrorHandler",[_X_ERROR_HANDLER],ctypes.c_void_p),
          ("XRefreshKeyboardMapping",[ctypes.POINTER(XMappingEvent)],ctypes.c_int)):
            f=getattr(x,name); f.argtypes=args; f.restype=res
    def keycode(self,sym):return int(self.x.XKeysymToKeycode(self.display,sym))
    def modifier_mask(self,names):
        class M(ctypes.Structure):_fields_=[("max",ctypes.c_int),("codes",ctypes.POINTER(ctypes.c_ubyte))]
        symbols={"CTRL":(0xffe3,0xffe4),"SHIFT":(0xffe1,0xffe2),"ALT":(0xffe9,0xffea),
                 "SUPER":(0xffeb,0xffec),"META":(0xffe7,0xffe8)}
        mapping=self.x.XGetModifierMapping(self.display)
        if not mapping:raise ShortcutError("Cannot read X11 modifier mapping")
        try:
            m=ctypes.cast(mapping,ctypes.POINTER(M)).contents
            if m.max<=0 or not m.codes:raise ShortcutError("Invalid X11 modifier mapping")
            result=0
            for name in set(names):
                codes={self.keycode(sym) for sym in symbols[name]}; codes.discard(0); found=False
                for slot in range(8):
                    if any(m.codes[slot*m.max+i] in codes for i in range(m.max)):result|=1<<slot;found=True
                if not found:raise ShortcutError("Shortcut modifier is not mapped by X11")
            return result
        finally:self.x.XFreeModifiermap(mapping)
    def lock_masks(self):
        class M(ctypes.Structure):_fields_=[("max",ctypes.c_int),("codes",ctypes.POINTER(ctypes.c_ubyte))]
        mapping=self.x.XGetModifierMapping(self.display)
        if not mapping:raise ShortcutError("Cannot read X11 modifier mapping")
        try:
            m=ctypes.cast(mapping,ctypes.POINTER(M)).contents
            if m.max<=0 or not m.codes:raise ShortcutError("Invalid X11 modifier mapping")
            caps=self.keycode(0xffe5); num=self.keycode(0xff7f); caps_mask=2; num_mask=None
            for slot in range(8):
                entries=[m.codes[slot*m.max+i] for i in range(m.max)]
                if caps and caps in entries:caps_mask|=1<<slot
                if num and num in entries:num_mask=1<<slot
            return lock_mask_variants(caps_mask,num_mask)
        finally:self.x.XFreeModifiermap(mapping)
    def grab(self,keycode,required,masks):
        _require_keycode(keycode)
        self.grab_entries({(keycode,required|lock) for lock in masks})
    def grab_entries(self,entries):
        entries=set(entries)
        for code,_mask in entries:_require_keycode(code)
        if not entries:return
        failed=[]; callback=_X_ERROR_HANDLER(lambda _d,e: failed.append(ctypes.cast(e,ctypes.POINTER(XErrorEvent)).contents.error_code) or 0)
        with _ERROR_LOCK:
            previous=self.x.XSetErrorHandler(callback)
            try:
                for code,mask in entries:self.x.XGrabKey(self.display,code,mask,self.root,0,1,1)
                self.x.XSync(self.display,0)
                if failed:
                    for code,mask in entries:self.x.XUngrabKey(self.display,code,mask,self.root)
                    self.x.XSync(self.display,0)
                    raise ShortcutError("Shortcut is already in use (X11 BadAccess)" if 10 in failed else "X11 shortcut registration failed")
            finally:self.x.XSetErrorHandler(ctypes.cast(previous,_X_ERROR_HANDLER) if previous else _X_ERROR_HANDLER())
    def ungrab(self,keycode,required,masks):
        self.ungrab_entries({(keycode,required|lock) for lock in masks})
    def ungrab_entries(self,entries):
        with _ERROR_LOCK:
            for code,mask in entries:self.x.XUngrabKey(self.display,code,mask,self.root)
            self.x.XSync(self.display,0)
    def update_grabs(self,oldcode,mods,oldmasks,newcode,newmods,newmasks):
        _require_keycode(newcode)
        old={(oldcode,mods|m) for m in oldmasks}; new={(newcode,newmods|m) for m in newmasks}
        additions=new-old; removals=old-new
        self.grab_entries(additions)
        self.ungrab_entries(removals)
    def select_mapping(self): pass  # MappingNotify is delivered independently of XSelectInput masks.
    def refresh_mapping(self,event): self.x.XRefreshKeyboardMapping(ctypes.byref(event))
    def sync(self):self.x.XSync(self.display,0)
    def fd(self):return self.x.XConnectionNumber(self.display)
    def pending(self):return self.x.XPending(self.display)
    def next_event(self):
        event=XEvent(); self.x.XNextEvent(self.display,ctypes.byref(event)); return event
    def active_window(self):
        # Active target is captured from the application's independent X11 adapter by caller when available.
        return None
    def key_is_down(self,keycode):
        bits=ctypes.create_string_buffer(32); self.x.XQueryKeymap(self.display,bits)
        return bool(bits.raw[keycode>>3] & (1<<(keycode&7)))
    def modifiers_down(self):
        # Conservatively use current X modifier mapping and keymap.
        class M(ctypes.Structure):_fields_=[("max",ctypes.c_int),("codes",ctypes.POINTER(ctypes.c_ubyte))]
        mapping=self.x.XGetModifierMapping(self.display)
        if not mapping:return True
        try:
            bits=ctypes.create_string_buffer(32); self.x.XQueryKeymap(self.display,bits); m=ctypes.cast(mapping,ctypes.POINTER(M)).contents
            return any(code and bits.raw[code>>3] & (1<<(code&7)) for code in (m.codes[i] for i in range(8*m.max)))
        finally:self.x.XFreeModifiermap(mapping)
    def close(self):
        if self.display:self.x.XCloseDisplay(self.display); self.display=None
