"""Spoken replies. Two voice families, both local and offline:

- Windows voices (SAPI and the newer OneCore voices): built in, instant.
- Natural voices (Kokoro-82M via kokoro-onnx, Apache-2.0 model): very human-sounding, ~50 voices in English
  (US/UK), Hindi and more. Optional pack in artifacts/models/kokoro (model + voices file). Its pronunciation
  helper (espeak-ng) is GPL-licensed: keep it an optional download if ORION is ever distributed.

Voice ids: "win:<name>" or "kokoro:<voice>". Speech is generated sentence by sentence so ORION starts talking
quickly; a new sentence or stop() interrupts whatever is playing.
"""

from __future__ import annotations

import queue
import re
import threading
from pathlib import Path

from orion import resources

KOKORO_DIR = resources.path("artifacts", "models", "kokoro")
KOKORO_MODEL, KOKORO_VOICES = "kokoro-v1.0.int8.onnx", "voices-v1.0.bin"
_LANG = {"a": ("en-us", "American English"), "b": ("en-gb", "British English"), "h": ("hi", "Hindi"),
         "e": ("es", "Spanish"), "f": ("fr-fr", "French"), "i": ("it", "Italian"), "p": ("pt-br", "Portuguese")}
ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"
DEFAULT_VOICE = "kokoro:af_heart"


def kokoro_available() -> bool:
    return (KOKORO_DIR / KOKORO_MODEL).exists() and (KOKORO_DIR / KOKORO_VOICES).exists()


def list_voices() -> list[dict[str, str]]:
    """Every voice ORION can use on this computer, natural voices first."""
    out: list[dict[str, str]] = []
    if kokoro_available():
        try:
            import numpy as np
            names = sorted(np.load(KOKORO_DIR / KOKORO_VOICES).files)
        except Exception:  # noqa: BLE001
            names = []
        for n in names:
            lang = _LANG.get(n[0])
            if lang is None or len(n) < 4 or n[1] not in "fm":
                continue
            out.append({"id": f"kokoro:{n}", "name": n[3:].replace("_", " ").title(), "family": "Natural",
                        "accent": lang[1], "gender": "Female" if n[1] == "f" else "Male"})
    out += _windows_voices()
    return out


def _windows_voices() -> list[dict[str, str]]:
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()
    seen, out = set(), []
    try:
        v = comtypes.client.CreateObject("SAPI.SpVoice")
        sources = [v.GetVoices()]
        try:
            cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
            cat.SetId(ONECORE, False)
            sources.append(cat.EnumerateTokens())
        except Exception:  # noqa: BLE001 - OneCore voices are optional
            pass
        for toks in sources:
            for i in range(toks.Count):
                d = toks.Item(i).GetDescription()
                if d in seen:
                    continue
                seen.add(d)
                name = d.replace("Microsoft ", "").split(" - ")[0].replace(" Desktop", "")
                accent = d.split(" - ")[1] if " - " in d else ""
                if any(o["name"] == name and o["accent"] == accent for o in out):
                    continue   # the same voice offered by both SAPI and OneCore
                out.append({"id": f"win:{d}", "name": name, "family": "Windows", "accent": accent, "gender": ""})
    except Exception:  # noqa: BLE001
        pass
    return out


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p for p in parts if p.strip()]


class Speaker:
    """Speaks on its own thread. say() never blocks; stop() silences immediately."""

    def __init__(self, voice: str = DEFAULT_VOICE, rate: float = 1.0):
        self.voice, self.rate = voice, rate
        self._q: queue.Queue = queue.Queue()
        self._gen = 0                 # bumped by say()/stop(): stale sentences are dropped
        self._kokoro = None
        self._thread = threading.Thread(target=self._loop, name="orion-voice", daemon=True)
        self._thread.start()

    def configure(self, voice: str | None = None, rate: float | None = None) -> None:
        if voice:
            self.voice = voice
        if rate:
            self.rate = max(0.5, min(2.0, float(rate)))

    # --- public -------------------------------------------------------------------------------
    def say(self, text: str) -> None:
        self._gen += 1
        self._stop_audio()
        for s in sentences(text):
            self._q.put(("say", s, self._gen, None))

    def say_and_wait(self, text: str, timeout: float = 60) -> None:
        self._gen += 1
        done = threading.Event()
        parts = sentences(text) or [""]
        for i, s in enumerate(parts):
            self._q.put(("say", s, self._gen, done if i == len(parts) - 1 else None))
        done.wait(timeout)

    def stop(self) -> None:
        self._gen += 1
        self._stop_audio()

    def to_wav(self, text: str, path: Path) -> Path:
        """Render speech to a .wav file (Windows voice; used to test speech recognition without a person)."""
        done = threading.Event()
        self._q.put(("file", (text, str(path)), self._gen, done))
        done.wait(60)
        return path

    def close(self) -> None:
        self._q.put(None)

    # --- worker -------------------------------------------------------------------------------
    def _stop_audio(self) -> None:
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:  # noqa: BLE001
            pass
        if getattr(self, "_sapi", None) is not None:
            self._sapi_purge = True

    def _loop(self) -> None:
        import comtypes
        import comtypes.client
        comtypes.CoInitialize()
        self._sapi = comtypes.client.CreateObject("SAPI.SpVoice")
        self._sapi_purge = False
        while True:
            job = self._q.get()
            if job is None:
                break
            kind, text, gen, done = job
            try:
                if kind == "file":
                    self._to_file(*text)
                elif gen == self._gen and text:
                    if self.voice.startswith("kokoro:") and kokoro_available():
                        self._say_kokoro(text, gen)
                    else:
                        self._say_windows(text, gen)
            except Exception:  # noqa: BLE001 - a voice problem never stops ORION
                pass
            finally:
                if done is not None:
                    done.set()

    def _say_kokoro(self, text: str, gen: int) -> None:
        import sounddevice as sd
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(KOKORO_DIR / KOKORO_MODEL), str(KOKORO_DIR / KOKORO_VOICES))
        name = self.voice.split(":", 1)[1]
        audio, sr = self._kokoro.create(text, voice=name, speed=self.rate, lang=_LANG.get(name[0], ("en-us",))[0])
        if gen != self._gen:
            return                      # interrupted while generating
        sd.play(audio, sr)
        sd.wait()

    def _pick_windows_voice(self) -> None:
        want = self.voice.split(":", 1)[1] if self.voice.startswith("win:") else "Zira"
        import comtypes.client
        sources = [self._sapi.GetVoices()]
        try:
            cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
            cat.SetId(ONECORE, False)
            sources.append(cat.EnumerateTokens())
        except Exception:  # noqa: BLE001
            pass
        for toks in sources:
            for i in range(toks.Count):
                if want.lower() in toks.Item(i).GetDescription().lower():
                    self._sapi.Voice = toks.Item(i)
                    return

    def _say_windows(self, text: str, gen: int) -> None:
        self._pick_windows_voice()
        self._sapi.Rate = int(round((self.rate - 1.0) * 10))
        self._sapi_purge = False
        self._sapi.Speak(text, 1)       # async, so stop() can cut it short
        while not self._sapi.WaitUntilDone(100):
            if self._sapi_purge or gen != self._gen:
                self._sapi.Speak("", 1 | 2)
                return

    def _to_file(self, text: str, path: str) -> None:
        import comtypes.client
        stream = comtypes.client.CreateObject("SAPI.SpFileStream")
        stream.Open(path, 3)
        old = self._sapi.AudioOutputStream
        self._sapi.AudioOutputStream = stream
        self._sapi.Speak(text)
        stream.Close()
        self._sapi.AudioOutputStream = old
