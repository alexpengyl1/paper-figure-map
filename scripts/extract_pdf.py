#!/usr/bin/env python3
"""Extract a PDF paper into a draft document.json plus figure images.

Usage:  python extract_pdf.py INPUT.pdf WORK_DIR [--boxes boxes.json] [--pages 3,4]

Writes  WORK_DIR/document.json      ordered headings, paragraphs and figure positions
        WORK_DIR/figures/figN.jpg   the region of the page that holds each figure
        WORK_DIR/contact_sheet.png  all figures at a glance
        WORK_DIR/pages/page_K.png   only for the pages named with --pages (to pick a crop box by eye)

A PDF has no notion of "figure", so the crops are a guess: the pictures and line art that sit
above (or below) each legend. Look at contact_sheet.png. Where a crop is wrong, render that page
with --pages, read the box off the image, and pass it back:

    boxes.json   {"3": {"page": 5, "bbox": [36, 60, 560, 410]}}

page is 1-based; bbox is x0, y0, x1, y1 in PDF points (the page image is drawn at 2 px per point).
"""
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figmap_common import CAPTION, caption_title, contact_sheet, plain, report, save_figure, tidy_runs, write_document

try:
    import fitz
except ImportError:
    sys.exit("extract_pdf.py needs PyMuPDF:  pip install pymupdf")

PAGE_ZOOM = 2            # pixels per point in pages/page_K.png
HYPHEN = re.compile(r"[a-z][-\u2010\u00ad]$")


def block_runs(block):
    """Runs of one text block; lines are joined and end-of-line hyphenation is undone."""
    runs = []
    for line in block["lines"]:
        spans = [s for s in line["spans"] if s["text"]]
        if not spans:
            continue
        if runs:
            last = runs[-1]
            if HYPHEN.search(last["text"]) and spans[0]["text"][:1].islower():
                last["text"] = last["text"][:-1]
            elif not last["text"].endswith(" "):
                last["text"] += " "
        for s in spans:
            runs.append({"text": s["text"], "b": bool(s["flags"] & 16) or "Bold" in s["font"],
                         "i": bool(s["flags"] & 2) or "Italic" in s["font"] or "Oblique" in s["font"],
                         "sup": bool(s["flags"] & 1), "size": s["size"]})
    return runs


def join_fragments(blocks):
    """A few words at the start of a line (often a bold lead-in) can be returned as a block of their own.
    Put such a fragment back in front of the block whose first line it shares."""
    kept = []
    for a in blocks:
        host = None
        if len(a["lines"]) == 1:
            ax0, ay0, ax1, ay1 = a["bbox"]
            for b in blocks:
                if b is a or not b["lines"]:
                    continue
                bx0, by0, bx1, by1 = b["lines"][0]["bbox"]
                overlap = min(ay1, by1) - max(ay0, by0)
                if overlap > 0.6 * (ay1 - ay0) and -2 <= bx0 - ax1 < 20:
                    host = b
                    break
        if host is None:
            kept.append(a)
        else:
            host["lines"] = a["lines"] + host["lines"]
            host["bbox"] = (min(a["bbox"][0], host["bbox"][0]), min(a["bbox"][1], host["bbox"][1]),
                            max(a["bbox"][2], host["bbox"][2]), max(a["bbox"][3], host["bbox"][3]))
    return kept


def reading_order(blocks, page_width):
    """Sort text blocks top to bottom, left column before right column between full-width blocks."""
    wide = lambda b: (b["bbox"][2] - b["bbox"][0]) > 0.6 * page_width
    narrow = [b for b in blocks if not wide(b)]
    left = [b for b in narrow if (b["bbox"][0] + b["bbox"][2]) / 2 < page_width / 2]
    two_columns = len(left) >= 2 and len(narrow) - len(left) >= 2
    if not two_columns:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
    ordered, band = [], []

    def flush():
        band.sort(key=lambda b: ((b["bbox"][0] + b["bbox"][2]) / 2 >= page_width / 2, b["bbox"][1]))
        ordered.extend(band)
        band.clear()

    for b in sorted(blocks, key=lambda b: b["bbox"][1]):
        if wide(b):
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def graphics_on(page):
    """Rectangles of the pictures and line art on a page (page-sized backgrounds and hairlines left out)."""
    rects = [fitz.Rect(info["bbox"]) for info in page.get_image_info()]
    rects += [fitz.Rect(d["rect"]) for d in page.get_drawings()]
    area = page.rect.width * page.rect.height
    keep = []
    for r in rects:
        r = r & page.rect
        if r.is_empty or r.width * r.height > 0.85 * area:
            continue
        if (r.width < 3 and r.height < 3) or (r.height < 1.5 and r.width > 0.5 * page.rect.width):
            continue
        keep.append(r)
    return keep


def figure_region(page, caption, graphics):
    """Union of the graphics stacked directly above the legend (or, failing that, below it)."""
    cap = fitz.Rect(caption)
    full = cap.width > 0.55 * page.rect.width
    x0, x1 = (0, page.rect.width) if full else (cap.x0 - 12, cap.x1 + 12)
    beside = [r for r in graphics if r.x1 > x0 and r.x0 < x1]

    def grow(candidates, edge, above):
        region = None
        for r in sorted(candidates, key=lambda r: -r.y1 if above else r.y0):
            gap = (edge - r.y1) if above else (r.y0 - edge)
            if gap > 36:
                break
            region = fitz.Rect(r) if region is None else region | r
            edge = min(edge, r.y0) if above else max(edge, r.y1)
        return region

    region = grow([r for r in beside if r.y1 <= cap.y0 + 4], cap.y0, True)
    if region is None or region.height < 30:
        region = grow([r for r in beside if r.y0 >= cap.y1 - 4], cap.y1, False)
    if region is None or region.height < 30:
        return None
    return (region + (-4, -4, 4, 4)) & page.rect


def render(page, bbox, width_px=2000):
    from PIL import Image
    clip = fitz.Rect(bbox)
    zoom = min(6, width_px / clip.width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    source, work = argv[0], Path(argv[1])
    boxes = json.loads(Path(argv[argv.index("--boxes") + 1]).read_text()) if "--boxes" in argv else {}
    show_pages = [int(k) for k in argv[argv.index("--pages") + 1].split(",")] if "--pages" in argv else []
    (work / "figures").mkdir(parents=True, exist_ok=True)
    pdf = fitz.open(source)
    warnings = []

    for k in show_pages:
        (work / "pages").mkdir(exist_ok=True)
        pdf[k - 1].get_pixmap(matrix=fitz.Matrix(PAGE_ZOOM, PAGE_ZOOM), alpha=False).save(work / "pages" / ("page_%d.png" % k))
        print("wrote pages/page_%d.png  (%d px per point; page is %.0f x %.0f points)"
              % (k, PAGE_ZOOM, pdf[k - 1].rect.width, pdf[k - 1].rect.height))

    # 1. text blocks of every page, with running headers, footers and page numbers removed
    pages, edge_text, sizes = [], Counter(), Counter()
    for page in pdf:
        blocks = join_fragments([b for b in page.get_text("dict")["blocks"] if b["type"] == 0])
        for b in blocks:
            b["runs"] = block_runs(b)
            b["text"] = re.sub(r"\s+", " ", plain(b["runs"])).strip()
            b["edge"] = b["bbox"][3] < 0.08 * page.rect.height or b["bbox"][1] > 0.92 * page.rect.height
            if b["edge"]:
                edge_text[re.sub(r"\d+", "#", b["text"])] += 1
            for r in b["runs"]:
                sizes[round(r["size"] * 2) / 2] += len(r["text"])
        pages.append([b for b in blocks if b["text"]])
    body_size = sizes.most_common(1)[0][0] if sizes else 10
    repeated = {t for t, c in edge_text.items() if c >= max(2, len(pdf) // 3)}
    for k, blocks in enumerate(pages):
        pages[k] = [b for b in blocks if not (b["edge"] and (re.sub(r"\d+", "#", b["text"]) in repeated
                                                            or re.fullmatch(r"[\divxlc\s|/-]{1,12}", b["text"])))]

    # 2. legends and the region each figure occupies
    figures, taken, blocks_of = {}, {}, {}                # taken: page index -> list of figure rectangles
    for k, blocks in enumerate(pages):
        graphics = None
        for b in blocks:
            m = CAPTION.match(b["text"])
            if not m or m.group(2) in figures:
                continue
            n = m.group(2)
            b["caption"] = n
            runs = tidy_runs(b["runs"])
            figures[n] = {"title": caption_title(runs), "caption": runs, "image": None, "page": k + 1}
            blocks_of[n] = b["runs"]
            if n in boxes:
                continue
            graphics = graphics_on(pdf[k]) if graphics is None else graphics
            region = figure_region(pdf[k], b["bbox"], graphics)
            if region is None:
                warnings.append("Figure %s (page %d): no picture found next to its legend; give a box with --boxes" % (n, k + 1))
                continue
            figures[n]["bbox"] = [round(v, 1) for v in region]
            taken.setdefault(k, []).append(region)
    for n, box in boxes.items():
        if n not in figures:
            figures[n] = {"title": "", "caption": [{"text": "Figure %s." % n, "b": True, "i": False, "sup": False}], "image": None}
            warnings.append("Figure %s has a box but no legend was found; add its legend and a fig item to document.json" % n)
        figures[n]["page"], figures[n]["bbox"] = box["page"], box["bbox"]
        taken.setdefault(box["page"] - 1, []).append(fitz.Rect(box["bbox"]))
    for n, f in figures.items():
        if f.get("bbox"):
            name = "figures/fig%s.jpg" % n
            f["w"], f["h"] = save_figure(render(pdf[f["page"] - 1], f["bbox"]), work / name)
            f["image"] = name

    # 3. the text in reading order; words printed inside a figure are not body text
    doc = {"title": "", "subtitle": "", "source": Path(source).name, "items": [], "figures": figures}
    items, counter, in_refs = doc["items"], [0], False
    last_caption, last_place = None, None                 # for legends and paragraphs that run on into the next column
    title_size = max((r["size"] for b in pages[0] for r in b["runs"]), default=body_size) if pages else body_size

    def add(kind, **fields):
        counter[0] += 1
        items.append({"type": kind, "id": "b%d" % counter[0], **fields})

    for k, blocks in enumerate(pages):
        for b in reading_order(blocks, pdf[k].rect.width):
            if b.get("caption"):
                add("fig", n=int(b["caption"]))
                last_caption = b["caption"]
                continue
            rect = fitz.Rect(b["bbox"])
            if any((rect & region).get_area() > 0.6 * rect.get_area() for region in taken.get(k, [])):
                continue
            text, runs = b["text"], tidy_runs(b["runs"])
            place = (k, (rect.x0 + rect.x1) / 2 >= pdf[k].rect.width / 2)
            moved, last_place = place != last_place, place
            if last_caption and items[-1]["type"] == "fig":
                legend = figures[last_caption]["caption"]
                if moved and not plain(legend, sup=False).rstrip().endswith((".", "?", "!")) and \
                        abs(b["runs"][0]["size"] - max(r.get("size", 0) for r in blocks_of[last_caption])) < 0.6:
                    figures[last_caption]["caption"] = tidy_runs(legend + [{"text": " "}] + runs)   # legend continues here
                    continue
            last_caption = None
            size = max(r["size"] for r in b["runs"])
            words = [r for r in b["runs"] if r["text"].strip() and not r["sup"]]
            if k == 0 and not doc["title"] and size >= title_size - 0.5 and size > body_size + 2 and len(text) < 300:
                doc["title"] = text
                continue
            short = len(text) < 140 and len(b["lines"]) <= 3 and not text.endswith((".", ",", ";"))
            numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z]", text)
            if short and (size > body_size + 0.7 or all(r["b"] for r in words) or (numbered and len(text) < 80)):
                in_refs = bool(re.match(r"(?i)^(\d+\.?\s*)?(references|bibliography|literature cited)\b", text))
                add("h1", text=text)                      # the level is set below, once every heading is known
                items[-1]["_rank"] = (round(size * 2) / 2, not all(r["i"] for r in words))
                items[-1]["_numbered"] = min(3, numbered.group(1).count(".") + 1) if numbered else 0
                continue
            if in_refs:
                add("ref", runs=[{**r, "text": re.sub(r"^\s*\[?\d{1,3}[\].]?\s+", "", r["text"]) if j == 0 else r["text"]}
                                 for j, r in enumerate(runs)])
                continue
            previous = next((i for i in reversed(items) if i["type"] != "fig"), None)   # a figure may sit inside a paragraph
            open_end = previous and previous["type"] == "p" and \
                not plain(previous["runs"], sup=False).rstrip().endswith((".", "?", "!", ":", ";", ")", "”", '"'))
            if open_end:
                joined = previous["runs"] + [{"text": " ", "b": False, "i": False, "sup": False}] + runs
                if HYPHEN.search(plain(previous["runs"])):
                    previous["runs"][-1]["text"] = previous["runs"][-1]["text"].rstrip()[:-1]
                    joined = previous["runs"] + runs
                previous["runs"] = tidy_runs(joined)      # a paragraph that continues in the next column or page
                continue
            add("p", runs=runs)

    # two or three bold words followed by text that starts in lower case are a lead-in, not a heading
    for k in range(len(items) - 2, -1, -1):
        head, after = items[k], items[k + 1]
        if "_rank" in head and after["type"] == "p" and len(head["text"].split()) <= 3 and plain(after["runs"])[:1].islower():
            after["runs"] = tidy_runs([{"text": head["text"] + " ", "b": True}] + after["runs"])
            del items[k]

    # heading levels: by number ("2.1") where headings are numbered, otherwise by size (larger first), upright before italic
    ranks = sorted({i["_rank"] for i in items if "_rank" in i}, reverse=True)
    for i in items:
        if "_rank" in i:
            i["type"] = "h%d" % (i.pop("_numbered") or min(3, ranks.index(i["_rank"]) + 1))
            del i["_rank"]

    write_document(doc, work)
    contact_sheet(figures, work)
    report(doc, work, warnings)


if __name__ == "__main__":
    main(sys.argv[1:])
