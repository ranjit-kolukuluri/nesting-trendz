"""Build the Nesting Trendz marketing brochure from the raw product PDF.

    python brochure/build.py                 # newest PDF in /source
    python brochure/build.py path/to/raw.pdf # explicit source file
    python brochure/build.py --preview       # also write page PNGs for review
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, str(Path(__file__).parent))
from extract import extract, is_placeholder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
PAGE_SIZES = {"letter": ("8.5in", "11in"), "a4": ("210mm", "297mm")}

warnings: list[str] = []


def warn(msg: str) -> None:
    warnings.append(msg)


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    with open(HERE / "config.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_source(arg: str | None, cfg: dict) -> Path:
    if arg:
        return Path(arg).resolve()
    configured = cfg.get("source", "auto")
    if configured and configured != "auto":
        return (ROOT / configured).resolve()
    pdfs = sorted((ROOT / "source").glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        sys.exit("No PDF found in /source. Drop the raw brochure PDF there and re-run.")
    if len(pdfs) > 1:
        warn(f"Multiple PDFs in /source - using the newest: {pdfs[0].name}")
    return pdfs[0]


# --------------------------------------------------------------------------- #
# Content shaping
# --------------------------------------------------------------------------- #

def tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {w[:-1] if w.endswith("s") and len(w) > 3 else w for w in words}


def match_spec_rows(products: list[dict], spec: dict | None) -> None:
    if not spec:
        return
    columns = spec["columns"]
    for product in products:
        best, best_score = None, 0.0
        for row in spec["rows"]:
            row_t, prod_t = tokens(row[0]), tokens(product["name"])
            score = len(row_t & prod_t) / max(len(row_t), 1)
            score = max(score, difflib.SequenceMatcher(
                None, row[0].lower(), product["name"].lower()).ratio())
            if score > best_score:
                best, best_score = row, score
        if best is not None and best_score >= 0.75:
            product["specs"] = [{"label": c, "value": v}
                                for c, v in zip(columns[1:], best[1:]) if v]
        else:
            warn(f"No spec-table row matched product '{product['name']}'")


def find_image(content: dict, ref: str | None) -> str | None:
    """Resolve refs like 'trends/3', 'gallery/2', 'products/designer-louvres/1' or a file path."""
    if not ref or ref == "auto":
        return None
    parts = ref.strip("/").split("/")
    try:
        index = int(parts[-1]) - 1
        if parts[0] == "products":
            node = next(i for s in content["sections"] if s["type"] == "products"
                        for i in s.get("items", []) if i["slug"] == parts[1])
            imgs = node.get("images", [])
        else:
            section = next(s for s in content["sections"] if s["type"] == parts[0])
            if section["type"] == "trends":
                imgs = [im for i in section.get("items", []) for im in i.get("images", [])[:1]]
            else:
                imgs = section.get("images", [])
        return imgs[index]["src"]
    except (StopIteration, ValueError, IndexError, KeyError):
        path = ROOT / ref
        if path.exists():
            return path.resolve().as_uri()
        warn(f"Image reference '{ref}' in config.yaml not found - ignored")
        return None


def all_images(content: dict) -> list[dict]:
    out = []
    for s in content["sections"]:
        out += s.get("images", [])
        for i in s.get("items", []):
            out += i.get("images", [])
    return out


def merge_contact(section: dict | None, cfg_contact: dict) -> list[dict]:
    raw = []
    if section:
        for g in section.get("groups", []):
            raw += g["items"]
    merged: dict[str, str] = {}
    for item in raw:
        if item.get("label"):
            merged[item["label"]] = item["text"].rstrip(".")
    for label, value in (cfg_contact or {}).items():
        merged[label] = "" if value is None else str(value)
    details = []
    for label, value in merged.items():
        if is_placeholder(value):
            warn(f"Contact detail '{label}' is empty or a placeholder - omitted (set it in config.yaml)")
            continue
        details.append({"label": label, "value": value})
    return details


def chunk(items: list, first: int, rest: int) -> list[list]:
    if not items:
        return []
    pages = [items[:first]]
    remaining = items[first:]
    while remaining:
        pages.append(remaining[:rest])
        remaining = remaining[rest:]
    # Avoid a lonely final page with a single image.
    if len(pages) > 1 and len(pages[-1]) == 1 and len(pages[-2]) > 2:
        pages[-1].insert(0, pages[-2].pop())
    return pages


def balanced(items: list, per_page: int) -> list[list]:
    if not items:
        return []
    n_pages = math.ceil(len(items) / per_page)
    size = math.ceil(len(items) / n_pages)
    return [items[i:i + size] for i in range(0, len(items), size)]


def plan_pages(content: dict, cfg: dict) -> list[dict]:
    labels = cfg.get("labels", {})
    sections = content["sections"]
    by_type = {}
    for s in sections:
        by_type.setdefault(s["type"], s)

    products_sec = by_type.get("products")
    products = products_sec.get("items", []) if products_sec else []
    spec_sec = by_type.get("specs")
    match_spec_rows(products, spec_sec.get("table") if spec_sec else None)

    for p in products:
        if not p.get("images"):
            warn(f"Product '{p['name']}' has no images")
        groups = p.get("groups", [])
        p["highlights"] = next((g for g in groups if g["kind"] == "highlights"), None)
        p["applications"] = next((g for g in groups if g["kind"] == "applications"), None)
        p["other_groups"] = [g for g in groups if g["kind"] == "other"]

    pages: list[dict] = [{"kind": "cover"}, {"kind": "intro"}]
    max_side = cfg.get("layout", {}).get("product_page_images", 3)
    for idx, p in enumerate(products):
        imgs = p.get("images", [])
        # A gallery page needs at least 3 photos to look intentional; fewer stay on the product page.
        on_page = len(imgs) if len(imgs) - max_side < 3 else max_side
        on_page = min(on_page, 5)
        pages.append({"kind": "product", "product": p, "images": imgs[:on_page],
                      "flip": idx % 2 == 1})
        for n, group in enumerate(balanced(imgs[on_page:], 9)):
            pages.append({"kind": "gallery", "title": p["name"],
                          "eyebrow": labels.get("product_gallery", "Finishes & Profiles"),
                          "images": group, "continued": n > 0, "product_number": p["number"]})

    rendered_types = {"products"}
    for s in sections:
        t = s["type"]
        if t == "products" or (t in rendered_types and t != "generic"):
            continue
        rendered_types.add(t)
        if t == "specs" and s.get("table"):
            pages.append({"kind": "specs", "section": s})
        elif t == "gallery":
            for n, group in enumerate(chunk(s.get("images", []), 6, 9)):
                pages.append({"kind": "gallery", "title": s["title"], "section": s,
                              "eyebrow": labels.get("projects", "Portfolio"),
                              "intro": s.get("paragraphs", []) if n == 0 else [],
                              "images": group, "continued": n > 0})
        elif t == "trends":
            items = s.get("items", [])
            for n in range(0, max(len(items), 1), 3):
                pages.append({"kind": "trends", "section": s, "items": items[n:n + 3],
                              "continued": n > 0})
        elif t == "contact":
            continue  # rendered as back cover
        else:
            pages.append({"kind": "generic", "section": s})

    pages.append({"kind": "back"})
    for i, page in enumerate(pages, start=1):
        page["number"] = i
    index = [{"number": p["product"]["number"], "name": p["product"]["name"],
              "subtitle": p["product"]["subtitle"], "page": p["number"]}
             for p in pages if p["kind"] == "product"]
    extras = [{"name": pg.get("section", {}).get("title") or pg.get("title"), "page": pg["number"]}
              for pg in pages if pg["kind"] in ("specs", "trends", "gallery", "generic")
              and pg.get("section") and not pg.get("continued")]
    content["index"] = index
    content["index_extras"] = extras
    return pages


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def render_html(content: dict, pages: list[dict], cfg: dict, out_dir: Path) -> Path:
    env = Environment(loader=FileSystemLoader(HERE / "templates"),
                      autoescape=select_autoescape(["html", "j2"]))
    env.filters["pad"] = lambda n: f"{int(n):02d}"

    brand = cfg.get("brand", {})
    cover = cfg.get("cover", {})
    year = str(cfg.get("edition_year") or date.today().year)
    title = content.get("title") or content["source"]["title"]

    cover_title = cover.get("title") or title
    cover_eyebrow = cover.get("eyebrow")
    if not cover.get("title") and re.search(r"\blookbook$", title, re.I):
        cover_title = re.sub(r"\s*lookbook$", "", title, flags=re.I)
        cover_eyebrow = cover_eyebrow or f"Lookbook {year}"
    cover_img = find_image(content, cover.get("image"))
    if not cover_img:
        candidates = [im for im in all_images(content) if im["h"] >= im["w"]]
        candidates = candidates or all_images(content)
        cover_img = max(candidates, key=lambda im: im["w"] * im["h"])["src"] if candidates else None

    contact_sec = next((s for s in content["sections"] if s["type"] == "contact"), None)
    contact = {
        "title": contact_sec["title"] if contact_sec else "Get in Touch",
        "intro": (contact_sec or {}).get("paragraphs", []),
        "details": merge_contact(contact_sec, cfg.get("contact")),
    }

    width, height = PAGE_SIZES[cfg.get("page_size", "letter")]
    fonts = (HERE / "fonts").resolve().as_uri()
    html = env.get_template("brochure.html.j2").render(
        c=content, pages=pages, brand=brand, labels=cfg.get("labels", {}),
        cover={"title": cover_title, "eyebrow": cover_eyebrow or "",
               "tagline": cover.get("tagline", ""), "image": cover_img},
        contact=contact, year=year,
        back_image=find_image(content, (cfg.get("back_cover") or {}).get("image")), width=width, height=height, fonts=fonts,
        css=(HERE / "templates" / "brochure.css").read_text(encoding="utf-8"),
    )
    path = out_dir / "brochure.html"
    path.write_text(html, encoding="utf-8")
    return path


def render_pdf(html_path: Path, pdf_path: Path) -> list[int]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until="networkidle")
        page.wait_for_function("window.__fitDone === true", timeout=30000)
        overflow = page.evaluate("window.__overflowPages || []")
        page.pdf(path=str(pdf_path), prefer_css_page_size=True, print_background=True)
        browser.close()
    return overflow


def write_previews(pdf_path: Path, out_dir: Path) -> None:
    import pymupdf
    prev = out_dir / "preview"
    shutil.rmtree(prev, ignore_errors=True)
    prev.mkdir()
    doc = pymupdf.open(pdf_path)
    for i, page in enumerate(doc, start=1):
        page.get_pixmap(dpi=70).save(prev / f"page-{i:02d}.png")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="raw PDF (defaults to newest PDF in /source)")
    ap.add_argument("--preview", action="store_true", help="also write page PNGs to output/preview")
    args = ap.parse_args()

    cfg = load_config()
    src = resolve_source(args.source, cfg)
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print(f"Reading   {src.name}")
    content = extract(src, out_dir)
    pages = plan_pages(content, cfg)
    (out_dir / "content.json").write_text(json.dumps(content, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    html_path = render_html(content, pages, cfg, out_dir)

    pdf_path = out_dir / f"{cfg.get('output_name', 'Brochure')}.pdf"
    overflow = render_pdf(html_path, pdf_path)
    for n in overflow:
        warn(f"Page {n} content was too long to fit even after shrinking - review it")
    if args.preview:
        write_previews(pdf_path, out_dir)

    products = next((s.get("items", []) for s in content["sections"] if s["type"] == "products"), [])
    print(f"Products  {len(products)}: " + ", ".join(p["name"] for p in products))
    print(f"Sections  " + ", ".join(f"{s['title']} [{s['type']}]" for s in content["sections"]))
    print(f"Pages     {len(pages)}")
    print(f"Wrote     {pdf_path.relative_to(ROOT)}")
    if warnings:
        print("\nReview:")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
