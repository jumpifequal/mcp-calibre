#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibre-mcp console - a separate desktop front-end for calibre_mcp.py.

The server is NOT modified or imported. The console only:
  * keeps the configuration that you used to export with `set` (profiles, validated, in one place),
  * launches calibre_mcp.py with the right command line + environment,
  * intercepts stdout/stderr of the server and of maintenance jobs and classifies every line
    (error / warning / progress / request / status / debug),
  * can write the Claude Desktop registration and tail Claude Desktop's own MCP log.

Pure standard library (tkinter). Windows-first, but runs anywhere Tk does.

Transport note: in stdio mode the child's stdout *is* the MCP protocol channel and the client
(Claude Desktop) owns the process, so the console cannot supervise it. For stdio it offers a
protocol self-test and a live tail of Claude Desktop's log. Supervised runs use HTTP transport.
"""
from __future__ import annotations

import codecs
import collections
import ctypes
import datetime as dt
import json
import os
import queue
import re
import secrets
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "calibre-mcp console"
APP_VERSION = "1.0.0"
IS_WIN = os.name == "nt"
CREATE_FLAGS = (0x08000000 | 0x00000200) if IS_WIN else 0  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
MAX_EVENTS = 20000          # events kept in memory
MAX_WIDGET_LINES = 12000    # lines kept in the Text widget
MAX_PROBLEMS = 500

# ----------------------------------------------------------------------------- palette
BG, PANEL, PANEL2, BORDER = "#12161c", "#1a2029", "#232b36", "#2d3745"
FG, MUTED = "#d7dde5", "#8793a3"
ACCENT, ACCENT_H, ACCENT_DIM = "#3ba99c", "#4cc3b4", "#24534f"
C_OK, C_WARN, C_ERR, C_INFO, C_PROG, C_REQ, C_DBG = (
    "#4cc38a", "#e5b34a", "#ef6b6b", "#6aa7e6", "#b48ef0", "#7f8c9c", "#5d6877")
CONSOLE_BG = "#0d1117"
KIND_COLOR = {"error": C_ERR, "warning": C_WARN, "progress": C_PROG,
              "request": C_REQ, "status": FG, "debug": C_DBG}
KINDS = ("error", "warning", "status", "progress", "request", "debug")
SOURCES = ("server", "task", "desktop", "test", "ui")


# ----------------------------------------------------------------------------- configuration schema
@dataclass(frozen=True)
class Var:
    name: str
    label: str
    kind: str            # str | int | path | file | choice
    group: str
    default: str = ""
    choices: tuple = ()
    help: str = ""


SCHEMA: tuple[Var, ...] = (
    Var("CALIBRE_LIBRARY", "Library folder", "path", "Library and data", "",
        help="Folder that contains metadata.db. Empty = auto-detect from Calibre's own config, then ~\\Calibre Library."),
    Var("CALIBRE_LIBRARIES", "Several libraries", "str", "Library and data", "",
        help="Several libraries, ';'-separated on Windows; the first is the default."),
    Var("CALIBRE_MCP_DATA", "Sidecar data folder", "path", "Library and data", r"%LOCALAPPDATA%\calibre-mcp",
        help="Where the sidecar full-text index, embeddings and model cache live."),
    Var("CALIBRE_MCP_MAX_CHARS", "Max chars per read call", "int", "Reading and indexing", "12000",
        help="Cap per read call. Directly controls how many tokens one tool call can return."),
    Var("CALIBRE_MCP_SYNC_INTERVAL", "Index sync interval (s)", "int", "Reading and indexing", "600",
        help="Seconds between background index syncs. 0 = at startup only."),
    Var("CALIBRE_MCP_THROTTLE_MS", "Throttle per document (ms)", "int", "Reading and indexing", "5",
        help="Pause per indexed document, to stay gentle on CPU and disk."),
    Var("CALIBRE_MCP_STEMMING", "Stemmed index", "choice", "Reading and indexing", "0",
        choices=("0", "1"), help="1 = build and use a second, stemmed full-text index."),
    Var("CALIBRE_EBOOK_CONVERT", "ebook-convert", "file", "Conversion and OCR", "",
        help="Auto-detected: PATH, then Calibre2\\ebook-convert.exe under Program Files / Program Files (x86)."),
    Var("CALIBRE_MCP_CONVERT_TIMEOUT", "Conversion timeout (s)", "int", "Conversion and OCR", "180"),
    Var("CALIBRE_MCP_OCR_ENGINE", "OCR engine", "choice", "Conversion and OCR", "auto",
        choices=("auto", "tesseract", "none"), help="auto = Tesseract if installed. Unknown values are rejected by the server."),
    Var("CALIBRE_MCP_OCR_LANGS", "OCR languages", "str", "Conversion and OCR", "ita+eng",
        help="Fallback when the book has no language."),
    Var("CALIBRE_MCP_TESSERACT", "Tesseract program", "file", "Conversion and OCR", "", help="Auto-detected."),
    Var("CALIBRE_MCP_TESSDATA", "Tesseract language files", "path", "Conversion and OCR", "", help="Auto-detected."),
    Var("CALIBRE_MCP_OCR_DPI", "OCR resolution (dpi)", "int", "Conversion and OCR", "300"),
    Var("CALIBRE_MCP_OCR_PAGE_TIMEOUT", "OCR page timeout (s)", "int", "Conversion and OCR", "180"),
    Var("CALIBRE_MCP_EMBED_BACKEND", "Embedding backend", "choice", "Semantic search", "fastembed",
        choices=("fastembed", "hash"), help="hash = lexical fallback for tests and air-gapped machines (not semantic)."),
    Var("CALIBRE_MCP_EMBED_MODEL", "Embedding model", "str", "Semantic search",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        help="The index is tied to the model: changing it requires --build-embeddings --rebuild."),
    Var("CALIBRE_MCP_EMBED_MAX_CHUNKS", "Max passages per book", "int", "Semantic search", "1500",
        help="Evenly sampled beyond this."),
    Var("CALIBRE_MCP_EMBED_CHUNK", "Passage size (chars)", "int", "Semantic search", "700"),
    Var("CALIBRE_MCP_SEMANTIC_FLOOR", "Low-confidence floor", "str", "Semantic search", "0.30",
        help="Similarity below which matches are flagged low_confidence."),
    Var("CALIBRE_MCP_EMBED_THREADS", "Embedding threads", "int", "Semantic search", "",
        help="Default: half of the CPU cores."),
    Var("FASTEMBED_CACHE_PATH", "Model cache folder", "path", "Semantic search", r"%LOCALAPPDATA%\calibre-mcp\models"),
    Var("HTTPS_PROXY", "HTTPS proxy", "str", "Network", "",
        help="Used for the one-off model and OCR language downloads."),
    Var("CALIBRE_MCP_LOG_LEVEL", "Log level", "choice", "Logging", "INFO",
        choices=("DEBUG", "INFO", "WARNING"), help="DEBUG also logs queries."),
)
SCHEMA_NAMES = {v.name for v in SCHEMA}
CREATED_ON_DEMAND = {"CALIBRE_MCP_DATA", "FASTEMBED_CACHE_PATH"}
TOKEN_VAR = "CALIBRE_MCP_HTTP_TOKEN"

TASKS = (
    dict(id="status", title="Library and index status", args=["--status"], json=True, opts=[],
         desc="Runs --status and fills the Overview tree."),
    dict(id="sync", title="Sync full-text index", args=["--sync"], opts=[],
         desc="Foreground sync of the sidecar index."),
    dict(id="extract", title="Extract missing texts (OCR)", args=["--extract-missing"],
         opts=[("max-books", "int"), ("books", "str"), ("retry-failed", "flag"), ("no-ocr", "flag"), ("force-ocr", "flag")],
         desc="Converts and OCRs scanned PDFs Calibre has not extracted. 'books' = comma-separated ids; force-ocr needs books."),
    dict(id="embed", title="Build semantic index", args=["--build-embeddings"],
         opts=[("max-books", "int"), ("rebuild", "flag"), ("retry-failed", "flag"), ("books", "str")],
         desc="Incremental and resumable. CPU-heavy. 'books' = comma-separated ids."),
    dict(id="figures", title="Index figures", args=["--index-figures"], opts=[],
         desc="Captions of EPUB and PDF figures (incremental)."),
    dict(id="report", title="Embeddings report", args=["--embeddings-report"], opts=[],
         desc="Per-book outcome of the semantic build."),
    dict(id="model", title="Download embedding model", args=["--download-model"], opts=[],
         desc="One-off download (honours HTTPS_PROXY). Run it before the first semantic build."),
    dict(id="ocrlangs", title="Download OCR languages", args=["--download-ocr-langs"], opts=[("langs", "str")],
         desc="Tesseract language files, e.g. ita,eng. Required value."),
)
SEQUENCE_REFRESH = ("extract", "embed", "figures", "report")   # same flow as scripts\\update_embeddings.bat


def default_profile() -> dict:
    return {
        "server_dir": "", "python": "", "isolate": True, "env": {}, "custom": {},
        "transport": {"mode": "http", "host": "127.0.0.1", "port": "8765", "path": "/mcp",
                      "allowed_hosts": "", "allowed_origins": "", "ssl_cert": "", "ssl_key": "",
                      "no_auth": False, "skip_verify": False},
        "token_dpapi": "", "desktop_name": "calibre", "tail_desktop": False,
    }


# ----------------------------------------------------------------------------- small helpers
def expand(v: str) -> str:
    return os.path.expandvars(os.path.expanduser(v)) if v else v


def config_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "calibre-mcp-console" / "profiles.json"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def is_loopback(host: str) -> bool:
    return host.strip().lower() in ("127.0.0.1", "localhost", "::1", "[::1]")


def split_list(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,\s;]+", s or "") if p.strip()]


def fmt_dur(sec: float) -> str:
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _dpapi(data: bytes, protect: bool) -> Optional[bytes]:
    """Windows DPAPI (current-user scope). Returns None where unavailable."""
    if not IS_WIN:
        return None
    try:
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

        buf = ctypes.create_string_buffer(data, len(data))
        inb = BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
        outb = BLOB()
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(outb))
        if not ok:
            return None
        res = ctypes.string_at(outb.pbData, outb.cbData)
        kernel32.LocalFree(outb.pbData)
        return res
    except Exception:
        return None


def protect_token(tok: str) -> str:
    import base64
    blob = _dpapi(tok.encode("utf-8"), True)
    return base64.b64encode(blob).decode("ascii") if blob else ""


def unprotect_token(b64: str) -> str:
    import base64
    if not b64:
        return ""
    try:
        blob = _dpapi(base64.b64decode(b64), False)
        return blob.decode("utf-8") if blob else ""
    except Exception:
        return ""


# ----------------------------------------------------------------------------- output classification
@dataclass
class Evt:
    ts: float
    source: str
    kind: str
    text: str
    detail: bool = False     # continuation lines (traceback frames): shown, but not listed as problems
    replace: bool = False    # carriage-return progress that overwrites the previous line
    stream: str = "out"


LEVEL_RE = re.compile(r"(?:^|[\s\[|:-])(CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG)(?=[\s\]|:-]|$)")
DESK_RE = re.compile(r"\[(error|warn|warning|info|debug)\]", re.I)
ACCESS_RE = re.compile(r'"(?:GET|POST|DELETE|PUT|PATCH|OPTIONS|HEAD)\s+\S+\s+HTTP/[\d.]+"\s+(\d{3})')
RPC_RE = re.compile(r"Message from (?:client|server)|Terminating session|Created new transport|Processing request of type")
HTTP_REJECT_RE = re.compile(r"^HTTP (\d{3}) from\b")
SECURITY_RE = re.compile(r"\b(auth DISABLED|WITHOUT TLS)\b")
JSONISH_RE = re.compile(r'^\s*(?:[{}\[\]],?|"[^"]+"\s*:.*)$')
FAILED_RE = re.compile(r"(?<![\d.] )\b(failed|cannot|could not|unable to|refused)\b", re.I)
EXC_RE = re.compile(r"^[\w.]+(?:Error|Exception|Exit|Interrupt)\b")
WARN_RE = re.compile(r"\b\w*Warning:")
FRAC_RE = re.compile(r"(?<![\w/.:\\-])(\d{1,9})\s*/\s*(\d{1,9})(?![\w/\\-]|[.:]\d)")
PCT_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*%")
TERM_RE = re.compile(r"\r\n|\n|\r")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
READY_RE = re.compile(r"Uvicorn running on|Application startup complete", re.I)


def parse_progress(text: str) -> Optional[float]:
    """Fraction 0..1 if the line carries n/m or a percentage, else None."""
    m = FRAC_RE.search(text)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if b > 0 and a <= b:
            return a / b
    m = PCT_RE.search(text)
    if m:
        v = float(m.group(1))
        if 0 <= v <= 100:
            return v / 100
    return None


class Classifier:
    """Stateful per stream (tracks multi-line tracebacks)."""

    def __init__(self) -> None:
        self.in_tb = False

    def classify(self, text: str, replace: bool = False) -> Optional[tuple[str, bool]]:
        t = ANSI_RE.sub("", text).rstrip()
        if not t.strip():
            return None
        if t.startswith("Traceback (most recent call last)"):
            self.in_tb = True
            return "error", False
        if self.in_tb:
            if t[0] in " \t" or t.startswith(("File ", "^")):
                return "error", True
            self.in_tb = False                     # the exception line closes the block
            return "error", False
        if t.startswith(("During handling of the above exception", "The above exception was the direct cause")):
            return "error", True
        m = ACCESS_RE.search(t)
        if m:
            code = int(m.group(1))
            return ("error" if code >= 500 else "warning" if code >= 400 else "request"), False
        m = HTTP_REJECT_RE.match(t)
        if m:
            return ("error" if int(m.group(1)) >= 500 else "warning"), False
        if RPC_RE.search(t):
            return "request", False
        d = DESK_RE.search(t[:160])
        lvl = None
        if d:
            lvl = {"warn": "WARNING", "warning": "WARNING"}.get(d.group(1).lower(), d.group(1).upper())
        else:
            lm = LEVEL_RE.search(t[:100])
            if lm:
                lvl = lm.group(1)
        if lvl in ("CRITICAL", "FATAL", "ERROR"):
            return "error", False
        if lvl in ("WARNING", "WARN"):
            return "warning", False
        if lvl == "DEBUG":
            return "debug", False
        if lvl is None:
            if EXC_RE.match(t) or re.match(r"(?i)(error|fatal)\b\s*[:!]", t):
                return "error", False
            if WARN_RE.search(t) or re.match(r"(?i)warning\b\s*[:!]", t):
                return "warning", False
        if lvl is None and not JSONISH_RE.match(t) and (SECURITY_RE.search(t) or FAILED_RE.search(t)):
            return "warning", False
        if replace or parse_progress(t) is not None:
            return "progress", False
        return "status", False


# ----------------------------------------------------------------------------- process plumbing
def pump_stream(pipe, source: str, stream: str, q: "queue.Queue", clf: Classifier,
                capture: Optional[list] = None) -> None:
    dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf = ""

    def handle(line: str, replace: bool) -> None:
        if capture is not None:
            capture.append(line)
            return
        res = clf.classify(line, replace)
        if res:
            kind, detail = res
            q.put(Evt(time.time(), source, kind, ANSI_RE.sub("", line).rstrip(),
                      detail, replace and kind == "progress", stream))

    try:
        while True:
            chunk = pipe.read1(4096) if hasattr(pipe, "read1") else pipe.read(4096)
            if not chunk:
                break
            buf += dec.decode(chunk)
            while True:
                m = TERM_RE.search(buf)
                if not m:
                    break
                line, term, buf = buf[:m.start()], m.group(0), buf[m.end():]
                handle(line, term == "\r")
        buf += dec.decode(b"", final=True)
        if buf.strip():
            handle(buf, False)
    except (OSError, ValueError):
        pass


class Proc:
    def __init__(self, name: str, source: str, cmd: list[str], env: dict, cwd: str,
                 q: "queue.Queue", capture: Optional[list] = None) -> None:
        self.name, self.source, self.cmd, self.env, self.cwd, self.q = name, source, cmd, env, cwd, q
        self.capture: Optional[list] = capture
        self.p: Optional[subprocess.Popen] = None
        self.started = 0.0
        self.rc: Optional[int] = None

    @property
    def running(self) -> bool:
        return self.p is not None and self.p.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self.p.pid if self.p else None

    def start(self) -> None:
        self.p = subprocess.Popen(self.cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=self.env, cwd=self.cwd,
                                  creationflags=CREATE_FLAGS)
        self.started = time.time()
        clf_out, clf_err = Classifier(), Classifier()
        self._threads = [
            threading.Thread(target=pump_stream, args=(self.p.stdout, self.source, "out", self.q, clf_out, self.capture), daemon=True),
            threading.Thread(target=pump_stream, args=(self.p.stderr, self.source, "err", self.q, clf_err), daemon=True),
        ]
        for t in self._threads:
            t.start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self) -> None:
        assert self.p is not None
        self.rc = self.p.wait()
        for t in self._threads:
            t.join(timeout=2)
        self.q.put(("exit", self))

    def stop(self, grace: float = 6.0) -> None:
        p = self.p
        if not p or p.poll() is not None:
            return
        try:
            if IS_WIN:
                p.send_signal(signal.CTRL_BREAK_EVENT)     # uvicorn handles SIGBREAK -> graceful shutdown
            else:
                p.terminate()
        except (OSError, ValueError):
            pass
        try:
            p.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            p.terminate()
            p.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            try:
                p.kill()
            except OSError:
                pass


class Tailer(threading.Thread):
    """Follows a text log file (Claude Desktop's mcp-server-<name>.log)."""

    def __init__(self, path: Path, q: "queue.Queue") -> None:
        super().__init__(daemon=True)
        self.path, self.q, self.stop_ev = path, q, threading.Event()

    def run(self) -> None:
        clf, pos, announced = Classifier(), None, False
        while not self.stop_ev.is_set():
            try:
                size = self.path.stat().st_size
                first = pos is None
                partial = False
                if first:                                         # first open: last 16 KB
                    pos = max(0, size - 16384)
                    partial = pos > 0
                if size < pos:                                    # rotated / truncated
                    pos = 0
                if size > pos:
                    with open(self.path, "rb") as f:
                        f.seek(pos)
                        data = f.read(size - pos)
                    pos = size
                    text = data.decode("utf-8", "replace").splitlines()
                    if first and partial and text:
                        text = text[1:]                           # drop a partial first line
                    for line in text:
                        res = clf.classify(line)
                        if res:
                            self.q.put(Evt(time.time(), "desktop", res[0], line.rstrip(), res[1]))
                announced = True
            except OSError:
                if announced:
                    announced = False
                    self.q.put(Evt(time.time(), "ui", "warning", f"Desktop log not readable: {self.path}"))
            self.stop_ev.wait(0.7)


# ----------------------------------------------------------------------------- MCP probes
def _parse_rpc_body(ctype: str, body: str) -> dict:
    if "text/event-stream" in ctype:
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except ValueError:
                    continue
        return {}
    return json.loads(body) if body.strip() else {}


def mcp_http_probe(url: str, token: str, skip_verify: bool, timeout: float = 8.0) -> dict:
    """initialize + tools/list against a Streamable HTTP endpoint."""
    res: dict[str, Any] = {"ok": False}
    ctx = None
    if url.startswith("https"):
        ctx = ssl.create_default_context()
        if skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        hdr["Authorization"] = f"Bearer {token}"

    def post(payload: dict, extra: Optional[dict] = None) -> tuple[int, dict, dict]:
        h = dict(hdr)
        h.update(extra or {})
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=h, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                body = r.read().decode("utf-8", "replace")
                return r.status, dict(r.headers), _parse_rpc_body(r.headers.get("Content-Type", ""), body)
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), {}

    t0 = time.time()
    try:
        st, hd, obj = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "calibre-mcp-console", "version": APP_VERSION}}})
        res["latency_ms"] = int((time.time() - t0) * 1000)
        res["status"] = st
        if st in (401, 403):
            res["error"] = f"HTTP {st}: token rejected" if token else f"HTTP {st}: server requires a bearer token"
            return res
        if st != 200:
            res["error"] = f"HTTP {st}"
            return res
        info = (obj.get("result") or {}).get("serverInfo") or {}
        res["server"] = f"{info.get('name', '?')} {info.get('version', '')}".strip()
        sid = {k: v for k, v in hd.items() if k.lower() == "mcp-session-id"}
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        st2, _hd2, obj2 = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
        tools = [t.get("name", "?") for t in (obj2.get("result") or {}).get("tools", [])]
        res["tools"] = tools
        res["ok"] = st2 == 200 and bool(tools)
        if not res["ok"]:
            res["error"] = f"tools/list returned HTTP {st2}, {len(tools)} tools"
    except (urllib.error.URLError, OSError, ValueError) as e:
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def mcp_stdio_selftest(cmd: list[str], env: dict, cwd: str, q: "queue.Queue", timeout: float = 25.0) -> dict:
    """Spawns the server over stdio, runs initialize + tools/list, verifies stdout is protocol-clean."""
    res: dict[str, Any] = {"ok": False}
    t0 = time.time()
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=env, cwd=cwd, creationflags=CREATE_FLAGS)
    except OSError as e:
        res["error"] = f"cannot start: {e}"
        return res
    threading.Thread(target=pump_stream, args=(p.stderr, "test", "err", q, Classifier()), daemon=True).start()
    outq: "queue.Queue" = queue.Queue()

    def rd() -> None:
        for line in iter(p.stdout.readline, b""):
            outq.put(line)
        outq.put(None)

    threading.Thread(target=rd, daemon=True).start()
    junk = 0

    def rpc(msg: dict, want: Optional[int]) -> Optional[dict]:
        nonlocal junk
        assert p.stdin is not None
        p.stdin.write((json.dumps(msg) + "\n").encode())
        p.stdin.flush()
        if want is None:
            return None
        end = time.time() + timeout
        while time.time() < end:
            try:
                line = outq.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError("server closed stdout before answering")
            try:
                obj = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                junk += 1
                q.put(Evt(time.time(), "test", "error",
                          "non-JSON on stdout (breaks the stdio protocol): " + line.decode("utf-8", "replace").rstrip()[:200]))
                continue
            if obj.get("id") == want:
                return obj
        raise TimeoutError(f"no answer to request {want} within {timeout:.0f}s")

    try:
        o = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "calibre-mcp-console", "version": APP_VERSION}}}, 1)
        info = ((o or {}).get("result") or {}).get("serverInfo") or {}
        res["server"] = f"{info.get('name', '?')} {info.get('version', '')}".strip()
        res["latency_ms"] = int((time.time() - t0) * 1000)
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, None)
        o2 = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, 2)
        res["tools"] = [t.get("name", "?") for t in ((o2 or {}).get("result") or {}).get("tools", [])]
        res["ok"] = bool(res["tools"]) and junk == 0
        if junk:
            res["error"] = f"{junk} non-protocol line(s) on stdout"
    except (RuntimeError, TimeoutError, OSError) as e:
        res["error"] = str(e) or type(e).__name__
    finally:
        try:
            if p.stdin:
                p.stdin.close()
            p.wait(timeout=3)
        except Exception:
            p.kill()
    return res


# ----------------------------------------------------------------------------- UI helpers
class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.w, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e) -> None:
        if self.tip or not self.text:
            return
        x, y = self.w.winfo_rootx() + 14, self.w.winfo_rooty() + self.w.winfo_height() + 4
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", bg="#2a3340", fg=FG, padx=9, pady=6,
                 wraplength=380, borderwidth=1, relief="solid").pack()

    def _hide(self, _e) -> None:
        if self.tip:
            self.tip.destroy()
            self.tip = None


class ScrollFrame(ttk.Frame):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, borderwidth=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))


def apply_theme(root: tk.Tk) -> tuple[str, str]:
    fams = set(tkfont.families())
    ui = next((f for f in ("Segoe UI", "SF Pro Text", "Inter", "Noto Sans", "DejaVu Sans") if f in fams),
              tkfont.nametofont("TkDefaultFont").actual("family"))
    mono = next((f for f in ("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Courier New") if f in fams),
                "TkFixedFont")
    for n in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(n).configure(family=ui, size=10)
    if mono in fams:
        tkfont.nametofont("TkFixedFont").configure(family=mono, size=10)
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL2, bordercolor=BORDER,
                lightcolor=BORDER, darkcolor=BORDER, troughcolor=PANEL, focuscolor=ACCENT, insertcolor=FG)
    s.configure("TFrame", background=BG)
    s.configure("Card.TFrame", background=PANEL)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("Card.TLabel", background=PANEL)
    s.configure("Muted.TLabel", foreground=MUTED)
    s.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED)
    s.configure("H1.TLabel", font=(ui, 15, "bold"))
    s.configure("H2.TLabel", font=(ui, 10, "bold"), foreground=MUTED)
    s.configure("Card.TLabel", background=PANEL)
    s.configure("Warn.TLabel", foreground=C_WARN)
    s.configure("Bad.TLabel", foreground=C_ERR)
    s.configure("TButton", background=PANEL2, foreground=FG, borderwidth=0, padding=(12, 6), relief="flat")
    s.map("TButton", background=[("disabled", PANEL), ("pressed", BORDER), ("active", "#2c3643")],
          foreground=[("disabled", C_DBG)])
    s.configure("Accent.TButton", background=ACCENT, foreground="#06201c")
    s.map("Accent.TButton", background=[("disabled", PANEL), ("pressed", ACCENT_DIM), ("active", ACCENT_H)],
          foreground=[("disabled", C_DBG)])
    s.configure("Danger.TButton", background="#7d3039", foreground="#ffecec")
    s.map("Danger.TButton", background=[("disabled", PANEL), ("active", "#9b3b46")], foreground=[("disabled", C_DBG)])
    s.configure("Tool.TButton", padding=(8, 3))
    for st, col in (("TEntry", PANEL2), ("Bad.TEntry", "#41222a"), ("Warn.TEntry", "#3f3420")):
        s.configure(st, fieldbackground=col, foreground=FG, bordercolor=BORDER, padding=4)
    s.configure("TCombobox", fieldbackground=PANEL2, foreground=FG, arrowcolor=MUTED, bordercolor=BORDER,
                background=PANEL2, padding=3)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", FG)],
          selectbackground=[("readonly", PANEL2)], selectforeground=[("readonly", FG)])
    s.configure("TSpinbox", fieldbackground=PANEL2, foreground=FG, arrowcolor=MUTED, bordercolor=BORDER)
    root.option_add("*TCombobox*Listbox.background", PANEL2)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DIM)
    root.option_add("*TCombobox*Listbox.selectForeground", FG)
    s.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
    s.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 8), borderwidth=0)
    s.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", FG)])
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24, borderwidth=0)
    s.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, relief="flat", padding=5)
    s.map("Treeview", background=[("selected", ACCENT_DIM)], foreground=[("selected", FG)])
    s.map("Treeview.Heading", background=[("active", PANEL2)])
    s.configure("TCheckbutton", background=BG, foreground=FG)
    s.map("TCheckbutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", PANEL2)])
    s.configure("Card.TCheckbutton", background=PANEL)
    s.map("Card.TCheckbutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACCENT), ("!selected", PANEL2)])
    s.configure("TRadiobutton", background=BG, foreground=FG)
    s.map("TRadiobutton", background=[("active", BG)], indicatorcolor=[("selected", ACCENT), ("!selected", PANEL2)])
    s.configure("Horizontal.TProgressbar", troughcolor=PANEL2, background=ACCENT, bordercolor=PANEL2,
                lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
    s.configure("TScrollbar", background=PANEL2, troughcolor=PANEL, arrowcolor=MUTED, bordercolor=PANEL)
    s.map("TScrollbar", background=[("active", BORDER)])
    s.configure("TLabelframe", background=BG, bordercolor=BORDER)
    s.configure("TLabelframe.Label", background=BG, foreground=MUTED)
    s.configure("TSeparator", background=BORDER)
    return ui, mono


# ----------------------------------------------------------------------------- application
class App(tk.Tk):
    def __init__(self) -> None:
        if IS_WIN:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass
        super().__init__()
        self.title(f"{APP_NAME}  {APP_VERSION}")
        self.ui_font, self.mono_font = apply_theme(self)
        self._set_icon()
        self.q: "queue.Queue" = queue.Queue()
        self.events: "collections.deque[Evt]" = collections.deque(maxlen=MAX_EVENTS)
        self.cfg = self._load_cfg()
        self.token = ""
        self.server: Optional[Proc] = None
        self.task: Optional[Proc] = None
        self.task_queue: list[dict] = []
        self.task_spec: Optional[dict] = None
        self.task_capture: list[str] = []
        self.state = "stopped"
        self.started_at = 0.0
        self.tailer: Optional[Tailer] = None
        self.n_err = self.n_warn = self.n_req = 0
        self._loading = False
        self.custom: dict[str, str] = {}
        self._cancelled = False
        self._tail_ev: Optional[Evt] = None
        self._save_job = None
        self._prev_progress_src: Optional[str] = None
        self._last_progress_t = 0.0

        self.var_env: dict[str, tk.StringVar] = {}
        self.entry_env: dict[str, ttk.Entry] = {}
        self.tvar: dict[str, tk.Variable] = {}
        self.kind_on = {k: tk.BooleanVar(value=(k != "debug")) for k in KINDS}
        self.src_filter = tk.StringVar(value="all")
        self.search = tk.StringVar()
        self.autoscroll = tk.BooleanVar(value=True)
        self.wrap = tk.BooleanVar(value=False)
        self.task_opts: dict[str, dict[str, tk.Variable]] = {}

        self._build()
        geo = self.cfg.get("ui", {}).get("geometry")
        if geo:
            self.geometry(geo)
        else:
            self.geometry("1280x%d" % min(920, max(640, self.winfo_screenheight() - 90)))
        self.minsize(980, 640)
        self.load_profile_to_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<Control-l>", lambda e: self.clear_console())
        self.bind_all("<Control-f>", lambda e: self.search_entry.focus_set())
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind_all("<Button-4>", self._wheel)
        self.bind_all("<Button-5>", self._wheel)
        self.after(150, self._place_sash)
        self.after(60, self._pump)
        self.after(1000, self._tick)
        self.set_state("stopped")
        self.log("ui", "status", f"{APP_NAME} {APP_VERSION} - server dir: {self.server_dir() or '(not found)'}")

    def _place_sash(self) -> None:
        saved = self.cfg.get("ui", {}).get("sash")
        self.update_idletasks()
        h = max(self.vpane.winfo_height(), 400)
        y = int(saved) if saved else int(h * 0.58)
        self.vpane.sash_place(0, 0, max(220, min(y, h - 200)))

    def _set_icon(self) -> None:
        """Window/taskbar icon from presentation/icon (optional: a missing file or a Tk without PNG support is ignored)."""
        here = Path(__file__).resolve().parent
        for root in (here.parent, here):
            png = root / "presentation" / "icon" / "mcp-calibre-owl-256.png"
            if png.exists():
                try:
                    self._icon_img = tk.PhotoImage(file=str(png))
                    self.iconphoto(True, self._icon_img)
                except tk.TclError:
                    pass
                return

    # ------------------------------------------------------------------ config
    def _load_cfg(self) -> dict:
        p = config_path()
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
        cfg.setdefault("profiles", {})
        if not cfg["profiles"]:
            cfg["profiles"]["Default"] = default_profile()
        for name, prof in cfg["profiles"].items():          # forward-compat: fill new keys
            base = default_profile()
            base.update(prof)
            base["transport"] = {**default_profile()["transport"], **prof.get("transport", {})}
            cfg["profiles"][name] = base
        if cfg.get("active") not in cfg["profiles"]:
            cfg["active"] = next(iter(cfg["profiles"]))
        return cfg

    @property
    def prof(self) -> dict:
        return self.cfg["profiles"][self.cfg["active"]]

    def dirty(self, *_a) -> None:
        if self._loading:
            return
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(700, self.save_now)
        self.after_idle(self.refresh_all)

    def save_now(self) -> None:
        self._save_job = None
        try:
            self.collect()
            self.cfg.setdefault("ui", {})["geometry"] = self.geometry()
            try:
                self.cfg["ui"]["sash"] = self.vpane.sash_coord(0)[1]
            except tk.TclError:
                pass
            atomic_write(config_path(), json.dumps(self.cfg, indent=2))
        except OSError as e:
            self.log("ui", "error", f"cannot save configuration: {e}")

    # ------------------------------------------------------------------ resolution of paths / commands
    def server_dir(self) -> Optional[Path]:
        here = Path(__file__).resolve().parent
        for cand in (self.prof.get("server_dir"), str(here), str(here.parent)):   # console lives in <root>\gui
            if cand and (Path(expand(cand)) / "calibre_mcp.py").exists():
                return Path(expand(cand))
        return None

    def python_path(self) -> tuple[str, str]:
        explicit = expand(self.prof.get("python", ""))
        if explicit and Path(explicit).exists():
            return explicit, "configured"
        sd = self.server_dir()
        if sd:
            for rel in (Path(".venv/Scripts/python.exe"), Path(".venv/bin/python")):
                if (sd / rel).exists():
                    return str(sd / rel), "venv"
        exe = sys.executable
        if IS_WIN and exe.lower().endswith("pythonw.exe"):      # a windowless interpreter has no stdio to intercept
            alt = exe[:-len("pythonw.exe")] + "python.exe"
            if Path(alt).exists():
                exe = alt
        return exe, "console interpreter (no .venv found: server dependencies may be missing)"

    def env_values(self, with_token: bool) -> dict[str, str]:
        """Values the profile sets explicitly (expanded)."""
        out: dict[str, str] = {}
        for k, v in self.prof["env"].items():
            if v.strip():
                out[k] = expand(v.strip())
        for k, v in self.prof["custom"].items():
            if k.strip() and v.strip() != "":
                out[k.strip()] = expand(v)
        if with_token and self.token:
            out[TOKEN_VAR] = self.token
        return out

    def build_env(self, with_token: bool) -> dict[str, str]:
        env = dict(os.environ)
        if self.prof.get("isolate", True):
            managed = SCHEMA_NAMES | set(self.prof["custom"]) | {TOKEN_VAR}
            for k in list(env):
                if k.upper() in {m.upper() for m in managed}:
                    env.pop(k, None)
        env.update(self.env_values(with_token))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def http_args(self) -> list[str]:
        t = self.prof["transport"]
        a = ["--transport", "http", "--host", t["host"], "--port", str(t["port"]), "--path", t["path"]]
        for h in split_list(t["allowed_hosts"]):
            a += ["--allowed-host", h]
        for o in split_list(t["allowed_origins"]):
            a += ["--allowed-origin", o]
        if t["ssl_cert"]:
            a += ["--ssl-certfile", expand(t["ssl_cert"])]
        if t["ssl_key"]:
            a += ["--ssl-keyfile", expand(t["ssl_key"])]
        if t["no_auth"]:
            a.append("--no-auth")
        return a

    def launch_spec(self, extra: list[str], with_token: bool) -> Optional[tuple[list[str], dict, str]]:
        sd = self.server_dir()
        if not sd:
            messagebox.showerror(APP_NAME, "calibre_mcp.py not found.\nSet 'Server folder' in Settings.")
            return None
        py, _how = self.python_path()
        return [py, "-u", str(sd / "calibre_mcp.py")] + extra, self.build_env(with_token), str(sd)

    def endpoint(self) -> str:
        t = self.prof["transport"]
        scheme = "https" if t["ssl_cert"] else "http"
        host = "127.0.0.1" if t["host"] in ("0.0.0.0", "::", "") else t["host"]
        return f"{scheme}://{host}:{t['port']}{t['path']}"

    # ------------------------------------------------------------------ UI construction
    def _build(self) -> None:
        self._build_header()
        self._build_footer()
        self.vpane = tk.PanedWindow(self, orient="vertical", bg=BG, sashwidth=7, sashrelief="flat", bd=0)
        self.vpane.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.nb = ttk.Notebook(self.vpane)
        self.vpane.add(self.nb, minsize=220, stretch="always")
        self._build_overview()
        self._build_settings()
        self._build_transport()
        self._build_maintenance()
        self._build_integration()
        self._build_console()

    def _build_header(self) -> None:
        h = ttk.Frame(self)
        h.pack(fill="x", padx=14, pady=(12, 10))
        ttk.Label(h, text="calibre-mcp", style="H1.TLabel").pack(side="left")
        ttk.Label(h, text="  console", style="Muted.TLabel").pack(side="left", pady=(5, 0))
        self.pill = tk.Label(h, text="STOPPED", bg=C_DBG, fg="#0b0f14", padx=12, pady=3,
                             font=(self.ui_font, 9, "bold"))
        self.pill.pack(side="left", padx=16)
        right = ttk.Frame(h)
        right.pack(side="right")
        self.btn_restart = ttk.Button(right, text="Restart", command=self.restart_server)
        self.btn_stop = ttk.Button(right, text="Stop", style="Danger.TButton", command=self.stop_server)
        self.btn_start = ttk.Button(right, text="Start server", style="Accent.TButton", command=self.start_server)
        for b in (self.btn_restart, self.btn_stop, self.btn_start):
            b.pack(side="right", padx=(6, 0))
        pf = ttk.Frame(h)
        pf.pack(side="right", padx=20)
        ttk.Label(pf, text="Profile", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        self.profile_var = tk.StringVar()
        self.profile_cb = ttk.Combobox(pf, textvariable=self.profile_var, state="readonly", width=20)
        self.profile_cb.pack(side="left")
        self.profile_cb.bind("<<ComboboxSelected>>", self.on_profile_selected)
        ttk.Button(pf, text="New", style="Tool.TButton", command=self.new_profile).pack(side="left", padx=(6, 0))
        ttk.Button(pf, text="Delete", style="Tool.TButton", command=self.delete_profile).pack(side="left", padx=(4, 0))

    def _scroll_page(self, title: str, pad: int = 14) -> ttk.Frame:
        """Notebook page whose content scrolls when the pane is short."""
        sf = ScrollFrame(self.nb)
        self.nb.add(sf, text=title)
        inner = ttk.Frame(sf.inner, padding=pad)
        inner.pack(fill="both", expand=True)
        return inner

    # ---- overview
    def _card(self, parent, title: str) -> ttk.Frame:
        f = ttk.Frame(parent, style="Card.TFrame", padding=14)
        ttk.Label(f, text=title.upper(), style="CardMuted.TLabel", font=(self.ui_font, 8, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        return f

    def _build_overview(self) -> None:
        page = self._scroll_page("Overview", pad=12)
        page.columnconfigure(0, weight=0)
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        card = self._card(page, "Server")
        card.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        self.sv = {k: tk.StringVar(value="-") for k in
                   ("state", "mode", "endpoint", "pid", "uptime", "req", "warn", "err", "test", "python", "task")}
        rows = (("State", "state"), ("Transport", "mode"), ("Endpoint", "endpoint"), ("PID", "pid"),
                ("Uptime", "uptime"), ("Requests", "req"), ("Warnings", "warn"), ("Errors", "err"),
                ("Last self-test", "test"), ("Interpreter", "python"), ("Running job", "task"))
        for i, (lab, key) in enumerate(rows, start=1):
            ttk.Label(card, text=lab, style="CardMuted.TLabel").grid(row=i, column=0, sticky="nw", pady=2, padx=(0, 14))
            ttk.Label(card, textvariable=self.sv[key], style="Card.TLabel", wraplength=290, justify="left").grid(
                row=i, column=1, sticky="nw", pady=2)
        bar = ttk.Frame(card, style="Card.TFrame")
        bar.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(bar, text="Self-test", command=self.run_selftest).pack(side="left")
        ttk.Button(bar, text="Copy endpoint", command=lambda: self.to_clipboard(self.endpoint())).pack(side="left", padx=6)
        self.banner = ttk.Label(card, text="", style="Warn.TLabel", wraplength=320, justify="left")
        self.banner.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="w", pady=(12, 0))

        right = self._card(page, "Library and index (from --status)")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.status_tree = ttk.Treeview(right, columns=("v",), selectmode="browse", height=10)
        self.status_tree.heading("#0", text="Key", anchor="w")
        self.status_tree.heading("v", text="Value", anchor="w")
        self.status_tree.column("#0", width=260, stretch=False)
        self.status_tree.column("v", width=420)
        self.status_tree.tag_configure("null", foreground=C_WARN)
        self.status_tree.tag_configure("bad", foreground=C_ERR)
        sb = ttk.Scrollbar(right, orient="vertical", command=self.status_tree.yview)
        self.status_tree.configure(yscrollcommand=sb.set)
        self.status_tree.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        ttk.Button(right, text="Refresh status", command=lambda: self.run_task_ids(["status"])).grid(
            row=2, column=0, sticky="w", pady=(10, 0))

    # ---- settings
    def _build_settings(self) -> None:
        page = ttk.Frame(self.nb)
        self.nb.add(page, text="Settings")
        sf = ScrollFrame(page)
        sf.pack(fill="both", expand=True)
        body = sf.inner
        body.columnconfigure(0, weight=1)
        r = 0
        top = ttk.LabelFrame(body, text="Launcher", padding=12)
        top.grid(row=r, column=0, sticky="ew", padx=12, pady=(12, 6))
        top.columnconfigure(1, weight=1)
        self.v_server_dir, self.v_python = tk.StringVar(), tk.StringVar()
        self.v_isolate = tk.BooleanVar(value=True)
        for i, (lab, var, kind, tip) in enumerate((
                ("Server folder", self.v_server_dir, "dir", "Folder containing calibre_mcp.py. Empty = this folder or its parent (the console lives in <root>/gui)."),
                ("Python interpreter", self.v_python, "file", "Empty = <server folder>\\.venv\\Scripts\\python.exe"))):
            ttk.Label(top, text=lab).grid(row=i, column=0, sticky="w", pady=4, padx=(0, 12))
            e = ttk.Entry(top, textvariable=var)
            e.grid(row=i, column=1, sticky="ew", pady=4)
            Tooltip(e, tip)
            ttk.Button(top, text="Browse", style="Tool.TButton", command=lambda v=var, k=kind: self.browse(v, k)).grid(
                row=i, column=2, padx=(6, 0))
            var.trace_add("write", self.dirty)
        cb = ttk.Checkbutton(top, text="Isolate from the system environment: variables managed here override anything already set",
                             variable=self.v_isolate, command=self.dirty)
        cb.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        Tooltip(cb, "When on, every variable known to this profile is removed from the inherited environment first, "
                    "so the profile is the single source of truth (reproducible). Turn off to inherit as-is.")
        r += 1
        groups: dict[str, list[Var]] = {}
        for v in SCHEMA:
            groups.setdefault(v.group, []).append(v)
        for g, vs in groups.items():
            lf = ttk.LabelFrame(body, text=g, padding=12)
            lf.grid(row=r, column=0, sticky="ew", padx=12, pady=6)
            lf.columnconfigure(1, weight=1)
            r += 1
            for i, v in enumerate(vs):
                sv = tk.StringVar()
                self.var_env[v.name] = sv
                lbl = ttk.Label(lf, text=v.label)
                lbl.grid(row=i, column=0, sticky="w", pady=4, padx=(0, 14))
                Tooltip(lbl, f"{v.name}\n{v.help}".strip())
                if v.kind == "choice":
                    w: ttk.Widget = ttk.Combobox(lf, textvariable=sv, state="readonly", values=("",) + v.choices, width=18)
                    w.grid(row=i, column=1, sticky="w", pady=4)
                else:
                    w = ttk.Entry(lf, textvariable=sv)
                    w.grid(row=i, column=1, sticky="ew", pady=4)
                    self.entry_env[v.name] = w
                if v.kind in ("path", "file"):
                    ttk.Button(lf, text="Browse", style="Tool.TButton",
                               command=lambda sv=sv, k=("dir" if v.kind == "path" else "file"): self.browse(sv, k)).grid(
                        row=i, column=2, padx=(6, 0))
                hint = f"default: {v.default}" if v.default else "default: (auto)"
                ttk.Label(lf, text=hint, style="Muted.TLabel", font=(self.ui_font, 8)).grid(row=i, column=3, padx=(10, 0), sticky="w")
                ttk.Button(lf, text="x", width=2, style="Tool.TButton", command=lambda sv=sv: sv.set("")).grid(
                    row=i, column=4, padx=(6, 0))
                Tooltip(w, f"{v.name}\n{v.help}".strip())
                sv.trace_add("write", self.dirty)
        cf = ttk.LabelFrame(body, text="Other variables (anything not listed above)", padding=12)
        cf.grid(row=r, column=0, sticky="ew", padx=12, pady=(6, 14))
        cf.columnconfigure(0, weight=1)
        self.custom_tree = ttk.Treeview(cf, columns=("v",), height=5, selectmode="browse")
        self.custom_tree.heading("#0", text="Name", anchor="w")
        self.custom_tree.heading("v", text="Value", anchor="w")
        self.custom_tree.column("#0", width=260, stretch=False)
        self.custom_tree.grid(row=0, column=0, sticky="ew")
        btns = ttk.Frame(cf)
        btns.grid(row=0, column=1, sticky="n", padx=(10, 0))
        for text, cmd in (("Add", self.custom_add), ("Edit", self.custom_edit), ("Remove", self.custom_remove),
                          ("Import from environment", self.import_env)):
            ttk.Button(btns, text=text, style="Tool.TButton", command=cmd).pack(fill="x", pady=2)

    # ---- transport
    def _build_transport(self) -> None:
        page = self._scroll_page("Transport")
        page.columnconfigure(1, weight=1)
        T = self.tvar
        T["mode"] = tk.StringVar(value="http")
        for k in ("host", "port", "path", "allowed_hosts", "allowed_origins", "ssl_cert", "ssl_key"):
            T[k] = tk.StringVar()
        T["no_auth"] = tk.BooleanVar()
        T["skip_verify"] = tk.BooleanVar()
        T["token"] = tk.StringVar()
        row = 0
        mf = ttk.Frame(page)
        mf.grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Radiobutton(mf, text="HTTP (supervised by this console)", value="http", variable=T["mode"],
                        command=self.dirty).pack(side="left")
        ttk.Radiobutton(mf, text="stdio (owned by Claude Desktop)", value="stdio", variable=T["mode"],
                        command=self.dirty).pack(side="left", padx=18)
        row += 1
        fields = (("Host", "host", ""), ("Port", "port", ""), ("Path", "path", ""),
                  ("Allowed hosts", "allowed_hosts", "Host-header allow-list (DNS-rebinding protection). Comma separated; 'name:*' = any port. Required with 0.0.0.0."),
                  ("Allowed origins", "allowed_origins", "Browser Origins allowed (comma separated). Others get 403."),
                  ("TLS certificate", "ssl_cert", "file"), ("TLS key", "ssl_key", "file"))
        self.http_widgets: list[tk.Widget] = []
        for lab, key, extra in fields:
            ttk.Label(page, text=lab).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 14))
            e = ttk.Entry(page, textvariable=T[key], width=(10 if key == "port" else 50))
            e.grid(row=row, column=1, sticky=("w" if key == "port" else "ew"), pady=4)
            self.http_widgets.append(e)
            if extra == "file":
                b = ttk.Button(page, text="Browse", style="Tool.TButton", command=lambda v=T[key]: self.browse(v, "file"))
                b.grid(row=row, column=2, padx=(6, 0))
                self.http_widgets.append(b)
            elif extra:
                Tooltip(e, extra)
            T[key].trace_add("write", self.dirty)
            row += 1
        ttk.Label(page, text="Bearer token").grid(row=row, column=0, sticky="w", pady=4)
        tf = ttk.Frame(page)
        tf.grid(row=row, column=1, sticky="ew", pady=4)
        tf.columnconfigure(0, weight=1)
        self.token_entry = ttk.Entry(tf, textvariable=T["token"], show="\u2022")
        self.token_entry.grid(row=0, column=0, sticky="ew")
        self._show_tok = tk.BooleanVar(value=False)
        ttk.Checkbutton(tf, text="show", variable=self._show_tok,
                        command=lambda: self.token_entry.configure(show="" if self._show_tok.get() else "\u2022")).grid(row=0, column=1, padx=8)
        ttk.Button(tf, text="Generate", style="Tool.TButton", command=self.gen_token).grid(row=0, column=2)
        ttk.Button(tf, text="Copy", style="Tool.TButton", command=lambda: self.to_clipboard(self.token_value())).grid(row=0, column=3, padx=(4, 0))
        self.http_widgets += [self.token_entry]
        T["token"].trace_add("write", self.dirty)
        Tooltip(self.token_entry, "256-bit random token. Stored with Windows DPAPI (current user) in the profile file; "
                                  "never written in clear to disk by this console.")
        row += 1
        of = ttk.Frame(page)
        of.grid(row=row, column=1, sticky="w", pady=(6, 2))
        ttk.Checkbutton(of, text="--no-auth (loopback only)", variable=T["no_auth"], command=self.dirty).pack(side="left")
        ttk.Checkbutton(of, text="skip TLS verification for self-test (loopback only)", variable=T["skip_verify"],
                        command=self.dirty).pack(side="left", padx=18)
        row += 1
        self.t_issues = ttk.Label(page, text="", justify="left", wraplength=800)
        self.t_issues.grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 4))
        row += 1
        ttk.Label(page, text="RESOLVED LAUNCH", style="H2.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 4))
        row += 1
        pf = ttk.Frame(page)
        pf.grid(row=row, column=0, columnspan=3, sticky="nsew")
        pf.columnconfigure(0, weight=1)
        self.preview = tk.Text(pf, height=8, bg=CONSOLE_BG, fg=FG, relief="flat", font="TkFixedFont", wrap="none",
                               padx=10, pady=8, state="disabled", highlightthickness=1, highlightbackground=BORDER)
        self.preview.grid(row=0, column=0, sticky="nsew")
        pb = ttk.Frame(pf)
        pb.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(pb, text="Copy as .bat", command=lambda: self.copy_launch("bat")).pack(side="left")
        ttk.Button(pb, text="Copy as PowerShell", command=lambda: self.copy_launch("ps")).pack(side="left", padx=6)
        ttk.Label(pb, text="the token is never included in the copied script", style="Muted.TLabel").pack(side="left", padx=8)

    # ---- maintenance
    def _build_maintenance(self) -> None:
        page = self._scroll_page("Maintenance")
        page.columnconfigure(0, weight=1)
        self.task_buttons: dict[str, ttk.Button] = {}
        for i, spec in enumerate(TASKS):
            f = ttk.Frame(page, style="Card.TFrame", padding=(14, 10))
            f.grid(row=i, column=0, sticky="ew", pady=3)
            f.columnconfigure(0, weight=1)
            tf = ttk.Frame(f, style="Card.TFrame")
            tf.grid(row=0, column=0, sticky="w")
            ttk.Label(tf, text=spec["title"], style="Card.TLabel", font=(self.ui_font, 10, "bold")).pack(anchor="w")
            ttk.Label(tf, text=spec["desc"], style="CardMuted.TLabel", wraplength=520, justify="left").pack(anchor="w")
            self.task_opts[spec["id"]] = {}
            of = ttk.Frame(f, style="Card.TFrame")
            of.grid(row=0, column=1, padx=10, sticky="e")
            for name, kind in spec["opts"]:
                if kind == "flag":
                    var: tk.Variable = tk.BooleanVar()
                    ttk.Checkbutton(of, text=name, variable=var, style="Card.TCheckbutton").pack(side="left", padx=4)
                else:
                    var = tk.StringVar()
                    ttk.Label(of, text=name, style="CardMuted.TLabel").pack(side="left", padx=(6, 2))
                    ttk.Entry(of, textvariable=var, width=(6 if kind == "int" else 12)).pack(side="left")
                self.task_opts[spec["id"]][name] = var
            b = ttk.Button(f, text="Run", command=lambda s=spec: self.run_task_ids([s["id"]]))
            b.grid(row=0, column=2, padx=(6, 0))
            self.task_buttons[spec["id"]] = b
        seq = ttk.Frame(page)
        seq.grid(row=len(TASKS), column=0, sticky="w", pady=(14, 0))
        self.btn_seq = ttk.Button(seq, text="Run refresh sequence (OCR, semantic, figures, report)", style="Accent.TButton",
                                  command=lambda: self.run_task_ids(list(SEQUENCE_REFRESH)))
        self.btn_seq.pack(side="left")
        self.btn_cancel = ttk.Button(seq, text="Cancel job", style="Danger.TButton", command=self.cancel_task, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)

    # ---- integration
    def _build_integration(self) -> None:
        page = self._scroll_page("Integration")
        page.columnconfigure(1, weight=1)
        self.v_desk_name = tk.StringVar()
        self.v_tail = tk.BooleanVar()
        ttk.Label(page, text="CLAUDE DESKTOP (stdio)", style="H2.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Label(page, text="Server entry name").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 14))
        e = ttk.Entry(page, textvariable=self.v_desk_name, width=24)
        e.grid(row=1, column=1, sticky="w")
        self.v_desk_name.trace_add("write", self.dirty)
        ttk.Label(page, text="Config file").grid(row=2, column=0, sticky="w", pady=4)
        self.desk_cfg_lbl = ttk.Label(page, text=str(self.desktop_config_path()), style="Muted.TLabel")
        self.desk_cfg_lbl.grid(row=2, column=1, sticky="w")
        bf = ttk.Frame(page)
        bf.grid(row=3, column=1, sticky="w", pady=8)
        ttk.Button(bf, text="Write / update entry (with backup)", style="Accent.TButton", command=self.write_desktop_entry).pack(side="left")
        ttk.Button(bf, text="Copy entry JSON", command=lambda: self.to_clipboard(json.dumps(self.desktop_entry(), indent=2))).pack(side="left", padx=6)
        ttk.Checkbutton(page, text="Follow Claude Desktop's MCP log in the console", variable=self.v_tail,
                        command=self.toggle_tail).grid(row=4, column=1, sticky="w", pady=(0, 4))
        self.v_tail.trace_add("write", self.dirty)
        ttk.Label(page, text="Entry preview (no token: stdio does not use one)", style="Muted.TLabel").grid(row=5, column=1, sticky="w")
        self.desk_preview = tk.Text(page, height=10, bg=CONSOLE_BG, fg=FG, relief="flat", font="TkFixedFont",
                                    padx=10, pady=8, state="disabled", highlightthickness=1, highlightbackground=BORDER)
        self.desk_preview.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(4, 14))
        ttk.Label(page, text="HTTP CLIENTS", style="H2.TLabel").grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 6))
        hf = ttk.Frame(page)
        hf.grid(row=8, column=1, sticky="w")
        ttk.Button(hf, text="Copy Claude Code command", command=self.copy_claude_code).pack(side="left")
        ttk.Button(hf, text="Copy mcp-remote JSON (Claude Desktop)", command=self.copy_mcp_remote).pack(side="left", padx=6)
        ttk.Label(page, text="These copy the real token to the clipboard.", style="Muted.TLabel").grid(row=9, column=1, sticky="w", pady=(4, 0))

    # ---- console + footer
    def _build_console(self) -> None:
        box = ttk.Frame(self.vpane)
        self.vpane.add(box, minsize=180, stretch="always")
        tb = ttk.Frame(box)
        tb.pack(fill="x", pady=(6, 4))
        ttk.Label(tb, text="CONSOLE", style="H2.TLabel").pack(side="left", padx=(0, 12))
        for k in KINDS:
            c = tk.Checkbutton(tb, text=k, variable=self.kind_on[k], command=self.refilter, fg=KIND_COLOR[k], bg=BG,
                               activebackground=BG, activeforeground=KIND_COLOR[k], selectcolor=PANEL2,
                               highlightthickness=0, borderwidth=0, font=(self.ui_font, 9))
            c.pack(side="left", padx=3)
        ttk.Label(tb, text="source", style="Muted.TLabel").pack(side="left", padx=(14, 4))
        cb = ttk.Combobox(tb, textvariable=self.src_filter, state="readonly", width=8, values=("all",) + SOURCES)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.refilter())
        self.search_entry = ttk.Entry(tb, textvariable=self.search, width=22)
        self.search_entry.pack(side="left", padx=(14, 0))
        Tooltip(self.search_entry, "Filter lines containing this text (Ctrl+F)")
        self.search.trace_add("write", lambda *a: self.after_idle(self.refilter))
        r = ttk.Frame(tb)
        r.pack(side="right")
        ttk.Checkbutton(r, text="autoscroll", variable=self.autoscroll).pack(side="left", padx=4)
        ttk.Checkbutton(r, text="wrap", variable=self.wrap, command=lambda: self.console.configure(wrap="word" if self.wrap.get() else "none")).pack(side="left", padx=4)
        ttk.Button(r, text="Save", style="Tool.TButton", command=self.save_log).pack(side="left", padx=2)
        ttk.Button(r, text="Clear", style="Tool.TButton", command=self.clear_console).pack(side="left", padx=2)
        hp = tk.PanedWindow(box, orient="horizontal", bg=BG, sashwidth=7, sashrelief="flat", bd=0)
        hp.pack(fill="both", expand=True)
        left = ttk.Frame(hp)
        hp.add(left, stretch="always", minsize=300)
        self.console = tk.Text(left, bg=CONSOLE_BG, fg=FG, insertbackground=FG, relief="flat", font="TkFixedFont",
                               wrap="none", padx=10, pady=6, state="disabled", highlightthickness=1,
                               highlightbackground=BORDER, selectbackground=ACCENT_DIM, spacing1=1)
        ys = ttk.Scrollbar(left, orient="vertical", command=self.console.yview)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.console.xview)
        self.console.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        ys.pack(side="right", fill="y")
        xs.pack(side="bottom", fill="x")
        self.console.pack(side="left", fill="both", expand=True)
        self.console.tag_configure("ts", foreground=C_DBG)
        self.console.tag_configure("src", foreground=MUTED)
        for k, col in KIND_COLOR.items():
            self.console.tag_configure(k, foreground=col)
        self.console.tag_configure("error", foreground=C_ERR)
        right = ttk.Frame(hp, style="Card.TFrame", padding=8)
        hp.add(right, minsize=240, width=360)
        hd = ttk.Frame(right, style="Card.TFrame")
        hd.pack(fill="x")
        self.prob_title = ttk.Label(hd, text="PROBLEMS", style="CardMuted.TLabel", font=(self.ui_font, 8, "bold"))
        self.prob_title.pack(side="left")
        ttk.Button(hd, text="Clear", style="Tool.TButton", command=self.clear_problems).pack(side="right")
        ttk.Button(hd, text="Copy", style="Tool.TButton", command=self.copy_problems).pack(side="right", padx=4)
        self.prob = ttk.Treeview(right, columns=("t", "src", "msg"), show="headings", selectmode="browse")
        for c, w, txt in (("t", 74, "Time"), ("src", 60, "Src"), ("msg", 200, "Message")):
            self.prob.heading(c, text=txt, anchor="w")
            self.prob.column(c, width=w, stretch=(c == "msg"))
        self.prob.tag_configure("error", foreground=C_ERR)
        self.prob.tag_configure("warning", foreground=C_WARN)
        ps = ttk.Scrollbar(right, orient="vertical", command=self.prob.yview)
        self.prob.configure(yscrollcommand=ps.set)
        ps.pack(side="right", fill="y", pady=(6, 0))
        self.prob.pack(fill="both", expand=True, pady=(6, 0))
        self.prob.bind("<Double-1>", lambda e: self.copy_problems(selected=True))

    def _build_footer(self) -> None:
        f = ttk.Frame(self, padding=(14, 4, 14, 10))
        f.pack(fill="x", side="bottom")
        f.columnconfigure(1, weight=1)
        self.pbar = ttk.Progressbar(f, mode="determinate", maximum=100, length=260)
        self.pbar.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.pl = tk.StringVar(value="Idle")
        ttk.Label(f, textvariable=self.pl, style="Muted.TLabel").grid(row=0, column=1, sticky="w")
        self.counters = tk.StringVar()
        ttk.Label(f, textvariable=self.counters, style="Muted.TLabel").grid(row=0, column=2, sticky="e")

    # ------------------------------------------------------------------ generic widgets helpers
    def _wheel(self, e) -> None:
        w = self.winfo_containing(e.x_root, e.y_root)
        while w is not None:
            if isinstance(w, ScrollFrame):
                step = -1 if (getattr(e, "delta", 0) > 0 or e.num == 4) else 1
                w.canvas.yview_scroll(step * 2, "units")
                return
            w = w.master

    def browse(self, var: tk.StringVar, kind: str) -> None:
        cur = expand(var.get())
        if kind == "dir":
            p = filedialog.askdirectory(initialdir=cur if cur and Path(cur).exists() else None)
        else:
            p = filedialog.askopenfilename(initialdir=str(Path(cur).parent) if cur else None)
        if p:
            var.set(os.path.normpath(p))

    def to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log("ui", "status", "copied to clipboard")

    def token_value(self) -> str:
        return self.tvar["token"].get().strip()

    def gen_token(self) -> None:
        self.tvar["token"].set(secrets.token_urlsafe(32))

    # ------------------------------------------------------------------ profile <-> widgets
    def load_profile_to_ui(self) -> None:
        self._loading = True
        try:
            p = self.prof
            self.profile_cb["values"] = list(self.cfg["profiles"])
            self.profile_var.set(self.cfg["active"])
            self.v_server_dir.set(p["server_dir"])
            self.v_python.set(p["python"])
            self.v_isolate.set(p["isolate"])
            for v in SCHEMA:
                self.var_env[v.name].set(p["env"].get(v.name, ""))
            for k, var in self.tvar.items():
                if k == "token":
                    continue
                var.set(p["transport"].get(k, False if isinstance(var, tk.BooleanVar) else ""))
            self.token = unprotect_token(p.get("token_dpapi", "")) if IS_WIN else self.token
            self.tvar["token"].set(self.token)
            self.v_desk_name.set(p["desktop_name"])
            self.v_tail.set(p["tail_desktop"])
            self.custom = dict(p["custom"])
            self._render_custom()
        finally:
            self._loading = False
        self.toggle_tail()
        self.refresh_all()

    def collect(self) -> dict:
        p = self.prof
        p["server_dir"], p["python"], p["isolate"] = self.v_server_dir.get().strip(), self.v_python.get().strip(), self.v_isolate.get()
        p["env"] = {n: v.get().strip() for n, v in self.var_env.items() if v.get().strip()}
        for k, var in self.tvar.items():
            if k == "token":
                continue
            val = var.get()
            p["transport"][k] = val.strip() if isinstance(val, str) else bool(val)
        self.token = self.tvar["token"].get().strip()
        if IS_WIN:
            p["token_dpapi"] = protect_token(self.token) if self.token else ""
        p["desktop_name"] = self.v_desk_name.get().strip() or "calibre"
        p["tail_desktop"] = bool(self.v_tail.get())
        p["custom"] = dict(self.custom)
        if self.token and IS_WIN and not p["token_dpapi"]:
            self.log("ui", "warning", "token not persisted (DPAPI unavailable): it will be lost when the console closes")
        return p

    def on_profile_selected(self, _e=None) -> None:
        self.save_now()
        self.cfg["active"] = self.profile_var.get()
        self.load_profile_to_ui()

    def new_profile(self) -> None:
        name = simpledialog.askstring(APP_NAME, "New profile name (copies the current one):", parent=self)
        if not name or name in self.cfg["profiles"]:
            return
        self.save_now()
        import copy
        self.cfg["profiles"][name] = copy.deepcopy(self.prof)
        self.cfg["profiles"][name]["token_dpapi"] = ""
        self.cfg["active"] = name
        self.load_profile_to_ui()

    def delete_profile(self) -> None:
        if len(self.cfg["profiles"]) < 2:
            messagebox.showinfo(APP_NAME, "At least one profile must remain.")
            return
        if messagebox.askyesno(APP_NAME, f"Delete profile '{self.cfg['active']}'?"):
            del self.cfg["profiles"][self.cfg["active"]]
            self.cfg["active"] = next(iter(self.cfg["profiles"]))
            self.load_profile_to_ui()

    # custom variables
    def _render_custom(self) -> None:
        self.custom_tree.delete(*self.custom_tree.get_children())
        for k, v in self.custom.items():
            self.custom_tree.insert("", "end", iid=k, text=k, values=(v,))

    def custom_add(self) -> None:
        n = simpledialog.askstring(APP_NAME, "Variable name:", parent=self)
        if not n or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", n.strip()):
            return
        v = simpledialog.askstring(APP_NAME, f"Value of {n.strip()}:", parent=self) or ""
        self.custom[n.strip()] = v
        self._render_custom()
        self.dirty()

    def custom_edit(self) -> None:
        sel = self.custom_tree.selection()
        if sel:
            v = simpledialog.askstring(APP_NAME, f"Value of {sel[0]}:", initialvalue=self.custom.get(sel[0], ""), parent=self)
            if v is not None:
                self.custom[sel[0]] = v
                self._render_custom()
                self.dirty()

    def custom_remove(self) -> None:
        for s_ in self.custom_tree.selection():
            self.custom.pop(s_, None)
        self._render_custom()
        self.dirty()

    def import_env(self) -> None:
        """Capture what is currently exported in the environment that launched the console (your old `set` lines)."""
        n_known = n_custom = 0
        for k, v in os.environ.items():
            ku = k.upper()
            if ku == TOKEN_VAR:
                self.tvar["token"].set(v)
                self.log("ui", "status", "token imported from environment")
            elif ku in SCHEMA_NAMES and v.strip():
                self.var_env[ku].set(v)
                n_known += 1
            elif ku.startswith(("CALIBRE_", "FASTEMBED_")) and ku not in SCHEMA_NAMES:
                self.custom[ku] = v
                n_custom += 1
        self._render_custom()
        self.dirty()
        messagebox.showinfo(APP_NAME, f"Imported {n_known} known and {n_custom} other variable(s) from this console's environment.\n"
                                      "Tip: start the console from the cmd window where you ran your `set` lines.")

    # ------------------------------------------------------------------ validation and previews
    def validate_entries(self) -> None:
        for v in SCHEMA:
            e = self.entry_env.get(v.name)
            if not e:
                continue
            val = self.var_env[v.name].get().strip()
            style = "TEntry"
            if val:
                if v.kind == "int" and not val.isdigit():
                    style = "Bad.TEntry"
                elif v.kind in ("path", "file") and v.name not in CREATED_ON_DEMAND and not Path(expand(val)).exists():
                    style = "Warn.TEntry"
            e.configure(style=style)

    def transport_issues(self) -> list[tuple[str, str]]:
        t = {k: (v.get() if not isinstance(v, tk.BooleanVar) else bool(v.get())) for k, v in self.tvar.items()}
        out: list[tuple[str, str]] = []
        if t["mode"] != "http":
            return out
        host = str(t["host"]).strip()
        try:
            port = int(str(t["port"]))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            out.append(("block", "Port must be 1-65535."))
        tok = str(t["token"]).strip()
        if t["no_auth"]:
            if not is_loopback(host):
                out.append(("block", "--no-auth is refused by the server off loopback."))
            else:
                out.append(("warn", "--no-auth: any local process can read the library through this endpoint."))
        else:
            if not tok:
                out.append(("block", "A bearer token is required (min 24 characters). Use Generate."))
            elif len(tok) < 24:
                out.append(("block", "Token shorter than 24 characters: the server will refuse to start."))
        if not is_loopback(host):
            if not str(t["ssl_cert"]).strip():
                out.append(("warn", f"Binding {host} without TLS: token and book content travel in clear on the network."))
            if not split_list(str(t["allowed_hosts"])):
                out.append(("block", "Non-loopback bind needs at least one allowed host."))
        if bool(t["ssl_cert"]) != bool(t["ssl_key"]):
            out.append(("block", "TLS needs both certificate and key."))
        if not self.server_dir():
            out.append(("block", "calibre_mcp.py not found: set the server folder in Settings."))
        return out

    def refresh_all(self) -> None:
        self.validate_entries()
        http = self.tvar["mode"].get() == "http"
        for w in self.http_widgets:
            try:
                w.configure(state="normal" if http else "disabled")
            except tk.TclError:
                pass
        issues = self.transport_issues()
        self.t_issues.configure(
            text="\n".join(("\u26d4 " if s == "block" else "\u26a0 ") + m for s, m in issues),
            style="Bad.TLabel" if any(s == "block" for s, _ in issues) else "Warn.TLabel")
        self._render_preview()
        self._render_desktop_preview()
        py, how = self.python_path()
        self.sv["python"].set(f"{py}\n({how})")
        self.sv["mode"].set("HTTP (supervised)" if http else "stdio (client-owned)")
        self.sv["endpoint"].set(self.endpoint() if http else "-")
        self.banner.configure(text="" if http else
                              "stdio: Claude Desktop launches and owns the server, and the pipe carries the protocol. "
                              "Use Self-test and the Desktop log tail; switch to HTTP to supervise.")
        self._sync_buttons()

    def _fmt_cmd(self, argv: list[str]) -> str:
        return subprocess.list2cmdline(argv) if IS_WIN else " ".join(f'"{a}"' if " " in a else a for a in argv)

    def launch_lines(self, style: str, mask_token: bool) -> list[str]:
        sd = self.server_dir()
        py, _ = self.python_path()
        lines: list[str] = []
        env = self.env_values(with_token=False)
        extra = self.http_args() if self.tvar["mode"].get() == "http" else []
        argv = [py, "-u", str(sd / "calibre_mcp.py") if sd else "calibre_mcp.py"] + extra
        if style == "bat":
            lines.append(f'cd /d "{sd}"' if sd else "rem server folder not set")
            for k in sorted(env):
                lines.append(f"set {k}={env[k]}")
            if self.tvar["mode"].get() == "http" and not self.tvar["no_auth"].get():
                lines.append(f"set {TOKEN_VAR}=********" if mask_token else f"rem set {TOKEN_VAR}=<your token>")
            lines.append(self._fmt_cmd(argv))
        else:
            lines.append(f"Set-Location -LiteralPath '{sd}'" if sd else "# server folder not set")
            for k in sorted(env):
                lines.append("$env:%s = '%s'" % (k, env[k].replace("'", "''")))
            if self.tvar["mode"].get() == "http" and not self.tvar["no_auth"].get():
                lines.append(f"$env:{TOKEN_VAR} = '********'" if mask_token else f"# $env:{TOKEN_VAR} = '<your token>'")
            lines.append("& " + " ".join("'%s'" % a.replace("'", "''") for a in argv))
        return lines

    def _set_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _render_preview(self) -> None:
        self.collect_light()
        self._set_text(self.preview, "\n".join(self.launch_lines("bat", True)))

    def collect_light(self) -> None:
        """Refresh the in-memory profile without touching DPAPI or disk (used for live previews)."""
        p = self.prof
        p["env"] = {n: v.get().strip() for n, v in self.var_env.items() if v.get().strip()}
        for k, var in self.tvar.items():
            if k != "token":
                val = var.get()
                p["transport"][k] = val.strip() if isinstance(val, str) else bool(val)
        p["custom"] = dict(self.custom)
        p["server_dir"], p["python"] = self.v_server_dir.get().strip(), self.v_python.get().strip()
        p["isolate"] = self.v_isolate.get()
        self.token = self.tvar["token"].get().strip()

    def copy_launch(self, style: str) -> None:
        self.collect_light()
        self.to_clipboard("\n".join(self.launch_lines(style, False)))

    # ------------------------------------------------------------------ Claude integration
    def desktop_config_path(self) -> Path:
        return Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "Claude" / "claude_desktop_config.json"

    def desktop_log_path(self) -> Path:
        return self.desktop_config_path().parent / "logs" / f"mcp-server-{self.v_desk_name.get().strip() or 'calibre'}.log"

    def desktop_entry(self) -> dict:
        self.collect_light()
        sd = self.server_dir()
        py, _ = self.python_path()
        entry: dict[str, Any] = {"command": py, "args": [str(sd / "calibre_mcp.py") if sd else "calibre_mcp.py"]}
        env = self.env_values(with_token=False)
        env.pop(TOKEN_VAR, None)
        if env:
            entry["env"] = env
        return entry

    def _render_desktop_preview(self) -> None:
        name = self.v_desk_name.get().strip() or "calibre"
        self._set_text(self.desk_preview, json.dumps({"mcpServers": {name: self.desktop_entry()}}, indent=2))

    def write_desktop_entry(self) -> None:
        path, name = self.desktop_config_path(), self.v_desk_name.get().strip() or "calibre"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError) as e:
            messagebox.showerror(APP_NAME, f"Cannot parse {path}:\n{e}\nNothing was written.")
            return
        existing = (data.get("mcpServers") or {}).get(name)
        msg = f"{'Replace' if existing else 'Add'} the '{name}' entry in\n{path}\n\nA timestamped backup is created first. " \
              "Claude Desktop must be fully quit and restarted afterwards."
        if not messagebox.askokcancel(APP_NAME, msg):
            return
        try:
            if path.exists():
                bak = path.with_name(path.name + ".bak-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
                bak.write_bytes(path.read_bytes())
            data.setdefault("mcpServers", {})[name] = self.desktop_entry()
            atomic_write(path, json.dumps(data, indent=2))
            self.log("ui", "status", f"Claude Desktop config updated: '{name}' ({path})")
        except OSError as e:
            self.log("ui", "error", f"cannot write {path}: {e}")

    def copy_claude_code(self) -> None:
        self.collect_light()
        self.to_clipboard(f'claude mcp add --transport http {self.v_desk_name.get().strip() or "calibre"} {self.endpoint()}'
                          + (f' --header "Authorization: Bearer {self.token}"' if self.token and not self.tvar["no_auth"].get() else ""))

    def copy_mcp_remote(self) -> None:
        self.collect_light()
        name = (self.v_desk_name.get().strip() or "calibre") + "-http"
        ent: dict[str, Any] = {"command": "npx", "args": ["-y", "mcp-remote", self.endpoint()]}
        if self.token and not self.tvar["no_auth"].get():
            ent["args"] += ["--header", "Authorization:${AUTH}"]
            ent["env"] = {"AUTH": f"Bearer {self.token}"}
        self.to_clipboard(json.dumps({"mcpServers": {name: ent}}, indent=2))

    def toggle_tail(self) -> None:
        if self.v_tail.get():
            if not self.tailer or not self.tailer.is_alive():
                self.tailer = Tailer(self.desktop_log_path(), self.q)
                self.tailer.start()
                self.log("ui", "status", f"following {self.desktop_log_path()}")
        elif self.tailer:
            self.tailer.stop_ev.set()
            self.tailer = None

    # ------------------------------------------------------------------ server control
    def set_state(self, state: str) -> None:
        self.state = state
        label, col = {"stopped": ("STOPPED", C_DBG), "starting": ("STARTING", C_WARN), "running": ("RUNNING", C_OK),
                      "stopping": ("STOPPING", C_WARN), "failed": ("FAILED", C_ERR)}[state]
        if self.tvar["mode"].get() == "stdio" and state == "stopped":
            label, col = "STDIO", C_INFO
        self.pill.configure(text=label, bg=col)
        self.sv["state"].set(label.title())
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        http = self.tvar["mode"].get() == "http"
        up = self.server is not None and self.server.running
        busy = self.state in ("starting", "stopping")
        self.btn_start.configure(state="normal" if (http and not up and not busy) else "disabled")
        self.btn_stop.configure(state="normal" if (http and up and self.state != "stopping") else "disabled")
        self.btn_restart.configure(state="normal" if (http and up and not busy) else "disabled")
        t_run = self.task is not None and self.task.running
        for b in self.task_buttons.values():
            b.configure(state="disabled" if t_run else "normal")
        self.btn_seq.configure(state="disabled" if t_run else "normal")
        self.btn_cancel.configure(state="normal" if t_run else "disabled")
        if not http and self.state == "stopped":
            self.pill.configure(text="STDIO", bg=C_INFO)

    def start_server(self) -> None:
        if self.server and self.server.running:
            return
        self.save_now()
        blockers = [m for s, m in self.transport_issues() if s == "block"]
        if blockers:
            messagebox.showerror(APP_NAME, "Cannot start:\n\n" + "\n".join("- " + b for b in blockers))
            return
        spec = self.launch_spec(self.http_args(), with_token=True)
        if not spec:
            return
        cmd, env, cwd = spec
        self.server = Proc("server", "server", cmd, env, cwd, self.q)
        try:
            self.server.start()
        except OSError as e:
            self.log("ui", "error", f"cannot start server: {e}")
            self.set_state("failed")
            return
        self.n_req = 0
        self.set_state("starting")
        self.log("ui", "status", "starting: " + self._fmt_cmd(cmd))
        t = self.prof["transport"]
        host = "127.0.0.1" if t["host"] in ("0.0.0.0", "::") else t["host"]
        threading.Thread(target=self._wait_listening, args=(self.server, host, int(t["port"])), daemon=True).start()

    def _wait_listening(self, proc: Proc, host: str, port: int) -> None:
        end = time.time() + 45
        while time.time() < end and proc.running:
            try:
                with socket.create_connection((host, port), 0.4):
                    self.q.put(("listening", proc))
                    return
            except OSError:
                time.sleep(0.4)
        if proc.running:
            self.q.put(Evt(time.time(), "ui", "warning", f"server alive but nothing listening on {host}:{port} after 45 s"))

    def stop_server(self) -> None:
        if self.server and self.server.running:
            self.set_state("stopping")
            self.log("ui", "status", "stopping server")
            threading.Thread(target=self.server.stop, daemon=True).start()

    def restart_server(self) -> None:
        if not (self.server and self.server.running):
            return
        self._restart_pending = True
        self.stop_server()

    # ------------------------------------------------------------------ self-test
    def run_selftest(self) -> None:
        self.sv["test"].set("running...")
        if self.tvar["mode"].get() == "http":
            t = self.prof["transport"]
            skip = bool(t["skip_verify"]) and is_loopback(t["host"])
            threading.Thread(target=lambda: self.q.put(("selftest", mcp_http_probe(
                self.endpoint(), "" if t["no_auth"] else self.token, skip))), daemon=True).start()
        else:
            self.collect_light()
            spec = self.launch_spec([], with_token=False)
            if not spec:
                self.sv["test"].set("-")
                return
            cmd, env, cwd = spec
            threading.Thread(target=lambda: self.q.put(("selftest", mcp_stdio_selftest(cmd, env, cwd, self.q))), daemon=True).start()

    # ------------------------------------------------------------------ maintenance jobs
    def run_task_ids(self, ids: list[str]) -> None:
        if self.task and self.task.running:
            return
        self.save_now()
        self.task_queue = [t for i in ids for t in TASKS if t["id"] == i]
        self._next_task()

    def _next_task(self) -> None:
        if not self.task_queue:
            self.set_busy(False)
            self._sync_buttons()
            return
        spec = self.task_queue.pop(0)
        args = list(spec["args"])
        if spec["id"] == "ocrlangs":
            langs = str(self.task_opts["ocrlangs"]["langs"].get()).strip()
            if not langs:
                messagebox.showinfo(APP_NAME, "Enter the languages first, e.g. ita,eng.")
                self.task_queue.clear()
                return
            args.append(langs)
        for name, var in self.task_opts[spec["id"]].items():
            if spec["id"] == "ocrlangs":
                break
            val = var.get()
            if isinstance(var, tk.BooleanVar):
                if val:
                    args.append(f"--{name}")
            elif str(val).strip():
                args += [f"--{name}", str(val).strip()]
        ls = self.launch_spec(args, with_token=False)
        if not ls:
            self.task_queue.clear()
            return
        cmd, env, cwd = ls
        self.task_spec, self.task_capture = spec, []
        self.task = Proc(spec["id"], "task", cmd, env, cwd, self.q, self.task_capture if spec.get("json") else None)
        try:
            self.task.start()
        except OSError as e:
            self.log("ui", "error", f"cannot start job: {e}")
            self.task_queue.clear()
            return
        self.sv["task"].set(spec["title"])
        self.log("task", "status", f"> {spec['title']}: {self._fmt_cmd(cmd[2:])}")
        self.set_busy(True)
        self._sync_buttons()

    def cancel_task(self) -> None:
        self.task_queue.clear()
        if self.task and self.task.running:
            self._cancelled = True
            self.log("ui", "warning", "job cancelled by user")
            threading.Thread(target=self.task.stop, daemon=True).start()

    # ------------------------------------------------------------------ event pump
    def log(self, source: str, kind: str, text: str) -> None:
        self.q.put(Evt(time.time(), source, kind, text))

    def _pump(self) -> None:
        batch = 0
        try:
            while batch < 500:
                item = self.q.get_nowait()
                batch += 1
                if isinstance(item, Evt):
                    self._ingest(item)
                else:
                    self._control(item)
        except queue.Empty:
            pass
        if batch:
            self._trim_widget()
            self._update_counters()
            if self.autoscroll.get():
                self.console.see("end")
        self.after(60, self._pump)

    def _visible(self, ev: Evt) -> bool:
        if not self.kind_on[ev.kind].get():
            return False
        s = self.src_filter.get()
        if s != "all" and ev.source != s:
            return False
        needle = self.search.get().strip().lower()
        return not needle or needle in ev.text.lower()

    def _insert(self, ev: Evt) -> None:
        c = self.console
        c.configure(state="normal")
        c.insert("end", time.strftime("%H:%M:%S", time.localtime(ev.ts)) + "  ", "ts")
        c.insert("end", f"{ev.source:<8}", "src")
        c.insert("end", ev.text + "\n", ev.kind)
        c.configure(state="disabled")

    def _ingest(self, ev: Evt) -> None:
        if ev.kind == "progress":
            frac = parse_progress(ev.text)
            self._on_progress(ev, frac)
        replaced = False
        if ev.replace and self.events and self._prev_progress_src == ev.source:
            last = self.events[-1]
            if last.kind == "progress" and last.source == ev.source and last.replace:
                self.events.pop()
                replaced = True
                if self._visible(last) and self._tail_is(last):
                    self.console.configure(state="normal")
                    self.console.delete("end-2l linestart", "end-1c")
                    self.console.configure(state="disabled")
        self.events.append(ev)
        self._prev_progress_src = ev.source if (ev.kind == "progress" and ev.replace) else None
        self._tail_ev = ev
        if self._visible(ev):
            self._insert(ev)
        if not replaced:
            if ev.kind == "error" and not ev.detail:
                self.n_err += 1
                self._add_problem(ev)
            elif ev.kind == "warning":
                self.n_warn += 1
                self._add_problem(ev)
            elif ev.kind == "request" and ev.source == "server":
                self.n_req += 1

    def _tail_is(self, ev: Evt) -> bool:
        return getattr(self, "_tail_ev", None) is ev

    def _trim_widget(self) -> None:
        n = int(self.console.index("end-1c").split(".")[0])
        if n > MAX_WIDGET_LINES:
            self.console.configure(state="normal")
            self.console.delete("1.0", f"{n - MAX_WIDGET_LINES + 1000}.0")
            self.console.configure(state="disabled")

    def refilter(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        c = self.console
        c.configure(state="normal")
        for ev in self.events:
            if self._visible(ev):
                c.insert("end", time.strftime("%H:%M:%S", time.localtime(ev.ts)) + "  ", "ts")
                c.insert("end", f"{ev.source:<8}", "src")
                c.insert("end", ev.text + "\n", ev.kind)
        c.configure(state="disabled")
        if self.autoscroll.get():
            c.see("end")

    def clear_console(self) -> None:
        self.events.clear()
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _add_problem(self, ev: Evt) -> None:
        self.prob.insert("", "end", values=(time.strftime("%H:%M:%S", time.localtime(ev.ts)), ev.source, ev.text[:400]),
                         tags=(ev.kind,))
        kids = self.prob.get_children()
        if len(kids) > MAX_PROBLEMS:
            self.prob.delete(*kids[: len(kids) - MAX_PROBLEMS])
        self.prob.see(self.prob.get_children()[-1])

    def clear_problems(self) -> None:
        self.prob.delete(*self.prob.get_children())
        self.n_err = self.n_warn = 0
        self._update_counters()

    def copy_problems(self, selected: bool = False) -> None:
        items = self.prob.selection() if selected else self.prob.get_children()
        self.to_clipboard("\n".join(" ".join(str(x) for x in self.prob.item(i, "values")) for i in items))

    def save_log(self) -> None:
        p = filedialog.asksaveasfilename(defaultextension=".log", initialfile=f"calibre-mcp-{time.strftime('%Y%m%d-%H%M%S')}.log")
        if p:
            Path(p).write_text("\n".join(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.ts))} [{e.source}] [{e.kind}] {e.text}"
                                         for e in self.events) + "\n", encoding="utf-8")
            self.log("ui", "status", f"log saved: {p}")

    def _update_counters(self) -> None:
        self.sv["req"].set(str(self.n_req))
        self.sv["warn"].set(str(self.n_warn))
        self.sv["err"].set(str(self.n_err))
        self.counters.set(f"{self.n_err} errors   {self.n_warn} warnings   {self.n_req} requests")
        self.prob_title.configure(text=f"PROBLEMS  ({self.n_err} err / {self.n_warn} warn)")

    # progress strip
    def set_busy(self, on: bool) -> None:
        if on:
            self.pbar.configure(mode="indeterminate")
            self.pbar.start(14)
            self.pl.set(f"Running: {self.task_spec['title']}" if self.task_spec else "Running")
        else:
            self.pbar.stop()
            self.pbar.configure(mode="determinate", value=0)
            self.pl.set("Idle")
            self.sv["task"].set("-")

    def _on_progress(self, ev: Evt, frac: Optional[float]) -> None:
        self._last_progress_t = time.time()
        label = re.sub(r"^\s*(\d{4}-\d\d-\d\d[ T])?\d\d:\d\d:\d\d[.,\d]*\s*", "", ev.text)[:110]
        self.pl.set(label)
        if frac is not None:
            if str(self.pbar.cget("mode")) != "determinate":
                self.pbar.stop()
                self.pbar.configure(mode="determinate")
            self.pbar.configure(value=frac * 100)

    # control messages from threads
    def _control(self, item: tuple) -> None:
        kind = item[0]
        if kind == "exit":
            proc: Proc = item[1]
            if proc is self.server:
                restart = getattr(self, "_restart_pending", False)
                expected = self.state == "stopping"
                self.log("ui", "status" if (expected or proc.rc == 0) else "error",
                         f"server exited (code {proc.rc})")
                self.set_state("stopped" if (expected or proc.rc == 0) else "failed")
                self.sv["pid"].set("-")
                if restart:
                    self._restart_pending = False
                    self.after(300, self.start_server)
            elif proc is self.task:
                spec = self.task_spec or {}
                ok = proc.rc == 0
                if spec.get("json"):
                    self._load_status_json(self.task_capture, ok)
                was_cancelled, self._cancelled = self._cancelled, False
                self.log("task", "status" if (ok or was_cancelled) else "error",
                         f"{spec.get('title', 'job')} " + ("cancelled" if was_cancelled else f"finished (code {proc.rc})"))
                if not ok:
                    self.task_queue.clear()
                self.task = None
                self._next_task()
                if not self.task_queue and not (self.task and self.task.running):
                    self.set_busy(False)
                self._sync_buttons()
        elif kind == "listening":
            if item[1] is self.server and self.state == "starting":
                self.started_at = time.time()
                self.set_state("running")
                self.sv["pid"].set(str(self.server.pid))
                self.log("ui", "status", f"listening on {self.endpoint()}")
                self.run_selftest()
        elif kind == "selftest":
            self._show_selftest(item[1])

    def _show_selftest(self, r: dict) -> None:
        if r.get("ok"):
            tools = r.get("tools", [])
            self.sv["test"].set(f"OK - {r.get('server', '?')}, {len(tools)} tools, {r.get('latency_ms', '?')} ms")
            self.log("test", "status", f"self-test OK: {len(tools)} tools ({', '.join(tools[:6])}{', ...' if len(tools) > 6 else ''})")
        else:
            self.sv["test"].set("FAILED - " + str(r.get("error", "unknown")))
            self.log("test", "error", "self-test failed: " + str(r.get("error", "unknown")))

    def _load_status_json(self, lines: list[str], ok: bool) -> None:
        text = "\n".join(lines).strip()
        self.status_tree.delete(*self.status_tree.get_children())
        if not ok:
            for ln in lines[-10:]:
                self.log("task", "error", ln)
            return
        try:
            start = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [0])
            data = json.loads(text[start:])
        except ValueError:
            self.log("task", "error", "status output is not valid JSON")
            for ln in lines[-10:]:
                self.log("task", "status", ln)
            return
        self._fill_tree(data, "")
        self.log("task", "status", "status refreshed")

    def _fill_tree(self, data: Any, parent: str) -> None:
        items = data.items() if isinstance(data, dict) else ((f"[{i}]", v) for i, v in enumerate(data[:300]))
        for k, v in items:
            if isinstance(v, (dict, list)):
                iid = self.status_tree.insert(parent, "end", text=str(k), open=(parent == ""),
                                              values=(f"{len(v)} {'keys' if isinstance(v, dict) else 'items'}",))
                self._fill_tree(v, iid)
            else:
                tag = ("null",) if v is None else ("bad",) if ("error" in str(k).lower() and v) else ()
                self.status_tree.insert(parent, "end", text=str(k), values=("-" if v is None else str(v)[:300],), tags=tag)

    def _tick(self) -> None:
        if self.state == "running":
            self.sv["uptime"].set(fmt_dur(time.time() - self.started_at))
        elif self.state in ("stopped", "failed"):
            self.sv["uptime"].set("-")
        if not (self.task and self.task.running) and self._last_progress_t and time.time() - self._last_progress_t > 10:
            self._last_progress_t = 0
            self.pbar.configure(value=0)
            self.pl.set("Idle")
        self.after(1000, self._tick)

    # ------------------------------------------------------------------ shutdown
    def on_close(self) -> None:
        if self.task and self.task.running:
            if not messagebox.askyesno(APP_NAME, "A maintenance job is running. Cancel it and exit?"):
                return
            self.task_queue.clear()
            self.task.stop(2)
        if self.server and self.server.running:
            self.server.stop(4)
        if self.tailer:
            self.tailer.stop_ev.set()
        self.save_now()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
