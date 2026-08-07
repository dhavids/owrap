import re


class OutputParser:
    ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    MODEL_RE = re.compile(r'^> build\s+\S\s+(\S+)', re.MULTILINE)

    def __init__(self):
        self._buf = ""
        self.model: str | None = None

    def feed(self, chunk: str) -> str:
        """Append chunk to buffer, return cleaned printable portion."""
        self._buf += chunk
        idx = self._buf.rfind('\x1b')
        if idx != -1:
            remaining = self._buf[idx:]
            if not self.ANSI_RE.match(remaining):
                pending = self._buf[idx:]
                process = self._buf[:idx]
                self._buf = pending
            else:
                process = self._buf
                self._buf = ""
        else:
            process = self._buf
            self._buf = ""

        cleaned = self.ANSI_RE.sub('', process)
        cleaned = cleaned.replace('\r\n', '\n')
        cleaned = cleaned.replace('\r', '\n')

        if self.model is None:
            match = self.MODEL_RE.search(cleaned)
            if match:
                self.model = match.group(1)
                cleaned = self.MODEL_RE.sub(f"model: {self.model}", cleaned)

        return cleaned

    def flush(self) -> str:
        if not self._buf:
            return ""
        process = self._buf
        self._buf = ""
        cleaned = self.ANSI_RE.sub('', process)
        cleaned = cleaned.replace('\r\n', '\n')
        cleaned = cleaned.replace('\r', '\n')

        if self.model is None:
            match = self.MODEL_RE.search(cleaned)
            if match:
                self.model = match.group(1)
                cleaned = self.MODEL_RE.sub(f"model: {self.model}", cleaned)

        return cleaned
