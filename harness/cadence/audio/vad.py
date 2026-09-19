import webrtcvad

MIC_SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = MIC_SAMPLE_RATE * FRAME_MS // 1000 * 2  # 16-bit mono

VAD_START_FRAMES = 10   # ~300ms of sustained speech opens an utterance
VAD_END_FRAMES = 16     # ~480ms of silence closes one
MIN_UTTERANCE_BYTES = FRAME_BYTES * 16  # ~480ms, drop shorter blips/noise


class VadSegmenter:
    """Extracted from tools/voice_chat_host.py's mic_server frame loop. Owns
    no socket and no mute window -- the mute logic stays behind in the legacy
    host because ducking replaced it."""

    def __init__(self):
        self.vad = webrtcvad.Vad(3)  # most aggressive (least sensitive to non-speech noise)
        self.buf = b""
        self.pre_roll = []
        self.speech_frames = []
        self.in_speech = False
        self.voiced_run = 0
        self.silent_run = 0

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        utterances = []
        while len(self.buf) >= FRAME_BYTES:
            frame, self.buf = self.buf[:FRAME_BYTES], self.buf[FRAME_BYTES:]
            is_speech = self.vad.is_speech(frame, MIC_SAMPLE_RATE)
            if is_speech:
                self.voiced_run += 1
                self.silent_run = 0
            else:
                self.silent_run += 1
                self.voiced_run = 0

            if self.in_speech:
                self.speech_frames.append(frame)
                if self.silent_run >= VAD_END_FRAMES:
                    self.in_speech = False
                    utterance = b"".join(self.speech_frames)
                    self.speech_frames = []
                    if len(utterance) >= MIN_UTTERANCE_BYTES:
                        utterances.append(utterance)
            else:
                self.pre_roll.append(frame)
                self.pre_roll = self.pre_roll[-VAD_START_FRAMES:]
                if self.voiced_run >= VAD_START_FRAMES:
                    self.in_speech = True
                    self.speech_frames = list(self.pre_roll)
        return utterances
