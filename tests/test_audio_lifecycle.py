import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from giga_pisar_dictation.audio import GstRecorder, PrivateWav
from giga_pisar_dictation.config import Config
from giga_pisar_dictation.controller import Controller, State
from giga_pisar_dictation.desktop import DesktopEffects
from giga_pisar_dictation.hotkey import PushToTalkGate


class MessageType:
    EOS = 1
    ERROR = 2


class FakeBus:
    def __init__(self, final_message): self.final_message = final_message; self.watch = 0; self.callback = None
    def add_signal_watch(self): self.watch += 1
    def remove_signal_watch(self): self.watch -= 1
    def connect(self, _name, callback): self.callback = callback


class FakeElement:
    def set_property(self, _name, _value): pass


class FakePipeline:
    def __init__(self, bus, play_result): self.bus = bus; self.states = []; self.play_result = play_result; self.eos = False; self.eos_sent = threading.Event()
    def get_by_name(self, _name): return FakeElement()
    def get_bus(self): return self.bus
    def set_state(self, state): self.states.append(state); return self.play_result if state == 1 else 0
    def send_event(self, _event):
        self.eos = True
        self.eos_sent.set()
        if self.bus.final_message is not None: self.bus.callback(self.bus, self.bus.final_message)
        return True


class FakeGst:
    class State: PLAYING = 1; NULL = 0
    class StateChangeReturn: FAILURE = -1
    class MessageType: EOS = 1; ERROR = 2
    SECOND = 1
    class ElementFactory:
        @staticmethod
        def find(_name): return object()
    class Event:
        @staticmethod
        def new_eos(): return object()
    def __init__(self, final_message, play_result=1):
        self.bus = FakeBus(final_message); self.pipeline = FakePipeline(self.bus, play_result)
    def parse_launch(self, _description): return self.pipeline


class RecorderUnitTests(unittest.TestCase):
    def test_real_gstreamer_audiotestsrc_finalizes_pcm_wav_with_glib_loop(self):
        try:
            import gi
            gi.require_version("Gst", "1.0"); gi.require_version("GLib", "2.0")
            from gi.repository import Gst, GLib
            Gst.init(None)
        except (ImportError, ValueError) as exc:
            self.skipTest(f"GStreamer GI unavailable: {exc}")
        required = ("audiotestsrc", "audioconvert", "audioresample", "wavenc", "filesink")
        if any(not Gst.ElementFactory.find(name) for name in required):
            self.skipTest("synthetic GStreamer audio plugins unavailable")

        class SyntheticGst:
            def __getattr__(self, name): return getattr(Gst, name)
            @staticmethod
            def parse_launch(_description):
                return Gst.parse_launch('audiotestsrc name=capture is-live=true ! audioconvert ! audioresample ! audio/x-raw,format=S16LE,channels=1,rate=16000 ! wavenc ! filesink name=output')

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); directory.chmod(0o700)
            wav = PrivateWav(directory)
            loop = GLib.MainLoop()
            loop_thread = threading.Thread(target=loop.run, daemon=True); loop_thread.start()
            recorder = None
            try:
                recorder = GstRecorder(wav.path, gst=SyntheticGst())
                first_buffer = threading.Event()
                source_pad = recorder.pipeline.get_by_name("capture").get_static_pad("src")
                source_pad.add_probe(Gst.PadProbeType.BUFFER, lambda *_args: (first_buffer.set(), Gst.PadProbeReturn.OK)[1])
                self.assertTrue(first_buffer.wait(3), "live audiotestsrc did not produce a buffer")
                recorder.stop(timeout_seconds=5)
            finally:
                try:
                    if recorder is not None: recorder.cancel()
                finally:
                    GLib.idle_add(loop.quit); loop_thread.join(2)
            import wave
            with wave.open(str(wav.path), "rb") as result:
                self.assertEqual((result.getnchannels(), result.getsampwidth(), result.getframerate()), (1, 2, 16000))
                self.assertGreater(result.getnframes(), 0)
            wav.remove()

    def test_eos_finalizes_and_removes_bus_watch(self):
        gst = FakeGst(SimpleNamespace(type=MessageType.EOS))
        recorder = GstRecorder(Path("unused.wav"), gst=gst)
        recorder.stop(timeout_seconds=1)
        self.assertTrue(gst.pipeline.eos)
        self.assertEqual(gst.pipeline.states, [gst.State.PLAYING, gst.State.NULL])
        self.assertEqual(gst.bus.watch, 0)
        recorder.cancel()
        self.assertEqual(gst.pipeline.states.count(gst.State.NULL), 1)

    def test_error_timeout_start_failure_and_bus_error_callback(self):
        gst = FakeGst(SimpleNamespace(type=MessageType.ERROR)); recorder = GstRecorder(Path("unused.wav"), gst=gst)
        with self.assertRaises(RuntimeError): recorder.stop(timeout_seconds=1)
        self.assertEqual(gst.bus.watch, 0)
        self.assertEqual(gst.pipeline.states[-1], gst.State.NULL)
        gst = FakeGst(None); recorder = GstRecorder(Path("unused.wav"), gst=gst)
        with self.assertRaises(RuntimeError): recorder.stop(timeout_seconds=0)
        self.assertEqual(gst.bus.watch, 0)
        with self.assertRaises(RuntimeError): recorder.stop(timeout_seconds=1)
        gst = FakeGst(None); recorder = GstRecorder(Path("unused.wav"), gst=gst)
        failures = []
        waiter = threading.Thread(target=lambda: self._capture_stop_failure(recorder, failures))
        waiter.start()
        self.assertTrue(gst.pipeline.eos_sent.wait(1), "stop did not send EOS")
        recorder.cancel(); waiter.join(1)
        self.assertFalse(waiter.is_alive()); self.assertEqual(len(failures), 1)
        recorder.cancel(); self.assertEqual(gst.bus.watch, 0)
        gst = FakeGst(None, play_result=FakeGst.StateChangeReturn.FAILURE)
        with self.assertRaises(RuntimeError): GstRecorder(Path("unused.wav"), gst=gst)
        self.assertEqual(gst.bus.watch, 0)
        errors = []; gst = FakeGst(None); recorder = GstRecorder(Path("unused.wav"), on_error=lambda: errors.append(True), gst=gst)
        gst.bus.callback(gst.bus, SimpleNamespace(type=MessageType.ERROR))
        self.assertEqual(errors, [True])
        recorder.cancel(); self.assertEqual(gst.bus.watch, 0)


    @staticmethod
    def _capture_stop_failure(recorder, failures):
        try: recorder.stop(timeout_seconds=2)
        except RuntimeError: failures.append(True)


class FakeGLib:
    SOURCE_REMOVE = 0
    def __init__(self): self.timers = {}; self.idle = []; self.removed = []; self.next_source = 1
    def timeout_add_seconds(self, seconds, callback): self.timers[1] = callback; self.seconds = seconds; return 1
    def timeout_add(self, milliseconds, callback):
        self.next_source += 1; self.milliseconds = milliseconds
        self.timers[self.next_source] = callback
        return self.next_source
    def source_remove(self, source_id): self.removed.append(source_id); self.timers.pop(source_id, None)
    def idle_add(self, callback): self.idle.append(callback); return len(self.idle)


class FakeThread:
    instances = []
    def __init__(self, target, daemon): self.target = target; self.daemon = daemon; self.instances.append(self)
    def start(self): pass
    def run(self): self.target()


class FakeRecorder:
    def __init__(self, path, _source, on_error): self.path = path; self.on_error = on_error; self.stopped = False; self.cancelled = False
    def stop(self): self.path.write_bytes(b"RIFF" + b"0" * 60); self.stopped = True
    def cancel(self): self.cancelled = True


class FakeClient:
    def __init__(self): self.calls = []
    def transcribe_async(self, path, callback, cancellable): self.calls.append((path, callback, cancellable))


class FakeClipboard:
    def __init__(self, events): self.events = events
    def shutdown(self): self.events.append("clipboard-close")


class FakeX11:
    def __init__(self, events): self.events = events
    def active_window(self): return 42
    def close(self): self.events.append("x11-close")


class Label:
    def __init__(self): self.text = ""
    def set_text(self, text): self.text = text


class View:
    def __init__(self): self.status = Label(); self.external_window = 42
    def refresh(self): pass
    def modifiers_down(self): return False


def make_effects(directory, glib=None):
    directory.mkdir(mode=0o700, exist_ok=True)
    FakeThread.instances.clear(); events = []
    view = View(); client = FakeClient(); glib = glib or FakeGLib()
    effects = DesktopEffects(view, config=Config(auto_insert=False, hotkey_enabled=False), key="fictional-test-key", client=client,
        audio_directory=directory, recorder_factory=FakeRecorder,
        clipboard=FakeClipboard(events), x11_factory=lambda: FakeX11(events),
        glib=glib, thread_factory=FakeThread)
    view.controller = Controller(effects)
    effects.view = view
    return effects, view, client, glib, events


class DesktopRecordingTests(unittest.TestCase):
    def test_five_minute_limit_discards_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start()); wav = effects.wav.path
            self.assertEqual(glib.seconds, 300)
            self.assertFalse(glib.timers[1]())
            self.assertEqual(view.controller.state, State.IDLE)
            self.assertFalse(wav.exists()); self.assertEqual(client.calls, [])
            self.assertIn("аудио удалено", view.status.text)

    def test_recording_limit_refreshes_idle_indicator_after_cancel_cleanup(self):
        from giga_pisar_dictation.gui import DesktopWindow
        class Buffer:
            def set_text(self, text): self.text = text
        class Output:
            def __init__(self): self.buffer = Buffer()
            def get_buffer(self): return self.buffer
        class Indicator:
            def set_icon_full(self, icon, _description): self.icon = icon
            def set_title(self, title): self.title = title
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, _client, _glib, _events = make_effects(Path(tmp) / "audio")
            view.output = Output(); view.indicator = Indicator()
            view.refresh = lambda: DesktopWindow.refresh(view)
            self.assertTrue(effects.command("start")["ok"])
            self.assertEqual(view.indicator.icon, "giga-pisar-dictation-recording")
            effects._recording_limit(effects.recording_generation)
            self.assertEqual(view.controller.state, State.IDLE)
            self.assertEqual(view.indicator.icon, "giga-pisar-dictation-idle")
            self.assertEqual(view.status.text, "Достигнут лимит записи в пять минут; аудио удалено")

    def test_successful_eos_flow_and_finalize_cancel_are_generation_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start()); wav = effects.wav.path
            self.assertTrue(view.controller.stop()); self.assertEqual(view.controller.state, State.FINALIZING)
            worker = FakeThread.instances[-1]; worker.run()
            callback = glib.idle.pop(); self.assertEqual(callback(), 0)
            self.assertEqual(view.controller.state, State.REQUESTING); self.assertEqual(len(client.calls), 1)
            submitted_path, response, _cancel = client.calls[0]
            self.assertEqual(submitted_path, wav); response("safe transcription", None)
            self.assertEqual(view.controller.state, State.RESULT); self.assertFalse(wav.exists())

        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start()); old_wav = effects.wav.path
            self.assertTrue(view.controller.stop()); worker = FakeThread.instances[-1]
            self.assertTrue(view.controller.cancel()); self.assertFalse(old_wav.exists())
            self.assertTrue(view.controller.start()); replacement_wav = effects.wav.path
            worker.run()
            self.assertEqual(glib.idle.pop()(), 0)
            self.assertEqual(view.controller.state, State.RECORDING)
            self.assertTrue(replacement_wav.exists()); self.assertEqual(client.calls, [])
            view.controller.cancel()

    def test_ptt_release_keeps_capture_for_300ms_then_finalizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start())
            owner=effects.recording_generation; effects._push_to_talk_owner=owner
            effects._push_to_talk_stop(owner)
            self.assertEqual(glib.milliseconds,300)
            self.assertEqual(view.controller.state,State.RECORDING)
            self.assertFalse(effects.recorder.stopped)
            tail_source=effects._ptt_tail_source
            self.assertEqual(glib.timers[tail_source](),0)
            self.assertEqual(view.controller.state,State.FINALIZING)
            FakeThread.instances[-1].run(); glib.idle.pop()()
            self.assertEqual(view.controller.state,State.REQUESTING)
            self.assertEqual(len(client.calls),1)

    def test_ptt_mapping_invalidation_after_release_cancels_tail_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            gate=PushToTalkGate(lambda:73,effects._push_to_talk_start,
                                effects._push_to_talk_stop,effects._invalidate_hold)
            gate.press(); owner=gate.owner
            gate.release(); self.assertTrue(gate.poll(False))
            stale_callback=glib.timers[effects._ptt_tail_source]
            self.assertEqual(effects._ptt_tail_owner,owner)
            gate.reset()  # MappingNotify resets the physical hold cycle.
            stale_callback()
            self.assertEqual(view.controller.state,State.IDLE)
            self.assertEqual(client.calls,[])
            self.assertIsNone(effects._ptt_tail_source)

    def test_ptt_close_after_release_cancels_tail_without_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, _ = make_effects(Path(tmp) / "audio")
            gate=PushToTalkGate(lambda:73,effects._push_to_talk_start,
                                effects._push_to_talk_stop,effects._invalidate_hold)
            gate.press(); gate.release(); self.assertTrue(gate.poll(False))
            stale_callback=glib.timers[effects._ptt_tail_source]
            gate.close()
            stale_callback()
            self.assertEqual(view.controller.state,State.IDLE)
            self.assertEqual(client.calls,[])
            self.assertIsNone(effects._ptt_tail_source)

    def test_ptt_tail_repeat_press_cancels_tail_and_reuses_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, _client, glib, _ = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start())
            owner=effects.recording_generation; effects._push_to_talk_owner=owner
            effects._push_to_talk_stop(owner); old_source=effects._ptt_tail_source
            self.assertEqual(effects._push_to_talk_start(42),owner)
            self.assertIn(old_source,glib.removed)
            self.assertEqual(view.controller.state,State.RECORDING)
            self.assertIsNone(effects._ptt_tail_owner)
            self.assertEqual(glib.timers.get(old_source),None)
            effects._push_to_talk_stop(owner)
            self.assertEqual(glib.milliseconds,300)
            effects.command("cancel")

    def test_ptt_tail_terminal_paths_and_stale_callback_cannot_stop_recording(self):
        for terminal in ("cancel","error","limit","shutdown","generation"):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as tmp:
                effects, view, _client, glib, _ = make_effects(Path(tmp) / "audio")
                self.assertTrue(view.controller.start())
                owner=effects.recording_generation; effects._push_to_talk_owner=owner
                effects._push_to_talk_stop(owner); callback=glib.timers[effects._ptt_tail_source]
                if terminal=="cancel":view.controller.cancel()
                elif terminal=="error":effects._audio_error(owner)
                elif terminal=="limit":effects._recording_limit(owner)
                elif terminal=="shutdown":effects.shutdown()
                else:effects.recording_generation+=1
                callback()
                if terminal=="generation":self.assertEqual(view.controller.state,State.RECORDING)
                else:self.assertNotEqual(view.controller.state,State.FINALIZING)
                self.assertNotEqual(view.controller.state,State.REQUESTING)

    def test_shutdown_during_finalization_discards_late_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, glib, events = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start()); wav = effects.wav.path
            self.assertTrue(view.controller.stop()); worker = FakeThread.instances[-1]
            effects.shutdown()
            self.assertFalse(wav.exists())
            worker.run()
            self.assertEqual(glib.idle.pop()(), 0)
            self.assertEqual(view.controller.state, State.IDLE)
            self.assertEqual(client.calls, [])
            self.assertEqual(events, ["clipboard-close", "x11-close"])

    def test_shutdown_during_request_ignores_late_transcription_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, client, _glib, events = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start())
            self.assertTrue(view.controller.stop())
            worker = FakeThread.instances[-1]; worker.run(); _glib.idle.pop()()
            self.assertEqual(view.controller.state, State.REQUESTING)
            _path, callback, _cancellable = client.calls[0]
            effects.shutdown(); effects.shutdown()
            callback("must be ignored", None)
            self.assertEqual(view.controller.state, State.IDLE)
            self.assertIsNone(view.controller.text)
            self.assertEqual(events, ["clipboard-close", "x11-close"])

    def test_shutdown_cleans_capture_and_closes_clipboard_before_x11(self):
        with tempfile.TemporaryDirectory() as tmp:
            effects, view, _client, _glib, events = make_effects(Path(tmp) / "audio")
            self.assertTrue(view.controller.start()); wav = effects.wav.path; recorder = effects.recorder
            effects.shutdown()
            self.assertTrue(recorder.cancelled); self.assertFalse(wav.exists())
            self.assertEqual(events, ["clipboard-close", "x11-close"])


if __name__ == "__main__": unittest.main()
