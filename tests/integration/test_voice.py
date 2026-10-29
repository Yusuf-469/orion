"""Voice round trip without a person: Windows speech -> .wav -> local Whisper. Marked `real` (model on disk)."""

import sys

import pytest

pytestmark = [pytest.mark.real, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]


@pytest.fixture(scope="module")
def voice():
    from orion.voice import Speaker, Transcriber
    s, t = Speaker(), Transcriber()
    t.warm_up()
    yield s, t
    s.close()


@pytest.mark.parametrize("sentence,must", [
    ("Fill in the feedback form and submit it.", ["feedback form", "submit"]),
    ("Compare the Aurora X1 with the Nimbus Pro.", ["compare", "nimbus pro"]),
    ("Stop.", ["stop"]),
])
def test_spoken_command_is_understood(voice, tmp_path, sentence, must):
    s, t = voice
    heard = t.transcribe(s.to_wav(sentence, tmp_path / "x.wav")).lower()
    assert all(m in heard for m in must), heard


def test_a_tap_is_not_speech(voice):
    import numpy as np
    assert voice[1].transcribe(np.zeros(1000, dtype=np.float32)) == ""
