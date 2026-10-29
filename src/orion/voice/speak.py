"""Spoken replies through the voices built into Windows (SAPI). No download, works offline."""

from __future__ import annotations

import queue
import threading
from pathlib import Path


class Speaker:
    """Speaks on its own thread (SAPI is a COM object and must stay on the thread that made it)."""

    def __init__(self, voice: str = "Zira", rate: int = 1):
        self.voice_hint, self.rate = voice, rate
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="orion-voice", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        voices = v.GetVoices()
        for i in range(voices.Count):
            if self.voice_hint.lower() in voices.Item(i).GetDescription().lower():
                v.Voice = voices.Item(i)
        v.Rate = self.rate
        while True:
            job = self._q.get()
            if job is None:
                break
            kind, text, done = job
            try:
                if kind == "say":
                    v.Speak(text, 1 | 2)          # async + purge anything still being said
                    v.WaitUntilDone(-1)
                elif kind == "stop":
                    v.Speak("", 1 | 2)
                elif kind == "file":
                    stream = comtypes.client.CreateObject("SAPI.SpFileStream")
                    stream.Open(text[1], 3)       # SSFMCreateForWrite
                    old = v.AudioOutputStream
                    v.AudioOutputStream = stream
                    v.Speak(text[0])
                    stream.Close()
                    v.AudioOutputStream = old
            finally:
                if done is not None:
                    done.set()

    def say(self, text: str) -> None:
        """Speak without blocking; a new sentence interrupts the previous one."""
        self._q.put(("say", text, None))

    def say_and_wait(self, text: str, timeout: float = 60) -> None:
        done = threading.Event()
        self._q.put(("say", text, done))
        done.wait(timeout)

    def stop(self) -> None:
        self._q.put(("stop", "", None))

    def to_wav(self, text: str, path: Path) -> Path:
        """Render speech to a .wav file (used to test speech recognition without a person)."""
        done = threading.Event()
        self._q.put(("file", (text, str(path)), done))
        done.wait(60)
        return path

    def close(self) -> None:
        self._q.put(None)
