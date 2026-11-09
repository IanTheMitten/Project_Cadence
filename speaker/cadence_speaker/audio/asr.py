import numpy as np
from faster_whisper import WhisperModel

NO_SPEECH_PROB_MAX = 0.6  # drop Whisper segments it isn't confident are speech


def _pcm16_bytes_to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


class Asr:
    def __init__(self, model_name: str = "small.en", beam_size: int = 5):
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")
        self.beam_size = beam_size

    def transcribe(self, pcm: bytes) -> str:
        audio = _pcm16_bytes_to_float32(pcm)
        # vad_filter re-checks with faster-whisper's own (Silero) VAD and
        # drops any non-speech stretch before decoding; no_speech_prob is a
        # second, per-segment guard against Whisper hallucinating filler
        # text ("Thank you.", "Thanks for watching!") on noise it still
        # decided to transcribe.
        segments, _info = self.model.transcribe(audio, beam_size=self.beam_size, vad_filter=True)
        segments = list(segments)
        text = "".join(
            seg.text for seg in segments if seg.no_speech_prob < NO_SPEECH_PROB_MAX
        ).strip()
        return text
