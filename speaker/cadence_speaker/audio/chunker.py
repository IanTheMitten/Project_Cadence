MIN_SENTENCE_LEN = 8


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
