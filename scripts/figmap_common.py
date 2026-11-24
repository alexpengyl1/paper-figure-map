"""Helpers shared by extract_docx.py, extract_pdf.py and build_viewer.py."""
import json
import re
from pathlib import Path

# "Figure 3.", "Fig. 3 |", "FIG. 3:" at the start of a paragraph marks a legend.
CAPTION = re.compile(r"^\s*(Figure|Fig\.?|FIGURE|FIG\.?)\s*(\d{1,2})\s*([.:|])\s*")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")


def plain(runs, sup=True):
    """Text of a list of runs, without superscripts when sup is False."""
    return "".join(r["text"] for r in runs if sup or not r.get("sup")).replace("\n", " ")


def tidy_runs(runs):
    """Merge neighbouring runs that share their formatting, and drop empty ones."""
    out = []
    for r in runs:
        text = r["text"].replace("\n", " ").replace("\t", " ").replace("\u00a0", " ")
        if not text:
            continue
        fmt = {k: bool(r.get(k)) for k in ("b", "i", "sup")}
        if out and all(out[-1][k] == fmt[k] for k in fmt):
            out[-1]["text"] += text
        else:
            out.append({"text": text, **fmt})
    return out


def caption_title(runs):
    """Short title of a legend: its bold opening if it has one, otherwise its first sentence."""
    runs = [r for r in runs if not r.get("sup")]
    text = plain(runs)
    label = CAPTION.match(text)
    start = label.end() if label else 0
    bold, pos = "", 0
    for r in runs:
        end = pos + len(r["text"])
        if end > start:
            piece = r["text"][max(0, start - pos):]
            if r.get("b") or not piece.strip():
                bold += piece
            else:
                break
        pos = end
    bold = re.sub(r"\s+", " ", bold).strip(" .|:")
    bold = re.sub(r"[.\s]+\(?[Aa]\)?$", "", bold)          # a panel letter that shares the bold opening
    if 3 <= len(bold) <= 160:
        return bold
    rest = text[start:].strip()
    first = SENTENCE_END.split(rest)[0] if rest else ""
    first = re.split(r"\s\|\s", first)[0].strip(" .")
    return first[:160]


def save_figure(image, dest, max_width=2000):
    """Flatten a PIL image on white, limit its width and save it as JPEG. Returns (width, height)."""
    from PIL import Image
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        ground = Image.new("RGBA", image.size, "white")
        ground.alpha_composite(image)
        image = ground
    image = image.convert("RGB")
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)), Image.LANCZOS)
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "JPEG", quality=88, subsampling=0, optimize=True)
    return image.size


def contact_sheet(figures, work_dir, name="contact_sheet.png"):
    """One image with every extracted figure and its number, for a quick visual check."""
    from PIL import Image, ImageDraw
    tiles = []
    for n in sorted(figures, key=int):
        info = figures[n]
        tile = Image.new("RGB", (620, 460), "white")
        draw = ImageDraw.Draw(tile)
        draw.rectangle([0, 0, 619, 459], outline="#888888")
        draw.text((10, 8), "Figure %s  %s" % (n, (info.get("title") or "")[:70]), fill="black")
        if info.get("image"):
            im = Image.open(Path(work_dir) / info["image"])
            im.thumbnail((600, 420))
            tile.paste(im, (10 + (600 - im.width) // 2, 32))
        else:
            draw.text((10, 200), "NO IMAGE FOUND", fill="red")
        tiles.append(tile)
    if not tiles:
        return None
    cols = 2 if len(tiles) > 1 else 1
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 620, rows * 460), "#DDDDDD")
    for k, tile in enumerate(tiles):
        sheet.paste(tile, ((k % cols) * 620, (k // cols) * 460))
    path = Path(work_dir) / name
    sheet.save(path)
    return path


def write_document(doc, work_dir):
    path = Path(work_dir) / "document.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    return path


def report(doc, work_dir, warnings):
    """Print what was found, so the draft can be checked before the page is built."""
    items = doc["items"]
    print("\nTitle:    ", doc.get("title") or "(none found)")
    print("Subtitle: ", doc.get("subtitle") or "(none)")
    print("Items:    ", ", ".join("%d %s" % (sum(1 for i in items if i["type"] == t), t)
                                  for t in ("h1", "h2", "h3", "p", "li", "quote", "ref", "fig")
                                  if any(i["type"] == t for i in items)))
    print("\nHeadings (check the levels):")
    for i in items:
        if i["type"] in ("h1", "h2", "h3"):
            print("  %s%s  [%s] %s" % ("    " * (int(i["type"][1]) - 1), i["type"], i["id"], i["text"][:90]))
    print("\nFigures (check each crop on contact_sheet.png):")
    for n in sorted(doc["figures"], key=int):
        f = doc["figures"][n]
        where = " page %s" % f["page"] if f.get("page") else ""
        print("  Figure %s%s | image: %s | %s" % (n, where, f.get("image") or "NONE", (f.get("title") or "")[:70]))
    for w in warnings:
        print("WARNING:", w)
    print("\nWrote", Path(work_dir) / "document.json")
