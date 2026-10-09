"""UI-independent dictation state machine."""
from __future__ import annotations

from enum import Enum, auto
from typing import Protocol


class State(Enum):
    IDLE = auto()
    RECORDING = auto()
    FINALIZING = auto()
    REQUESTING = auto()
    RESULT = auto()
    ERROR = auto()


class Effects(Protocol):
    def start_recording(self) -> None: ...
    def finalize_recording(self) -> None: ...
    def cancel_recording(self) -> None: ...
    def submit_audio(self) -> None: ...
    def cancel_request(self) -> None: ...
    def remove_audio(self) -> None: ...


class Controller:
    def __init__(self, effects: Effects):
        self.effects = effects
        self.state = State.IDLE
        self.text: str | None = None
        self.message = "Ready"
        self._request_generation = 0

    def start(self) -> bool:
        if self.state not in (State.IDLE, State.RESULT, State.ERROR):
            self.message = "Busy"
            return False
        self.text = None
        self.message = "Recording"
        self.state = State.RECORDING
        try:
            self.effects.start_recording()
        except Exception:
            self.fail("Audio recording failed")
            return False
        return True

    def stop(self) -> bool:
        if self.state != State.RECORDING:
            return False
        self.state = State.FINALIZING
        self.message = "Finalizing audio"
        try:
            self.effects.finalize_recording()
        except Exception:
            self.fail("Audio finalization failed")
            return False
        return True

    def audio_finalized(self, valid: bool) -> bool:
        if self.state != State.FINALIZING:
            return False
        if not valid:
            self.fail("Audio is empty or invalid")
            return False
        self.state = State.REQUESTING
        self.message = "Recognizing"
        self._request_generation += 1
        try:
            self.effects.submit_audio()
        except Exception:
            self.fail("Unable to submit audio")
            return False
        return True

    def response(self, text: str, generation: int | None = None) -> bool:
        if self.state != State.REQUESTING or (generation is not None and generation != self._request_generation):
            return False
        if not text.strip():
            self.fail("Server returned an empty transcription")
            return False
        self.text = text
        self.state = State.RESULT
        self.message = "Transcription ready"
        self.effects.remove_audio()
        return True

    def fail(self, safe_message: str) -> None:
        if self.state == State.REQUESTING:
            self._request_generation += 1
        self.state = State.ERROR
        self.message = safe_message
        self.text = None
        try:
            self.effects.remove_audio()
        except Exception:
            pass

    def cancel(self) -> bool:
        if self.state in (State.IDLE, State.RESULT, State.ERROR):
            return False
        if self.state == State.REQUESTING:
            self._request_generation += 1
            self.effects.cancel_request()
        else:
            self.effects.cancel_recording()
        try:
            self.effects.remove_audio()
        except Exception:
            pass
        self.state = State.IDLE
        self.message = "Cancelled"
        self.text = None
        return True

    def toggle(self) -> bool:
        return self.stop() if self.state == State.RECORDING else self.start()
