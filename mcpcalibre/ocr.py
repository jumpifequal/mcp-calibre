"""OCR for scanned PDFs (batch only: --extract-missing). Read-only: the PDF is never modified; the
recognised text goes to the server's cache like any other extraction.

Engine (CALIBRE_MCP_OCR_ENGINE)
  auto       default: tesseract if found, else none
  tesseract  Tesseract OCR: fast on CPU (~1-3 s/page), faithful (it transcribes, never invents)
  none       disabled
Only pages without a usable text layer are recognised; pages with text are kept as they are.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

MIN_PAGE_CHARS = 30          # a page with less text than this is treated as scanned
DPI = int(os.environ.get("CALIBRE_MCP_OCR_DPI", "300"))
PAGE_TIMEOUT = int(os.environ.get("CALIBRE_MCP_OCR_PAGE_TIMEOUT", "180"))
MAX_PIXELS = 40_000_000      # rendering budget per page (huge pages are rendered at a lower dpi)
TESSDATA_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{lang}.traineddata"
# Calibre stores ISO 639-2 codes; Tesseract mostly uses the same 3-letter names
_LANG_ALIAS = {"fre": "fra", "ger": "deu", "dut": "nld", "gre": "ell", "chi": "chi_sim", "cze": "ces",
               "rum": "ron", "slo": "slk", "per": "fas", "wel": "cym"}


def _proc_flags() -> int:
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    return 0


class OcrError(ValueError):
    pass


class TesseractEngine:
    def __init__(self, exe: str, tessdata: Optional[str]):
        self.exe, self.tessdata = exe, tessdata
        self.name = "tesseract"

    def _base(self) -> list[str]:
        return [self.exe] + (["--tessdata-dir", self.tessdata] if self.tessdata else [])

    def languages(self) -> list[str]:
        try:
            r = subprocess.run(self._base() + ["--list-langs"], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL, creationflags=_proc_flags())
        except (OSError, subprocess.TimeoutExpired):
            return []
        out = (r.stdout or "") + (r.stderr or "")
        return sorted({ln.strip() for ln in out.splitlines()[1:] if ln.strip() and " " not in ln.strip()} - {"osd"})

    def page_text(self, png: bytes, langs: str) -> str:
        env = dict(os.environ, OMP_THREAD_LIMIT=str(max(1, (os.cpu_count() or 2) // 2)))
        with tempfile.TemporaryDirectory(prefix="calibre-mcp-ocr-") as td:
            img = Path(td) / "page.png"
            img.write_bytes(png)
            try:   # list argv, no shell; stdout captured, never reaches the MCP stream
                r = subprocess.run(self._base() + [str(img), "stdout", "-l", langs, "--psm", "3"],
                                   capture_output=True, timeout=PAGE_TIMEOUT, stdin=subprocess.DEVNULL,
                                   env=env, creationflags=_proc_flags())
            except subprocess.TimeoutExpired as exc:
                raise OcrError(f"tesseract timed out after {PAGE_TIMEOUT}s on a page") from exc
            if r.returncode != 0:
                raise OcrError("tesseract failed: " + (r.stderr or b"").decode("utf-8", "replace").strip()[-300:])
            return r.stdout.decode("utf-8", "replace")


def find_tesseract(program_files: list[str]) -> Optional[str]:
    cand = [os.environ.get("CALIBRE_MCP_TESSERACT"), shutil.which("tesseract")]
    if sys.platform == "win32":
        bases = list(program_files) + [str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")]
        cand += [str(Path(b) / "Tesseract-OCR" / "tesseract.exe") for b in bases if b]
    return next((c for c in cand if c and Path(c).is_file()), None)


def tessdata_dir(data_dir: Path) -> Optional[str]:
    """Our own language files (downloaded by --download-ocr-langs) win; else Tesseract's default."""
    env = os.environ.get("CALIBRE_MCP_TESSDATA")
    if env:
        return env
    own = data_dir / "tessdata"
    return str(own) if any(own.glob("*.traineddata")) else None


def get_engine(data_dir: Path, program_files: list[str]):
    """Engine object or None (OCR disabled / not installed)."""
    choice = os.environ.get("CALIBRE_MCP_OCR_ENGINE", "auto").lower()
    if choice == "none":
        return None
    if choice not in ("auto", "tesseract"):
        raise OcrError(f"Unknown CALIBRE_MCP_OCR_ENGINE {choice!r}: use auto, tesseract or none")
    exe = find_tesseract(program_files)
    if exe:
        return TesseractEngine(exe, tessdata_dir(data_dir))
    if choice == "tesseract":
        raise OcrError("Tesseract not found: install it (install.ps1 sets it up) or set CALIBRE_MCP_TESSERACT")
    return None


def pick_languages(engine, book_langs: list[str]) -> str:
    have = set(engine.languages())
    wanted = [_LANG_ALIAS.get(l, l) for l in book_langs if l]
    wanted += [x for x in os.environ.get("CALIBRE_MCP_OCR_LANGS", "ita+eng").split("+") if x]
    seen, out = set(), []
    for l in wanted:
        if l in have and l not in seen:
            seen.add(l)
            out.append(l)
    return "+".join(out[:3]) or ("eng" if "eng" in have else (sorted(have)[0] if have else "eng"))


def needs_ocr(page_texts: list[str]) -> bool:
    """Scanned (or mostly scanned) PDF: most pages lack a usable text layer."""
    if not page_texts:
        return False
    thin = sum(1 for t in page_texts if len(t.strip()) < MIN_PAGE_CHARS)
    return thin / len(page_texts) >= 0.3


def ocr_pdf(path: str, engine, langs: str, force: bool = False,
            progress: Callable[[str], None] = lambda m: None) -> tuple[str, dict[str, Any]]:
    """Text of every page: the existing text layer where usable, OCR elsewhere (or everywhere if force)."""
    import pymupdf  # PyMuPDF renders the pages
    t0, ocr_pages = time.monotonic(), 0
    parts: list[str] = []
    with pymupdf.open(path) as doc:
        n = doc.page_count
        for i, page in enumerate(doc):
            existing = page.get_text("text")
            if not force and len(existing.strip()) >= MIN_PAGE_CHARS:
                parts.append(existing)
                continue
            r = page.rect
            dpi = DPI
            if (r.width / 72 * dpi) * (r.height / 72 * dpi) > MAX_PIXELS:   # huge pages: lower dpi, bounded memory
                dpi = int(72 * (MAX_PIXELS / max(r.width * r.height, 1)) ** 0.5)
            png = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY).tobytes("png")
            parts.append(engine.page_text(png, langs))
            ocr_pages += 1
            if ocr_pages % 10 == 0:
                progress(f"    OCR {i + 1}/{n} pages")
    return "\n\n".join(parts), {"pages": n, "ocr_pages": ocr_pages, "engine": engine.name, "languages": langs,
                                "seconds": round(time.monotonic() - t0, 1)}


def download_languages(dest: Path, langs: list[str]) -> dict[str, Any]:
    """Fetch tessdata_fast language files into dest (setup step, like the embedding model)."""
    dest.mkdir(parents=True, exist_ok=True)
    done = {}
    for lang in langs:
        lang = lang.strip()
        if not lang or not all(c.isalnum() or c == "_" for c in lang):
            raise OcrError(f"bad language code {lang!r}")
        target = dest / f"{lang}.traineddata"
        tmp = target.with_suffix(".part")
        try:
            with urllib.request.urlopen(TESSDATA_URL.format(lang=lang), timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
        except OSError as exc:
            raise OcrError(f"download of {lang} failed: {exc} (proxy? set HTTPS_PROXY)") from exc
        tmp.replace(target)
        done[lang] = round(target.stat().st_size / 2 ** 20, 1)
    return {"tessdata": str(dest), "languages_mb": done}
