"""Parse the raw product PDF into structured content (content.json + image assets).

The raw file is authored as a simple document: serif headings, sans-serif body
text, bullet lists, a spec table and photos. This module walks the document in
reading order and rebuilds that structure so the brochure can be re-rendered
whenever the raw file changes.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

BULLET_CHARS = "●•▪◦■-–"
ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff"), None)
PLACEHOLDER_VALUES = {"", "person", "place", "calendar event", "file", "tbd", "todo"}
MIN_IMAGE_PX = 120

SUBHEAD_RE = re.compile(
    r"(highlights?|applications?|features?|benefits?|specifications?|uses?)\s*:?\s*$", re.I
)
NUMBERED_ITEM_RE = re.compile(r"^(\d{1,2})[.)]\s+(.+)$")
TREND_ITEM_RE = re.compile(r"^(trend|look|style|idea)\s*(\d{1,2})\s*[:.\-–]\s*(.+)$", re.I)


def clean(text: str) -> str:
    text = text.translate(ZERO_WIDTH).replace("\u2212", "-")
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def font_family(font: str) -> str:
    return re.split(r"[-,]", font)[0].lower()


def section_type(title: str) -> str:
    t = title.lower()
    if re.search(r"spec|matrix|technical", t):
        return "specs"
    if re.search(r"order|contact|consult|enquir|inquir|get in touch", t):
        return "contact"
    if re.search(r"project|customer|portfolio|installation|gallery", t):
        return "gallery"
    if re.search(r"trend|inspiration|lookbook|mood", t):
        return "trends"
    if re.search(r"collection|product|range", t):
        return "products"
    return "generic"


def group_kind(title: str) -> str:
    t = title.lower()
    if "application" in t or "use" in t:
        return "applications"
    if re.search(r"highlight|feature|benefit", t):
        return "highlights"
    return "other"


@dataclass
class El:
    kind: str  # heading | para | bullet | blank | image | table
    y: float
    x: float = 0.0
    text: str = ""
    size: float = 0.0
    page: int = 0
    data: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Stream building
# --------------------------------------------------------------------------- #

def detect_fonts(doc: pymupdf.Document) -> str:
    counts: Counter[str] = Counter()
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    counts[font_family(span["font"])] += len(span["text"].strip())
    return counts.most_common(1)[0][0]


def find_tables(page: pymupdf.Page) -> list[El]:
    found = []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            tables = page.find_tables().tables
    except Exception:
        return found
    for tb in tables:
        rows, boxes = [], []
        for raw_row, row in zip(tb.extract(), tb.rows):
            cells = [clean(c or "") for c in raw_row]
            filled = [c for c in cells if c]
            if len(filled) >= 2 and all(len(c) < 60 for c in filled):
                rows.append(cells)
                boxes.append(pymupdf.Rect(row.bbox))
        if len(rows) < 2:
            continue
        keep = [i for i in range(len(rows[0])) if any(r[i] for r in rows)]
        rows = [[r[i] for i in keep] for r in rows]
        bbox = boxes[0]
        for b in boxes[1:]:
            bbox |= b
        found.append(El("table", bbox.y0, bbox.x0, data={"rows": rows, "bbox": bbox}))
    return found


def page_elements(doc, page, page_no, body_font, assets_dir, seen) -> list[El]:
    els: list[El] = []
    tables = find_tables(page)
    els.extend(tables)
    table_boxes = [t.data["bbox"] for t in tables]

    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            raw = "".join(s["text"] for s in spans)
            text = clean(raw)
            x0, y0 = line["bbox"][0], line["bbox"][1]
            if any(pymupdf.Rect(line["bbox"]).intersects(b) for b in table_boxes):
                continue
            if not text:
                els.append(El("blank", y0, x0, page=page_no))
                continue
            if text[0] in BULLET_CHARS and (len(text) == 1 or text[1] == " "):
                els.append(El("bullet", y0, x0, clean(text[1:]), page=page_no))
                continue
            weighted = Counter()
            for s in spans:
                weighted[font_family(s["font"])] += len(s["text"].strip())
            dominant = weighted.most_common(1)[0][0]
            size = max(s["size"] for s in spans if s["text"].strip())
            kind = "heading" if dominant != body_font else "para"
            els.append(El(kind, y0, x0, text, size, page_no))

    for img in page.get_images(full=True):
        xref, smask, w, h = img[0], img[1], img[2], img[3]
        if min(w, h) < MIN_IMAGE_PX:
            continue
        rects = page.get_image_rects(xref)
        if not rects:
            continue
        path = save_image(doc, xref, smask, assets_dir, seen)
        if path is None:
            continue
        top = max(rects[0].y0, 0)
        els.append(El("image", top, rects[0].x0, page=page_no,
                      data={"src": path, "w": w, "h": h}))

    # Merge lines that share a baseline (e.g. a bullet label and its value chip).
    els.sort(key=lambda e: (round(e.y / 4), e.x))
    return els


def save_image(doc, xref, smask, assets_dir: Path, seen: dict) -> str | None:
    if xref in seen:
        return None  # repeated image (e.g. a header logo) - keep first only
    if smask:
        pix = pymupdf.Pixmap(pymupdf.Pixmap(doc, xref), pymupdf.Pixmap(doc, smask))
        data, ext = pix.tobytes("png"), "png"
    else:
        info = doc.extract_image(xref)
        data, ext = info["image"], info["ext"]
        if ext not in ("jpeg", "jpg", "png", "webp"):
            data, ext = pymupdf.Pixmap(doc, xref).tobytes("png"), "png"
    digest = hashlib.sha1(data).hexdigest()[:10]
    if digest in seen.values():
        seen[xref] = digest
        return None
    seen[xref] = digest
    name = f"img-{digest}.{ext}"
    (assets_dir / name).write_bytes(data)
    return f"assets/{name}"


# --------------------------------------------------------------------------- #
# Structure building
# --------------------------------------------------------------------------- #

def split_label(text: str) -> tuple[str | None, str]:
    m = re.match(r"^([^:]{2,70}):\s*(.*)$", text)
    if m and ". " not in m.group(1):
        return clean(m.group(1)), clean(m.group(2))
    return None, text


def sentence(text: str) -> str:
    text = text.strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def build_structure(stream: list[El]) -> dict:
    doc: dict = {"title": None, "intro": [], "logo": None, "sections": []}
    section = None
    item = None
    group = None
    para_buf: list[str] = []
    last_bullet = None
    last_kind = None

    def target():
        return item if item is not None else (section if section is not None else doc)

    def flush_para():
        nonlocal para_buf
        if para_buf:
            tgt = target()
            key = "intro" if tgt is doc else "paragraphs"
            tgt.setdefault(key, []).append(clean(" ".join(para_buf)))
            para_buf = []

    for el in stream:
        if el.kind == "blank":
            if last_kind == "para":
                flush_para()
            continue

        if el.kind == "para" and last_bullet is not None and el.x > last_bullet["x"] + 4:
            last_bullet["text"] = clean(last_bullet["text"] + " " + el.text)
            continue

        if el.kind != "para":
            flush_para()

        if el.kind == "heading":
            last_bullet = None
            title = el.text.rstrip(":").strip()
            if SUBHEAD_RE.search(title) and (section is not None):
                group = {"title": title, "kind": group_kind(title), "items": []}
                target().setdefault("groups", []).append(group)
            elif (m := NUMBERED_ITEM_RE.match(title)) and section is not None:
                item = new_item(int(m.group(1)), m.group(2))
                section.setdefault("items", []).append(item)
                group = None
            elif (m := TREND_ITEM_RE.match(title)) and section is not None:
                item = new_item(int(m.group(2)), m.group(3))
                section.setdefault("items", []).append(item)
                group = None
            elif doc["title"] is None and section is None:
                doc["title"] = title
            else:
                section = {"title": title, "type": section_type(title), "slug": slugify(title)}
                doc["sections"].append(section)
                item = group = None
        elif el.kind == "para":
            last_bullet = None
            para_buf.append(el.text)
        elif el.kind == "bullet":
            entry = {"text": el.text, "x": el.x}
            if group is None:
                group = {"title": "", "kind": "other", "items": []}
                target().setdefault("groups", []).append(group)
            group["items"].append(entry)
            last_bullet = entry
        elif el.kind == "image":
            last_bullet = None
            if doc["logo"] is None and section is None and not doc["sections"]:
                doc["logo"] = el.data["src"]
            else:
                target().setdefault("images", []).append(el.data)
        elif el.kind == "table":
            last_bullet = None
            target().setdefault("tables", []).append(el.data["rows"])
        last_kind = el.kind
    flush_para()

    finalize(doc)
    return doc


def new_item(number: int, title: str) -> dict:
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", title)
    name, subtitle = (m.group(1), m.group(2)) if m else (title, "")
    return {"number": number, "name": clean(name), "subtitle": clean(subtitle),
            "slug": slugify(name)}


def finalize(node: dict) -> None:
    for group in node.get("groups", []):
        items = []
        for entry in group["items"]:
            text = clean(entry["text"])
            if group["kind"] == "applications":
                items.append({"label": None, "text": sentence(text.rstrip(",;. "))})
            else:
                label, body = split_label(text)
                body = sentence(body)
                if body and body[-1] not in ".!?":
                    body += "."
                items.append({"label": label, "text": body})
        group["items"] = items
    for table in node.pop("tables", []):
        header, *rows = table
        node["table"] = {"columns": header, "rows": rows}
    for child in node.get("sections", []) + node.get("items", []):
        finalize(child)


# --------------------------------------------------------------------------- #
# Logo
# --------------------------------------------------------------------------- #

def process_logo(src: Path, out_dir: Path) -> dict:
    img = Image.open(src).convert("RGB")
    gray = ImageOps.invert(img.convert("L"))
    bbox = gray.point(lambda v: 255 if v > 25 else 0).getbbox()
    if bbox:
        pad = 6
        bbox = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height))
        img = img.crop(bbox)
    r, g, b = img.split()
    alpha = Image.eval(Image.merge("RGB", (r, g, b)).convert("L"), lambda v: 255 - v)
    alpha = alpha.point(lambda v: min(255, int(v * 1.6)))

    color = img.copy().convert("RGBA")
    color.putalpha(alpha)
    white = Image.new("RGBA", img.size, (255, 255, 255, 0))
    white.putalpha(alpha)

    color.save(out_dir / "logo-color.png")
    white.save(out_dir / "logo-white.png")
    return {"color": "assets/logo-color.png", "white": "assets/logo-white.png"}


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def extract(pdf_path: Path, out_dir: Path) -> dict:
    assets = out_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for old in assets.glob("img-*"):
        old.unlink()

    doc = pymupdf.open(pdf_path)
    body_font = detect_fonts(doc)
    seen: dict = {}
    stream: list[El] = []
    for i, page in enumerate(doc):
        stream.extend(page_elements(doc, page, i + 1, body_font, assets, seen))

    content = build_structure(stream)
    if content["logo"]:
        content["logo"] = process_logo(out_dir / content["logo"], assets)
    content["source"] = {"file": pdf_path.name, "pages": doc.page_count,
                         "title": doc.metadata.get("title") or pdf_path.stem}
    return content


def is_placeholder(value: str | None) -> bool:
    return clean(value or "").lower() in PLACEHOLDER_VALUES
