#!/usr/bin/env python3
"""Realtime voice conversation host for the voice_chat/ firmware.

Two servers run side by side:
- A raw TCP socket on MIC_PORT that voice_chat.c streams 16kHz/16-bit/mono
  mic PCM into continuously.
- An HTTP server on HTTP_PORT serving GET /speak_stream: voice_chat.c holds
  one long-lived GET open at a time, one per assistant turn. This handler
  blocks until the pipeline below has a turn ready, then streams raw s16le
  44100Hz stereo PCM chunked into the response body as TTS produces it
  (sentence by sentence, so playback can start before the full reply has
  finished generating) and ends the response when the turn is done.

Pipeline, run sequentially on one worker thread (single conversation at a
time): VAD segments the mic stream into utterances -> faster-whisper
transcribes -> mlx_lm streams a reply -> a sentence chunker (ported from
lumi's crates/cadence-gateway/src/voice/chunker.rs) cuts it into sentences
as they complete -> Kokoro synthesizes each sentence -> resampled and
streamed to /speak_stream.

No real echo cancellation: instead, the mic is gated off (VAD skipped, frames
dropped) for the estimated duration of the board's own playback after each
turn (MUTE_MARGIN_S padding on top), so the assistant can't hear and
transcribe itself. A loud enough echo bleeding past that window is still
possible -- this is a blunt mitigation, not real AEC.

Setup:
    brew install espeak-ng
    pip install -r tools/requirements-voice.txt
    # Kokoro model files (not fetched by this script):
    wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
    wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin
    # put both next to this script, or point KOKORO_MODEL_PATH / KOKORO_VOICES_PATH below at them.
"""
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import webrtcvad
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro
from kokoro_onnx.config import SAMPLE_RATE as KOKORO_SAMPLE_RATE
from mlx_lm import load, stream_generate
from scipy.signal import resample_poly

MIC_LISTEN_PORT = 8766
HTTP_LISTEN_PORT = 8767

MIC_SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = MIC_SAMPLE_RATE * FRAME_MS // 1000 * 2  # 16-bit mono

VAD_START_FRAMES = 10   # ~300ms of sustained speech opens an utterance
VAD_END_FRAMES = 16     # ~480ms of silence closes one
MIN_UTTERANCE_BYTES = FRAME_BYTES * 16  # ~480ms, drop shorter blips/noise

# No echo cancellation: while the board is playing the assistant's reply,
# ignore mic frames entirely (skip VAD, don't accumulate) instead of trying
# to tell the board's own voice apart from the user's.
MUTE_MARGIN_S = 0.8  # extra pad past the last chunk's estimated playback time

SPK_SAMPLE_RATE = 44100
KEEPALIVE_TIMEOUT_S = 15  # how long /speak_stream waits before sending a
                          # silence heartbeat to keep the client's HTTP
                          # transport read from timing out while idle
KEEPALIVE_MS = 50

ASR_MODEL_SIZE = "small.en"
NO_SPEECH_PROB_MAX = 0.6  # drop Whisper segments it isn't confident are speech
LLM_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"
SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Keep replies short and "
    "conversational, a sentence or two, since they are spoken aloud."
)

TTS_VOICE = "af_sarah"
MIN_SENTENCE_LEN = 8

HERE = Path(__file__).parent
KOKORO_MODEL_PATH = HERE / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = HERE / "voices-v1.0.bin"


class PatchedKokoro(Kokoro):
    """kokoro-onnx 0.4.7's Kokoro._create_audio hardcodes speed as int32 for
    "input_ids"-schema models, but kokoro-v1.0.onnx's speed input is
    tensor(float) -- ONNXRuntimeError: Unexpected input data type. Actual:
    (tensor(int32)), expected: (tensor(float)). Same method, speed cast to
    float32 instead."""

    def _create_audio(self, phonemes, voice, speed):
        tokens = np.array(self.tokenizer.tokenize(phonemes), dtype=np.int64)
        voice = voice[len(tokens)]
        tokens = [[0, *tokens, 0]]
        if "input_ids" in [i.name for i in self.sess.get_inputs()]:
            inputs = {
                "input_ids": tokens,
                "style": np.array(voice, dtype=np.float32),
                "speed": np.array([speed], dtype=np.float32),
            }
        else:
            inputs = {
                "tokens": tokens,
                "style": voice,
                "speed": np.ones(1, dtype=np.float32) * speed,
            }
        audio = self.sess.run(None, inputs)[0]
        return audio, KOKORO_SAMPLE_RATE


# --- sentence chunker (port of lumi's SentenceChunker) ----------------------

def _find_boundary(text: str, start: int):
    n = len(text)
    for idx in range(start, n):
        if idx > 0 and text[idx - 1] in ".!?" and text[idx].isspace():
            return idx + 1
        if idx + 1 < n and text[idx] == "\n" and text[idx + 1] == "\n":
            return idx + 2
    return None


class SentenceChunker:
    def __init__(self, min_len: int = MIN_SENTENCE_LEN):
        self.min_len = min_len
        self.buf = ""

    def feed(self, delta: str):
        self.buf += delta
        out = []
        start = 0
        while True:
            end = _find_boundary(self.buf, start)
            if end is None:
                break
            head = self.buf[:end]
            if len(head.strip()) < self.min_len:
                start = end
                continue
            out.append(head)
            self.buf = self.buf[end:]
            start = 0
        return out

    def flush(self):
        tail = self.buf.strip()
        self.buf = ""
        return [tail] if tail else []


# --- audio helpers -----------------------------------------------------------

def pcm16_bytes_to_float32(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def kokoro_audio_to_i2s_pcm(samples: np.ndarray, src_rate: int) -> bytes:
    """float32 mono @ src_rate -> s16le stereo @ SPK_SAMPLE_RATE bytes."""
    resampled = resample_poly(samples, SPK_SAMPLE_RATE, src_rate)
    clipped = np.clip(resampled, -1.0, 1.0)
    mono16 = (clipped * 32767.0).astype(np.int16)
    stereo = np.repeat(mono16[:, None], 2, axis=1)
    return stereo.tobytes()


def silence_chunk(ms: int) -> bytes:
    n = SPK_SAMPLE_RATE * ms // 1000
    return np.zeros(n * 2, dtype=np.int16).tobytes()


# --- turn queue: bridges the pipeline worker and the /speak_stream handler --

turn_queue: "queue.Queue[queue.Queue]" = queue.Queue()


def start_turn() -> "queue.Queue":
    """Call once a reply starts generating. Returns the queue to push
    audio chunks (bytes) onto; push None to mark the turn finished."""
    q: "queue.Queue" = queue.Queue()
    turn_queue.put(q)
    return q


# --- pipeline ------------------------------------------------------------

class Pipeline:
    def __init__(self):
        print("[voice_chat_host] loading faster-whisper...")
        self.asr = WhisperModel(ASR_MODEL_SIZE, device="cpu", compute_type="int8")
        print("[voice_chat_host] loading mlx-lm model...")
        self.llm_model, self.llm_tokenizer = load(LLM_MODEL)
        print("[voice_chat_host] loading Kokoro...")
        self.tts = PatchedKokoro(str(KOKORO_MODEL_PATH), str(KOKORO_VOICES_PATH))
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        print("[voice_chat_host] pipeline ready")

    def handle_utterance(self, pcm: bytes):
        audio = pcm16_bytes_to_float32(pcm)
        # vad_filter re-checks with faster-whisper's own (Silero) VAD and
        # drops any non-speech stretch before decoding; no_speech_prob is a
        # second, per-segment guard against Whisper hallucinating filler
        # text ("Thank you.", "Thanks for watching!") on noise it still
        # decided to transcribe. Both are needed: webrtcvad in mic_server
        # only decides when to *cut* an utterance, not whether it was
        # speech at all.
        segments, _info = self.asr.transcribe(audio, beam_size=5, vad_filter=True)
        segments = list(segments)
        text = "".join(
            seg.text for seg in segments if seg.no_speech_prob < NO_SPEECH_PROB_MAX
        ).strip()
        if not text:
            return 0.0
        print(f"[user] {text}")

        self.history.append({"role": "user", "content": text})
        prompt = self.llm_tokenizer.apply_chat_template(
            self.history, tokenize=False, add_generation_prompt=True
        )

        turn_q = start_turn()
        chunker = SentenceChunker()
        reply_parts = []
        speech_s = 0.0
        try:
            for response in stream_generate(
                self.llm_model, self.llm_tokenizer, prompt, max_tokens=200
            ):
                reply_parts.append(response.text)
                for sentence in chunker.feed(response.text):
                    speech_s += self._speak(sentence, turn_q)
                if response.finish_reason:
                    break
            for sentence in chunker.flush():
                speech_s += self._speak(sentence, turn_q)
        finally:
            turn_q.put(None)

        reply = "".join(reply_parts).strip()
        print(f"[assistant] {reply}")
        self.history.append({"role": "assistant", "content": reply})
        return speech_s

    def _speak(self, sentence: str, turn_q: "queue.Queue") -> float:
        text = sentence.strip()
        if not text:
            return 0.0
        samples, sr = self.tts.create(text, voice=TTS_VOICE)
        turn_q.put(kokoro_audio_to_i2s_pcm(samples, sr))
        return len(samples) / sr


# --- mic TCP server --------------------------------------------------------

def mic_server(pipeline: Pipeline):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", MIC_LISTEN_PORT))
    srv.listen(1)
    print(f"[voice_chat_host] mic server listening on :{MIC_LISTEN_PORT}")

    vad = webrtcvad.Vad(3)  # most aggressive (least sensitive to non-speech noise)

    while True:
        conn, addr = srv.accept()
        print(f"[voice_chat_host] mic connected from {addr}")
        buf = b""
        pre_roll = []
        speech_frames = []
        in_speech = False
        voiced_run = 0
        silent_run = 0
        mute_until = 0.0
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buf += data
                while len(buf) >= FRAME_BYTES:
                    frame, buf = buf[:FRAME_BYTES], buf[FRAME_BYTES:]
                    if time.time() < mute_until:
                        # assistant is (or was just) talking -- drop this
                        # frame instead of feeding it to the VAD
                        continue
                    is_speech = vad.is_speech(frame, MIC_SAMPLE_RATE)
                    if is_speech:
                        voiced_run += 1
                        silent_run = 0
                    else:
                        silent_run += 1
                        voiced_run = 0

                    if in_speech:
                        speech_frames.append(frame)
                        if silent_run >= VAD_END_FRAMES:
                            in_speech = False
                            utterance = b"".join(speech_frames)
                            speech_frames = []
                            if len(utterance) >= MIN_UTTERANCE_BYTES:
                                try:
                                    speech_s = pipeline.handle_utterance(utterance)
                                except Exception as exc:
                                    print(f"[voice_chat_host] turn failed: {exc!r}")
                                    speech_s = 0.0
                                if speech_s:
                                    mute_until = time.time() + speech_s + MUTE_MARGIN_S
                    else:
                        pre_roll.append(frame)
                        pre_roll = pre_roll[-VAD_START_FRAMES:]
                        if voiced_run >= VAD_START_FRAMES:
                            in_speech = True
                            speech_frames = list(pre_roll)
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            conn.close()
            print("[voice_chat_host] mic disconnected, waiting for reconnect")


# --- /speak_stream HTTP server ---------------------------------------------

class SpeakHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/speak_stream":
            self.send_error(404, "expected /speak_stream")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        try:
            turn_q = self._wait_for(turn_queue)
            while True:
                chunk = self._wait_for(turn_q)
                if chunk is None:
                    break
                self._write_chunk(chunk)
            self._write_chunk(b"", final=True)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _wait_for(self, q: "queue.Queue"):
        """Blocks on q.get(), sending a silent keepalive chunk every
        KEEPALIVE_TIMEOUT_S so the client's HTTP read timeout never fires
        while ASR/LLM/TTS are still working on this turn."""
        while True:
            try:
                return q.get(timeout=KEEPALIVE_TIMEOUT_S)
            except queue.Empty:
                self._write_chunk(silence_chunk(KEEPALIVE_MS))

    def _write_chunk(self, data: bytes, final: bool = False):
        self.wfile.write(b"%x\r\n" % len(data))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        if final:
            self.wfile.write(b"0\r\n\r\n")

    def log_message(self, fmt, *args):
        print(f"[voice_chat_host] {self.address_string()} {fmt % args}")


def main():
    pipeline = Pipeline()

    # mlx-lm's Metal stream is bound to whichever thread first touches it
    # (here, the thread that ran Pipeline()'s model load). Run the HTTP
    # server on a background thread instead, and keep mic_server -> ASR ->
    # LLM -> TTS on this (main) thread so every mx.eval() call stays on the
    # thread MLX was initialized on.
    http_srv = ThreadingHTTPServer(("0.0.0.0", HTTP_LISTEN_PORT), SpeakHandler)
    print(f"[voice_chat_host] speak_stream server listening on :{HTTP_LISTEN_PORT}")
    threading.Thread(target=http_srv.serve_forever, daemon=True).start()

    mic_server(pipeline)


if __name__ == "__main__":
    main()
