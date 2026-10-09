"""Private WAV lifecycle and GStreamer capture adapter."""
from __future__ import annotations
import os
import stat
import tempfile
import threading
from pathlib import Path


def private_audio_directory():
    temporary_root = Path("/tmp")
    root_stat = temporary_root.lstat()
    if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_uid != 0 or not root_stat.st_mode & stat.S_ISVTX:
        raise PermissionError("Unsafe system temporary directory")
    directory = temporary_root / f"giga-pisar-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    st = directory.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
        raise PermissionError("Unsafe audio directory")
    return directory


class PrivateWav:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(tempfile.mkdtemp(prefix="giga-pisar-")) if directory is None else directory
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = self.directory.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
            raise PermissionError("Unsafe audio directory")
        if stat.S_IMODE(st.st_mode) != 0o700: raise PermissionError("Audio directory must have mode 0700")
        fd, name = tempfile.mkstemp(prefix="recording-", suffix=".wav", dir=self.directory)
        os.fchmod(fd, 0o600); os.close(fd)
        self.path = Path(name)

    def remove(self):
        try: self.path.unlink()
        except FileNotFoundError: pass

    @staticmethod
    def cleanup_stale(directory: Path):
        st = directory.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o700:
            raise PermissionError("Unsafe audio directory")
        for p in directory.iterdir():
            try:
                item = p.lstat()
                if stat.S_ISREG(item.st_mode) and item.st_uid == os.getuid() and p.name.startswith("recording-") and p.suffix == ".wav": p.unlink()
            except FileNotFoundError: pass


class GstRecorder:
    REQUIRED = ("pulsesrc", "audioconvert", "audioresample", "wavenc", "filesink")

    def __init__(self, path: Path, source: str = "", on_error=None, gst=None):
        if gst is None:
            import gi
            gi.require_version("Gst", "1.0")
            from gi.repository import Gst
            Gst.init(None)
        else:
            Gst = gst
        self.Gst = Gst; self.on_error = on_error
        missing = [name for name in self.REQUIRED if not Gst.ElementFactory.find(name)]
        if missing: raise RuntimeError("Required GStreamer audio plugins are unavailable")
        pipeline = 'pulsesrc name=capture ! audioconvert ! audioresample ! audio/x-raw,format=S16LE,channels=1,rate=16000 ! wavenc ! filesink name=output'
        self.pipeline = Gst.parse_launch(pipeline)
        if source: self.pipeline.get_by_name("capture").set_property("device", source)
        self.pipeline.get_by_name("output").set_property("location", str(path))
        self.bus = self.pipeline.get_bus()
        self._condition = threading.Condition()
        self._message = None
        self._cancelled = False
        self._failed = False
        self.closed = False
        # The GLib signal watch is the sole bus consumer; stop waits on its notification.
        self.bus.add_signal_watch()
        self.bus.connect("message", self._on_bus_message)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.pipeline.set_state(Gst.State.NULL); self.bus.remove_signal_watch(); self.closed = True
            raise RuntimeError("Unable to start audio capture")

    def _on_bus_message(self, _bus, message):
        message_type = message.type
        if message_type not in (self.Gst.MessageType.EOS, self.Gst.MessageType.ERROR):
            return
        with self._condition:
            accepted = not self.closed
            if self._message is None and accepted:
                self._message = message
                self._condition.notify_all()
        if accepted and message_type == self.Gst.MessageType.ERROR and self.on_error:
            self.on_error()

    def _cleanup(self):
        if self.closed:
            return
        self.closed = True
        self.pipeline.set_state(self.Gst.State.NULL)
        self.bus.remove_signal_watch()

    def stop(self, timeout_seconds: int = 10):
        with self._condition:
            if self.closed:
                if self._failed: raise RuntimeError("Unable to finalize WAV recording")
                return
            self.pipeline.send_event(self.Gst.Event.new_eos())
            ready = self._condition.wait_for(lambda: self._message is not None or self._cancelled, timeout_seconds)
            message = self._message
            cancelled = self._cancelled
            failed = cancelled or not ready or message is None or message.type == self.Gst.MessageType.ERROR
            self._failed = failed
            self._cleanup()
        if failed:
            raise RuntimeError("Unable to finalize WAV recording")

    def cancel(self):
        with self._condition:
            if self.closed: return
            self._cancelled = True
            self._condition.notify_all()
            self._cleanup()
