"""Push-to-talk: record from the microphone while held, then transcribe locally with Whisper."""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

RATE = 16_000            # Whisper's sample rate
MAX_SECONDS = 60


class Recorder:
    """Records only between start() and stop(); audio stays in memory."""

    def __init__(self, device: int | None = None):
        self.device = device
        self._chunks: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        import sounddevice as sd
        with self._lock:
            if self._stream is not None:
                return
            self._chunks = []

            def cb(data, frames, t, status):
                if sum(len(c) for c in self._chunks) < RATE * MAX_SECONDS:
                    self._chunks.append(data[:, 0].copy())
            self._stream = sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=cb,
                                          device=self.device)
            self._stream.start()

    def stop(self) -> np.ndarray:
        with self._lock:
            if self._stream is None:
                return np.zeros(0, dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            return np.concatenate(self._chunks) if self._chunks else np.zeros(0, dtype=np.float32)


class Transcriber:
    """faster-whisper (MIT), loaded on first use. Tries the GPU, falls back to the CPU."""

    def __init__(self, model: str = "small.en"):
        self.model_name = model
        self._model = None
        self.device = ""

    def _load(self, cpu: bool = False):
        if self._model is None or (cpu and self.device != "cpu"):
            from faster_whisper import WhisperModel
            if not cpu:
                _cuda_dlls_from_torch()
                try:
                    self._model = WhisperModel(self.model_name, device="cuda", compute_type="float16")
                    # Encode real (noise) audio: silence is skipped and would not reveal missing CUDA libraries.
                    list(self._model.transcribe(np.random.default_rng(0).normal(0, 0.1, RATE).astype(np.float32),
                                                language="en")[0])
                    self.device = "cuda"
                    return self._model
                except Exception:  # noqa: BLE001
                    pass
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self.device = "cpu"
        return self._model

    def warm_up(self) -> str:
        self._load()
        return self.device

    def transcribe(self, audio: np.ndarray | str | Path) -> str:
        if isinstance(audio, np.ndarray) and len(audio) < RATE // 4:
            return ""   # under a quarter second: a tap, not speech
        src = audio if not isinstance(audio, Path) else str(audio)
        try:
            segments, _ = self._load().transcribe(src, language="en", beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()
        except RuntimeError:
            if self.device == "cpu":
                raise
            segments, _ = self._load(cpu=True).transcribe(src, language="en", beam_size=1, vad_filter=True)
            return " ".join(s.text.strip() for s in segments).strip()


def _cuda_dlls_from_torch() -> None:
    """PyTorch's CUDA build ships cuBLAS/cuDNN; let faster-whisper find them (no separate CUDA install)."""
    import importlib.util
    import os
    spec = importlib.util.find_spec("torch")
    if spec and spec.origin:
        lib = Path(spec.origin).parent / "lib"
        if lib.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(lib))
            os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
