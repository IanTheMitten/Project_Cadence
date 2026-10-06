"""Off-by-default bench recorder: session mic PCM plus per-utterance PCM files.

Never raises into a session; any I/O failure disables recording and logs to stderr.
"""

import json
import os
import sys
import time

SAMPLE_RATE = 16000


class BenchRecorder:
    def __init__(self, directory, client_id, path, file, clock):
        self._dir = directory
        self._client_id = client_id
        self._clock = clock
        self.path = path
        self._file = file

    @classmethod
    def open(cls, directory, client_id, *, clock=time.time):
        if not os.path.isdir(directory) or not os.access(directory, os.W_OK):
            print(f"bench recorder disabled: {directory!r} is not a writable directory",
                  file=sys.stderr)
            return None
        try:
            start = clock()
            stem = f"{client_id}-{int(start * 1000)}"
            meta = {"client_id": client_id, "start_wall": start,
                    "sample_rate": SAMPLE_RATE, "format": "s16le"}
            with open(os.path.join(directory, f"{stem}.json"), "w") as f:
                json.dump(meta, f)
            path = os.path.join(directory, f"{stem}.pcm")
            file = open(path, "wb", buffering=0)
        except OSError as exc:
            print(f"bench recorder disabled: {directory!r}: {exc}", file=sys.stderr)
            return None
        return cls(directory, client_id, path, file, clock)

    def write(self, pcm):
        if self._file is None:
            return
        try:
            self._file.write(pcm)
        except OSError as exc:
            print(f"bench recorder write failed: {exc}", file=sys.stderr)
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None

    def save_utterance(self, pcm):
        path = os.path.join(self._dir, f"utt-{self._client_id}-{int(self._clock() * 1000)}.pcm")
        try:
            with open(path, "wb") as f:
                f.write(pcm)
        except OSError as exc:
            print(f"bench recorder utterance write failed: {exc}", file=sys.stderr)

    def close(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
