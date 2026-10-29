"""ORION's voice: push-to-talk speech recognition (local Whisper) and spoken replies (Windows voices).

Everything runs on this computer. The microphone is open only while push-to-talk is held; audio is kept
in memory and never saved.
"""

from orion.voice.speak import Speaker
from orion.voice.listen import Recorder, Transcriber

__all__ = ["Recorder", "Speaker", "Transcriber"]
