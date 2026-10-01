"""Figures: list and extract images from EPUB / PDF, render PDF pages (for vector diagrams).

Ids are stable and shared with the Markdown output of calibre_read_section:
  EPUB  s<section>-<n>    n-th <img>/<svg:image> of spine section <section>, document order, 1-based
  PDF   p<page>-x<xref>   embedded image object <xref> on 1-based <page>

Untrusted input: images come from third-party files. Guards: zip member/total size caps and
in-archive path confinement, a pixel budget checked from image headers BEFORE decoding
(decompression bombs), SVG only ever rasterised (never passed on as markup), output re-encoded.
"""
from __future__ import annotations

import functools
import io
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import unquote

MAX_PIXELS = 40_000_000          # decoded-size budget (e.g. 8000 x 5000); larger images are refused
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PX_OUT = 2000
_IMG_EXT = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif", ".webp": "webp",
            ".svg": "svg", ".bmp": "bmp", ".tif": "tiff", ".tiff": "tiff"}
_CAPTION_RX = re.compile(r"^\s*(figure|figura|fig\.|table|tabella|tab\.|chart|diagram|image)\s*[\dIVXLC]",
                         re.IGNORECASE)


class FigureError(ValueError):
    pass


# --------------------------------------------------------------------------- EPUB scanning
class _ImgScan(HTMLParser):
    """Collect images in document order with alt text and a caption (figcaption, or the next
    short text block that looks like 'Figure 3-2 ...')."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, Any]] = []
        self._fig_depth = 0
        self._fig_items: list[int] = []
        self._in_caption = 0
        self._caption: list[str] = []
        self._pending: Optional[int] = None   # image waiting for a following caption-like text
        self._pending_budget = 0
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "figure":
            self._fig_depth += 1
            self._fig_items = []
        elif tag == "figcaption" and self._fig_depth:
            self._in_caption += 1
            self._caption = []
        elif tag in ("img", "image"):
            src = a.get("src") or a.get("xlink:href") or a.get("href") or ""
            self.items.append({"src": src, "alt": (a.get("alt") or a.get("title") or "").strip(), "caption": None})
            idx = len(self.items) - 1
            if self._fig_depth:
                self._fig_items.append(idx)
            else:
                self._pending, self._pending_budget = idx, 400

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "figcaption" and self._in_caption:
            self._in_caption -= 1
            cap = " ".join("".join(self._caption).split())
            for i in self._fig_items:
                self.items[i]["caption"] = cap or self.items[i]["caption"]
        elif tag == "figure" and self._fig_depth:
            self._fig_depth -= 1

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_caption:
            self._caption.append(data)
            return
        txt = data.strip()
        if self._pending is not None and txt:
            if _CAPTION_RX.match(txt):
                self.items[self._pending]["caption"] = " ".join(txt.split())[:300]
                self._pending = None
            else:
                self._pending_budget -= len(txt)
                if self._pending_budget <= 0:
                    self._pending = None


def _zip_bytes(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = z.getinfo(name)
    if info.file_size > limit:
        raise FigureError(f"embedded file too large ({info.file_size} bytes)")
    with z.open(info) as f:
        data = f.read(limit + 1)          # do not trust header sizes alone
    if len(data) > limit:
        raise FigureError("embedded file exceeds size limit")
    return data


@functools.lru_cache(maxsize=16)
def epub_figures(path: str, _mtime: float, _size: int, spine_hrefs: tuple[str, ...]) -> list[dict[str, Any]]:
    """All images of the spine sections, in order. spine_hrefs comes from the text parser so that
    section indices are identical to calibre_get_toc / calibre_read_section."""
    out: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for si, href in enumerate(spine_hrefs):
            if href not in names:
                continue
            p = _ImgScan()
            try:
                p.feed(_zip_bytes(z, href, 16 * 1024 * 1024).decode("utf-8", errors="replace"))
                p.close()
            except (FigureError, zipfile.BadZipFile, KeyError):
                continue
            base = posixpath.dirname(href)
            for n, it in enumerate(p.items, 1):
                src = it["src"]
                if not src or src.startswith(("data:", "http:", "https:", "//")):
                    target, size = None, None
                else:
                    target = posixpath.normpath(posixpath.join(base, unquote(src.split("#")[0])))
                    if ".." in target.split("/") or target not in names:
                        target = None
                    size = z.getinfo(target).file_size if target else None
                ext = posixpath.splitext(target or "")[1].lower()
                out.append({"id": f"s{si}-{n}", "section": si, "member": target, "bytes": size,
                            "format": _IMG_EXT.get(ext), "alt": it["alt"] or None, "caption": it["caption"],
                            "available": bool(target) and ext in _IMG_EXT})
    return out


def epub_figure_bytes(path: str, member: str) -> bytes:
    with zipfile.ZipFile(path) as z:
        return _zip_bytes(z, member, MAX_IMAGE_BYTES)


# --------------------------------------------------------------------------- image normalisation
def _pymupdf():
    try:
        import pymupdf  # type: ignore
        return pymupdf
    except ImportError:
        try:
            import fitz  # type: ignore
            return fitz
        except ImportError:
            return None


def _check_pixels(w: int, h: int) -> None:
    if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
        raise FigureError(f"image of {w}x{h} px refused (pixel budget {MAX_PIXELS:,}): possible decompression bomb")


def normalise(data: bytes, fmt: Optional[str], max_px: int) -> tuple[bytes, str]:
    """Decode an untrusted image safely and re-encode it (PNG or JPEG), longest side <= max_px."""
    max_px = max(64, min(max_px, MAX_PX_OUT))
    mu = _pymupdf()
    if fmt == "svg":
        if mu is None:
            raise FigureError("SVG figures need PyMuPDF (pip install pymupdf)")
        try:
            doc = mu.open(stream=data, filetype="svg")
        except Exception as exc:  # noqa: BLE001 - malformed third-party SVG
            raise FigureError(f"unreadable SVG: {exc}") from exc
        with doc:
            r = doc[0].rect
            _check_pixels(int(r.width) or 1, int(r.height) or 1)
            scale = min(4.0, (max_px - 1) / max(r.width, r.height, 1))
            pix = doc[0].get_pixmap(matrix=mu.Matrix(scale, scale), alpha=False)
            return pix.tobytes("png"), "png"
    try:
        from PIL import Image as PILImage  # type: ignore
        PILImage.MAX_IMAGE_PIXELS = MAX_PIXELS
        with PILImage.open(io.BytesIO(data)) as im:          # lazy: reads the header only
            _check_pixels(*im.size)
            im.seek(0)
            im.thumbnail((max_px, max_px))
            has_alpha = im.mode in ("RGBA", "LA", "P")
            buf = io.BytesIO()
            if fmt in ("png", "gif", "bmp") or has_alpha:
                im.convert("RGBA" if has_alpha else "RGB").save(buf, "PNG", optimize=True)
                return buf.getvalue(), "png"
            im.convert("RGB").save(buf, "JPEG", quality=85)
            return buf.getvalue(), "jpeg"
    except ImportError:
        pass
    except FigureError:
        raise
    except Exception as exc:  # noqa: BLE001 - PIL raises many types on hostile input
        if "DecompressionBomb" in type(exc).__name__:
            raise FigureError(f"image refused (pixel budget {MAX_PIXELS:,}): possible decompression bomb") from exc
        raise FigureError(f"unreadable image: {exc}") from exc
    if mu is not None:
        try:
            pix = mu.Pixmap(data)
        except Exception as exc:  # noqa: BLE001
            raise FigureError(f"unreadable image: {exc}") from exc
        _check_pixels(pix.width, pix.height)
        if pix.alpha or (pix.colorspace and pix.colorspace.n not in (1, 3)):
            pix = mu.Pixmap(mu.csRGB, pix)
        while max(pix.width, pix.height) > max_px:
            pix.shrink(1)
        return pix.tobytes("png"), "png"
    raise FigureError("No image library: pip install pillow (or pymupdf)")


# --------------------------------------------------------------------------- PDF
def pdf_figures(path: str, start: int, end: int) -> list[dict[str, Any]]:
    mu = _pymupdf()
    if mu is None:
        raise FigureError("PDF figures need PyMuPDF: pip install pymupdf")
    out: list[dict[str, Any]] = []
    with mu.open(path) as doc:
        end = min(end, doc.page_count)
        for pno in range(start - 1, end):
            page = doc[pno]
            captions = [b[4].strip() for b in page.get_text("blocks") if _CAPTION_RX.match(b[4] or "")]
            imgs = page.get_images(full=True)
            seen = set()
            for img in imgs:
                xref, w, h = img[0], img[2], img[3]
                if xref in seen:
                    continue
                seen.add(xref)
                rects = page.get_image_rects(xref)
                area = sum(r.width * r.height for r in rects) / max(page.rect.width * page.rect.height, 1)
                out.append({"id": f"p{pno + 1}-x{xref}", "page": pno + 1, "kind": "image", "px": [w, h],
                            "page_area": round(area, 3), "caption": captions[0][:300] if captions else None})
            if captions and not imgs:  # caption but no raster image: a vector drawing -> render the page
                out.append({"id": f"p{pno + 1}-render", "page": pno + 1, "kind": "vector",
                            "caption": captions[0][:300], "hint": "use calibre_render_page on this page"})
    return out


def pdf_figure_bytes(path: str, page: int, xref: int, max_px: int) -> tuple[bytes, str]:
    mu = _pymupdf()
    if mu is None:
        raise FigureError("PDF figures need PyMuPDF: pip install pymupdf")
    with mu.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            raise FigureError(f"page out of range (1..{doc.page_count})")
        if xref not in {i[0] for i in doc[page - 1].get_images(full=True)}:
            raise FigureError(f"image x{xref} is not on page {page}")
        info = doc.extract_image(xref)
        _check_pixels(info.get("width", 0), info.get("height", 0))
        pix = mu.Pixmap(doc, xref)
        if pix.alpha or (pix.colorspace and pix.colorspace.n not in (1, 3)):
            pix = mu.Pixmap(mu.csRGB, pix)
        max_px = max(64, min(max_px, MAX_PX_OUT))
        while max(pix.width, pix.height) > max_px:
            pix.shrink(1)
        return pix.tobytes("png"), "png"


def pdf_render(path: str, page: int, max_px: int, clip: Optional[list[float]] = None) -> tuple[bytes, str]:
    """Render a page (or a relative area x0,y0,x1,y1 in 0..1) to PNG: vector diagrams included."""
    mu = _pymupdf()
    if mu is None:
        raise FigureError("Page rendering needs PyMuPDF: pip install pymupdf")
    with mu.open(path) as doc:
        if not 1 <= page <= doc.page_count:
            raise FigureError(f"page out of range (1..{doc.page_count})")
        pg = doc[page - 1]
        rect = pg.rect
        if clip:
            if len(clip) != 4 or not all(0 <= v <= 1 for v in clip) or clip[0] >= clip[2] or clip[1] >= clip[3]:
                raise FigureError("clip must be [x0, y0, x1, y1] with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1")
            rect = mu.Rect(rect.x0 + clip[0] * rect.width, rect.y0 + clip[1] * rect.height,
                           rect.x0 + clip[2] * rect.width, rect.y0 + clip[3] * rect.height)
        max_px = max(64, min(max_px, MAX_PX_OUT))
        scale = (max_px - 1) / max(rect.width, rect.height, 1)   # MuPDF rounds up: stay <= max_px
        _check_pixels(int(rect.width * scale) + 1, int(rect.height * scale) + 1)
        pix = pg.get_pixmap(matrix=mu.Matrix(scale, scale), clip=rect, alpha=False)
        return pix.tobytes("png"), "png"
