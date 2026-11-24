#!/usr/bin/env python3
"""Extract a .docx paper or proposal into a draft document.json plus figure images.

Usage:  python extract_docx.py INPUT.docx WORK_DIR

Writes  WORK_DIR/document.json      ordered headings, paragraphs and figure positions
        WORK_DIR/figures/figN.jpg   one image per figure, cropped as Word shows it
        WORK_DIR/figures/extra_K.jpg  images that no legend claimed
        WORK_DIR/contact_sheet.png  all figures at a glance

The result is a draft. Read the printed report, look at the contact sheet, and correct
document.json by hand where a heading level, a legend or an image assignment is wrong.
"""
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figmap_common import CAPTION, caption_title, contact_sheet, plain, report, save_figure, tidy_runs, write_document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
SKIP = {W + "del", W + "moveFrom", W + "instrText", W + "delText", W + "pPr", W + "rPr"}


def on(rpr, name):
    node = rpr.find(W + name) if rpr is not None else None
    return node is not None and node.get(W + "val") not in ("0", "false")


def read_paragraph(p, rels):
    """Return {"style", "list", "runs", "images", "boxes"} for one w:p.

    Word stores a text box twice (mc:Choice and mc:Fallback); only one copy is read.
    Paragraphs inside a text box are returned in "boxes", not mixed into the host paragraph.
    """
    style = p.find(W + "pPr/" + W + "pStyle")
    para = {"style": style.get(W + "val") if style is not None else "",
            "list": p.find(W + "pPr/" + W + "numPr") is not None, "runs": [], "images": [], "boxes": []}

    def walk(node, fmt):
        for child in node:
            tag = child.tag
            if tag in SKIP:
                continue
            if tag == MC + "AlternateContent":
                branch = child.find(MC + "Choice")
                walk(branch if branch is not None else child.find(MC + "Fallback"), fmt)
            elif tag == W + "txbxContent":
                for inner in child.iter(W + "p"):
                    box = read_paragraph(inner, rels)
                    para["images"] += box["images"]
                    para["boxes"].append(box)
            elif tag == W + "r":
                rpr = child.find(W + "rPr")
                colour = rpr.find(W + "color") if rpr is not None else None
                vert = rpr.find(W + "vertAlign") if rpr is not None else None
                walk(child, {"b": on(rpr, "b"), "i": on(rpr, "i"),
                             "sup": vert is not None and vert.get(W + "val") == "superscript",
                             "colour": colour.get(W + "val") if colour is not None else None})
            elif tag == W + "t":
                para["runs"].append({"text": child.text or "", **fmt})
            elif tag in (W + "br", W + "cr"):
                para["runs"].append({"text": "\n", **fmt})
            elif tag == W + "tab":
                para["runs"].append({"text": " ", **fmt})
            elif tag == W + "noBreakHyphen":
                para["runs"].append({"text": "-", **fmt})
            elif tag == PIC + "blipFill":
                blip, crop = child.find(A + "blip"), child.find(A + "srcRect")
                if blip is not None and rels.get(blip.get(R + "embed")):
                    para["images"].append({"target": rels[blip.get(R + "embed")],
                                           "crop": {k: int(v) / 100000 for k, v in crop.attrib.items()} if crop is not None else {}})
            elif tag == V + "imagedata":
                if rels.get(child.get(R + "id")):
                    crop = {k[4]: int(child.get(k).rstrip("f")) / 65536 for k in ("croptop", "cropbottom", "cropleft", "cropright")
                            if child.get(k, "").rstrip("f").lstrip("-").isdigit()}
                    para["images"].append({"target": rels[child.get(R + "id")], "crop": crop})
            else:
                walk(child, fmt)

    walk(p, {"b": False, "i": False, "sup": False, "colour": None})
    return para


def load_image(archive, target, warnings):
    """Open an embedded picture as a PIL image. EMF/WMF only work when they carry a PDF copy (Word for Mac)."""
    from PIL import Image
    data = archive.read("word/" + target.lstrip("/").replace("word/", "", 1))
    if target.lower().endswith((".emf", ".wmf")):
        start, end = data.find(b"%PDF-"), data.rfind(b"%%EOF")
        if start < 0 or end < start:
            warnings.append("%s is an EMF/WMF picture without an embedded PDF and could not be converted" % target)
            return None
        try:
            import fitz
        except ImportError:
            warnings.append("%s needs PyMuPDF to be converted (pip install pymupdf)" % target)
            return None
        page = fitz.open(stream=data[start:end + 5], filetype="pdf")[0]
        zoom = 2600 / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.open(io.BytesIO(pix.tobytes("png")))
    try:
        return Image.open(io.BytesIO(data))
    except Exception as error:                       # unknown picture format
        warnings.append("%s could not be opened (%s)" % (target, error))
        return None


def cropped(image, crop):
    """Apply Word's crop (fractions of width and height; negative values mean padding and are ignored)."""
    w, h = image.size
    cut = {k: max(0.0, crop.get(k, 0.0)) for k in "ltrb"}
    return image.crop((round(cut["l"] * w), round(cut["t"] * h), round(w - cut["r"] * w), round(h - cut["b"] * h)))


def heading_level(para, text):
    """0 for body text, otherwise 1-3. Uses the paragraph style first, then how the whole line is formatted."""
    style = para["style"] or ""
    m = re.match(r"(?i)heading\s*(\d)", style)
    if m:
        return min(3, int(m.group(1)))
    if para["list"] or len(text) > 140 or text.rstrip().endswith((".", ";", ",")) or text.startswith(("“", '"')):
        return 0
    runs = [r for r in para["runs"] if r["text"].strip() and not r["sup"]]
    if not runs:
        return 0
    bold = all(r["b"] for r in runs)
    coloured = all(r["colour"] not in (None, "auto", "000000") for r in runs)
    caps = text.upper() == text and any(c.isalpha() for c in text)
    if bold and coloured or (caps and (bold or coloured) and len(text) < 60 and coloured):
        return 1
    if coloured or (caps and len(text) < 60 and not bold):
        return 2
    if bold:
        return 3
    return 0


def split_leadins(runs):
    """Split one long paragraph at bold-italic lead-ins ("Biopsy procedure. ...") into separate items."""
    starts = [k for k, r in enumerate(runs) if r["b"] and r["i"] and len(r["text"].strip()) > 3]
    if len(starts) < 4 or len(plain(runs)) < 900 or starts[0] > 1:
        return None
    return [runs[a:b] for a, b in zip(starts, starts[1:] + [len(runs)])]


def split_references(runs):
    """Split "1. Author ... 2. Author ..." kept in one paragraph into one entry per reference."""
    chars = [(c, r) for r in runs for c in r["text"]]
    text = "".join(c for c, _ in chars)
    cuts, pos, n = [], 0, 1
    while True:
        m = re.compile(r"(?:(?<=[\s.)])|^)%d\s?\.\s*" % n).search(text, pos)
        if not m:
            break
        cuts.append((m.start(), m.end()))
        pos, n = m.end(), n + 1
    if len(cuts) < 3:
        return None
    entries = []
    for k, (start, end) in enumerate(cuts):
        stop = cuts[k + 1][0] if k + 1 < len(cuts) else len(chars)
        entries.append([{"text": c, "b": r["b"], "i": r["i"], "sup": r["sup"]} for c, r in chars[end:stop]])
    return entries


def main(source, work_dir):
    work = Path(work_dir)
    (work / "figures").mkdir(parents=True, exist_ok=True)
    warnings = []
    archive = zipfile.ZipFile(source)
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(archive.read("word/_rels/document.xml.rels"))}
    body = ET.fromstring(archive.read("word/document.xml")).find(W + "body")

    # 1. paragraphs and pictures in reading order
    events = []                                           # ("para", record) or ("img", record), each with its body index
    seen_inner = set()
    for index, node in enumerate(body):
        paragraphs = [node] if node.tag == W + "p" else [p for p in node.iter(W + "p")]
        for p in paragraphs:
            if id(p) in seen_inner:
                continue
            para = read_paragraph(p, rels)
            for inner in p.iter(W + "txbxContent"):
                seen_inner.update(id(q) for q in inner.iter(W + "p"))
            used = set()
            for image in para["images"]:
                if image["target"] not in used:           # the same picture can be listed by a group and its fallback
                    used.add(image["target"])
                    events.append(("img", {**image, "at": index}))
            for box in para["boxes"]:
                events.append(("para", {**box, "at": index, "box": True}))
            events.append(("para", {**para, "at": index, "box": False}))

    # 2. open the pictures; small ones (logos, bullets) are ignored
    pictures = []
    for k, (kind, record) in enumerate(events):
        if kind != "img":
            continue
        image = load_image(archive, record["target"], warnings)
        if image is None:
            continue
        image = cropped(image, record["crop"])
        if image.width < 150 or image.height < 150:
            continue
        pictures.append({"event": k, "at": record["at"], "image": image, "figure": None})

    # 3. legends: the first paragraph that opens with "Figure N." for each N
    captions = {}
    for k, (kind, record) in enumerate(events):
        if kind != "para":
            continue
        m = CAPTION.match(plain(record["runs"]))
        if m and m.group(2) not in captions:
            captions[m.group(2)] = k
            record["caption"] = m.group(2)

    # 4. give each legend a picture: one anchored in the same paragraph first, then the nearest free one
    for n, k in captions.items():
        same = [p for p in pictures if p["figure"] is None and p["at"] == events[k][1]["at"]]
        if same:
            same[0]["figure"] = n
    for n, k in captions.items():
        if any(p["figure"] == n for p in pictures):
            continue
        free = [p for p in pictures if p["figure"] is None]
        if free:
            nearest = min(free, key=lambda p: (abs(p["event"] - k), p["event"] > k))
            if abs(nearest["event"] - k) <= 6:
                nearest["figure"] = n

    figures = {}
    for n, k in captions.items():
        runs = tidy_runs(events[k][1]["runs"])
        figures[n] = {"title": caption_title(runs), "caption": runs, "image": None}
    extra = 0
    for p in pictures:
        if p["figure"]:
            name = "figures/fig%s.jpg" % p["figure"]
            figures[p["figure"]]["w"], figures[p["figure"]]["h"] = save_figure(p["image"], work / name)
            figures[p["figure"]]["image"] = name
        else:
            extra += 1
            save_figure(p["image"], work / ("figures/extra_%d.jpg" % extra))
            warnings.append("figures/extra_%d.jpg belongs to no legend; assign it in document.json if it is a figure" % extra)
    for n, f in figures.items():
        if not f["image"]:
            warnings.append("Figure %s has a legend but no picture in the file" % n)

    # 5. the text, in order
    doc = {"title": "", "subtitle": "", "source": Path(source).name, "items": [], "figures": figures}
    items, counter, in_refs = doc["items"], [0], False

    def add(kind, **fields):
        counter[0] += 1
        items.append({"type": kind, "id": "b%d" % counter[0], **fields})

    for kind, record in events:
        if kind != "para":
            continue
        if record.get("caption"):
            add("fig", n=int(record["caption"]))
            continue
        text = re.sub(r"\s+", " ", plain(record["runs"])).strip()
        if not text:
            continue
        runs = tidy_runs(record["runs"])
        if not items and not doc["title"] and len(text) < 250:
            doc["title"] = text
            continue
        if not items and doc["title"] and not doc["subtitle"] and len(text) < 200 and heading_level(record, text) == 0 \
                and all(r["i"] for r in runs if r["text"].strip(" -–")):
            doc["subtitle"] = text.lstrip("-– ").strip()
            continue
        level = heading_level(record, text)
        if level:
            in_refs = bool(re.match(r"(?i)^(references|bibliography|literature cited)\b", text))
            add("h%d" % level, text=text)
        elif in_refs:
            for entry in split_references(record["runs"]) or [runs]:
                add("ref", runs=tidy_runs(entry))
        elif record["list"]:
            add("li", runs=runs)
        elif text[0] in "“\"" and text.rstrip()[-1] in "”\"" and len(text) < 600:
            add("quote", runs=runs)
        else:
            parts = split_leadins(record["runs"])
            if parts:
                for part in parts:
                    add("li", runs=tidy_runs(part))
            else:
                add("p", runs=runs)

    write_document(doc, work)
    contact_sheet(figures, work)
    report(doc, work, warnings)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
