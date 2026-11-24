#!/usr/bin/env python3
"""Build the interactive figure map from document.json (and rail.json, if there is one).

Usage:  python build_viewer.py WORK_DIR OUT_DIR [--rail rail.json] [--standalone | --single-file]

Reads   WORK_DIR/document.json, WORK_DIR/figures/, WORK_DIR/rail.json (or the file given with --rail)
Writes  OUT_DIR/index.html and OUT_DIR/figures/

index.html is a page fragment (no <html> or <body>), which is what the Artifact tool publishes.
With --standalone it is a complete HTML document that opens straight from disk in a browser.
With --single-file the figures are embedded as well, so the one file can be copied or sent on its own.
Without a rail.json the left panel lists the top-level sections of the document.
"""
import base64
import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from figmap_common import CAPTION, SENTENCE_END, plain

esc = html.escape
LETTERS = r"(?:[A-Za-z](?![A-Za-z]))(?:\s?[-–,]\s?[A-Za-z](?![A-Za-z]))*"
CITE = re.compile(r"(?<![A-Za-z])(Figures?|Figs?\.?|FIGURES?|FIGS?\.?)\s*(\d{1,2})(%s)?" % LETTERS)
MORE = re.compile(r"(\s*(?:,|and|&|[-–]|to)\s*)(\d{1,2})(%s)?(?![\d.]*\d)" % LETTERS)
SUPPLEMENT = re.compile(r"(Supplementary|Supplemental|Suppl\.?|Extended Data|Appendix)\s*$")


def main(argv):
    if len(argv) < 2:
        sys.exit(__doc__)
    work, out = Path(argv[0]), Path(argv[1])
    single = "--single-file" in argv

    def img_tag(n, extra=""):
        """<img> for figure n: a file path, or (single file) a marker that the page fills from its embedded copy."""
        if not figs[n].get("image"):
            return ""
        source = 'data-embedded="%s"' % n if single else 'src="%s"' % esc(figs[n]["image"])
        return '<img %s alt=""%s>' % (source, extra)
    doc = json.loads((work / "document.json").read_text())
    rail_path = Path(argv[argv.index("--rail") + 1]) if "--rail" in argv else work / "rail.json"
    rail = json.loads(rail_path.read_text()) if rail_path.exists() else None
    figs = {str(n): f for n, f in doc["figures"].items()}
    order = sorted(figs, key=int)
    cites = {n: [] for n in figs}
    section = ["", "", ""]
    placement, para_runs, body = {}, {}, []

    # ------------------------------------------------------------ the text
    def cite_link(n, shown, pid, label):
        cid = "cite-%s-%d" % (n, len(cites[n]) + 1)
        cites[n].append({"id": cid, "label": re.sub(r"\s+", " ", label), "pid": pid,
                         "section": " › ".join(s for s in section if s)})
        return '<a class="figref" id="%s" href="#fig-%s" data-fig="%s">%s</a>' % (cid, n, n, esc(shown))

    def link_citations(text, pid):
        out_html, pos = "", 0
        for m in CITE.finditer(text):
            if m.start() < pos or m.group(2) not in figs or SUPPLEMENT.search(text[:m.start()]):
                continue
            refs, end = [(m.start(), m.end(), m.group(2))], m.end()
            while True:                                   # "Figure 7 and 8", "Figs 2, 3 and 5"
                more = MORE.match(text, end)
                if not more or more.group(2) not in figs:
                    break
                refs.append((more.start(2), more.end(), more.group(2)))
                end = more.end()
            label = text[m.start():end]
            for a, b, n in refs:
                out_html += esc(text[pos:a]) + cite_link(n, text[a:b], pid, label)
                pos = b
        return out_html + esc(text[pos:])

    def runs_html(runs, pid):
        out_html = ""
        for r in runs:
            text = r["text"]
            if r.get("sup"):
                out_html += "<sup>%s</sup>" % esc(text.strip()) if text.strip() else " "
                continue
            piece = link_citations(text, pid)
            if r.get("b"):
                piece = "<strong>%s</strong>" % piece
            if r.get("i"):
                piece = "<em>%s</em>" % piece
            out_html += piece
        return re.sub(r"\s+", " ", out_html).strip()

    def nice(text):
        return text.capitalize() if text.upper() == text else text

    open_list = [None]

    def close_list():
        if open_list[0]:
            body.append("</%s>" % open_list[0])
            open_list[0] = None

    for item in doc["items"]:
        kind, pid = item["type"], item["id"]
        if kind not in ("li", "ref"):
            close_list()
        if kind in ("h1", "h2", "h3"):
            level = int(kind[1])
            section[level - 1:] = [nice(item["text"])] + [""] * (3 - level)
            body.append('<h%d id="%s">%s</h%d>' % (level + 1, pid, esc(item["text"]), level + 1))
        elif kind == "fig":
            n = str(item["n"])
            if n not in figs:
                continue
            placement[n] = {"path": " › ".join(s for s in section if s), "top": section[0]}
            picture = img_tag(n, ' loading="lazy"')
            body.append('<a class="figcard" id="figcard-%s" href="#fig-%s" data-fig="%s">%s<span class="figcard-text">'
                        '<span class="figcard-no">Figure %s</span><span class="figcard-title">%s</span></span>'
                        '<span class="figcard-go">View</span></a>' % (n, n, n, picture, n, esc(figs[n].get("title") or "")))
        elif kind == "li":
            if open_list[0] != "ul":
                close_list()
                body.append('<ul class="doc-list">')
                open_list[0] = "ul"
            para_runs[pid] = item["runs"]
            mark = '<span class="roman">%s</span>' % esc(item["mark"]) if item.get("mark") else ""
            body.append('<li id="%s"%s>%s<span>%s</span></li>' % (pid, ' class="marked"' if mark else "", mark,
                                                               runs_html(item["runs"], pid)))
        elif kind == "ref":
            if open_list[0] != "ol":
                close_list()
                body.append('<ol class="refs">')
                open_list[0] = "ol"
            body.append('<li id="%s">%s</li>' % (pid, runs_html(item["runs"], pid)))
        elif kind == "quote":
            para_runs[pid] = item["runs"]
            body.append('<blockquote id="%s">%s</blockquote>' % (pid, runs_html(item["runs"], pid)))
        else:
            para_runs[pid] = item["runs"]
            body.append('<p id="%s">%s</p>' % (pid, runs_html(item["runs"], pid)))
    close_list()

    def snippet(pid, label):
        """The sentence that holds a citation, with the citation marked."""
        text = re.sub(r"\s+", " ", plain(para_runs.get(pid, []), sup=False))
        for sentence in SENTENCE_END.split(text):
            if label in sentence:
                return esc(sentence).replace(esc(label), "<mark>%s</mark>" % esc(label), 1)
        return "<mark>%s</mark>" % esc(label)

    # ------------------------------------------------------------ legends, split at panel letters
    def caption_parts(fig):
        chars = [(c, bool(r.get("sup"))) for r in fig["caption"] for c in r["text"]]
        text = "".join(c for c, _ in chars)
        label = CAPTION.match(text)
        start = label.end() if label else 0
        title = fig.get("title") or ""
        at = text.find(title, start) if title else -1
        if 0 <= at <= start + 3:
            start = at + len(title)
        start += len(re.match(r"[\s.|:]*", text[start:]).group())

        def render(a, b):
            out_html, i = "", a
            while i < b:
                j = i
                while j < b and chars[j][1] == chars[i][1]:
                    j += 1
                piece = esc(text[i:j])
                out_html += "<sup>%s</sup>" % piece.strip() if chars[i][1] else piece
                i = j
            return out_html.strip()

        best = []
        for alphabet in ("ABCDEFGHIJKLMNOP", "abcdefghijklmnop"):
            cuts, pos = [], start
            for letter in alphabet:
                m = re.compile(r"(?:(?<=[\s.;:,])|^)(?:\(%s\)|%s\s?[.,|:)])\s*(?=[A-Z0-9(“\"])" % (letter, letter)).search(text, pos)
                if not m:
                    break
                cuts.append((letter, m.start(), m.end()))
                pos = m.end()
            if len(cuts) > len(best):
                best = cuts
        if len(best) < 2:
            best = []
        lead_end = best[0][1] if best else len(text)
        panels = [{"k": k, "html": render(e, best[i + 1][1] if i + 1 < len(best) else len(text))}
                  for i, (k, s, e) in enumerate(best)]
        return render(start, lead_end), panels

    # ------------------------------------------------------------ the pinned panel
    inferred = True
    if rail is None:                                      # no rail.json: list the top-level sections
        inferred = False
        tops = [i for i in doc["items"] if i["type"] == "h1"]
        rail = {"heading": "Sections", "links_heading": "Section", "groups": [], "links": {},
                "note": "Top-level sections of the document. Blue tags are the figures placed in each section; click one to show it."}
        by_name = {}
        for k, item in enumerate(tops, 1):
            by_name[nice(item["text"])] = "S%d" % k
            rail["groups"].append({"id": "S%d" % k, "tag": "Section %d" % k, "statement": item["text"], "anchor": item["id"]})
        for n in order:
            gid = by_name.get(placement.get(n, {}).get("top"))
            if gid:
                rail["links"][n] = [{"to": gid, "why": "Placed in this section"}]
    links = {str(n): v for n, v in rail.get("links", {}).items()}
    meta = {}

    def chips(target):
        out_html = ""
        for n in order:
            for link in links.get(n, []):
                if link["to"] == target:
                    out_html += '<a class="chip" href="#fig-%s" data-fig="%s">Fig %s%s</a>' % (
                        n, n, n, "<span>%s</span>" % esc(link["panels"]) if link.get("panels") else "")
        return out_html

    def jump(anchor, text="In text"):
        return '<button class="jump" type="button" data-target="%s">%s</button>' % (esc(anchor), text) if anchor else ""

    rail_html = []
    for group in rail["groups"]:
        meta[group["id"]] = {"label": group.get("tag", ""), "title": group.get("badge", ""), "parent": None}
        group_chips = chips(group["id"])
        rail_html.append('<section class="obj" data-aim="%s"><header class="obj-head"><span class="obj-tag">%s</span>%s%s</header>'
                         '<p class="obj-statement">%s</p>%s<ol class="subaims">' % (
                             esc(group["id"]), esc(group.get("tag", "")),
                             '<span class="obj-proj">%s</span>' % esc(group["badge"]) if group.get("badge") else "",
                             jump(group.get("anchor")), esc(group.get("statement", "")),
                             '<p class="chips obj-chips"><span class="chips-label">%s</span>%s</p>' % (
                                 esc(group.get("figures_label", "")), group_chips) if group_chips else ""))
        for sub in group.get("items", []):
            meta[sub["id"]] = {"label": "%s · %s" % (group.get("tag", ""), sub.get("mark", "")), "title": sub.get("title", ""),
                               "parent": group["id"]}
            detail = sub.get("detail")
            rail_html.append('<li class="sub" data-aim="%s"><span class="roman">%s</span><div class="sub-body">'
                             '<p class="sub-title">%s</p><p class="chips">%s%s%s</p>%s</div></li>' % (
                                 esc(sub["id"]), esc(sub.get("mark", "")), esc(sub.get("title", "")), chips(sub["id"]),
                                 jump(sub.get("anchor")),
                                 '<button class="jump more" type="button" aria-expanded="false">%s</button>' % esc(
                                     rail.get("detail_label", "Detail")) if detail else "",
                                 '<p class="sub-desc" hidden>%s</p>' % esc(detail) if detail else ""))
        rail_html.append("</ol></section>")

    # ------------------------------------------------------------ data for the page
    def embedded(fig):
        if not fig.get("image"):
            return None
        kind = "png" if fig["image"].lower().endswith(".png") else "jpeg"
        return "data:image/%s;base64,%s" % (kind, base64.b64encode((work / fig["image"]).read_bytes()).decode())

    data = {}
    for n in order:
        f = figs[n]
        lead, panels = caption_parts(f)
        data[n] = {"n": int(n), "title": f.get("title") or "", "lead": lead, "panels": panels,
                   "image": embedded(f) if single else f.get("image"), "w": f.get("w"), "h": f.get("h"),
                   "placement": placement.get(n, {}).get("path", ""), "anchor": "figcard-%s" % n if n in placement else "",
                   "cites": [{"id": c["id"], "label": c["label"], "section": c["section"], "snippet": snippet(c["pid"], c["label"])}
                             for c in cites[n]],
                   "aims": [{"id": l["to"], "panels": l.get("panels", ""), "why": l.get("why", "")}
                            for l in links.get(n, []) if l["to"] in meta]}
    thumbs = "".join('<a class="thumb" href="#fig-%s" data-fig="%s" title="Figure %s. %s">%s<span>%s</span></a>' % (
        n, n, n, esc(figs[n].get("title") or ""),
        img_tag(n), n) for n in order)
    default_note = ("Blue tags are the related figures; click one to show it. Figures are matched to the items in this panel "
                    "by their content, which the document does not state itself. Only “Cited in the text” lists the "
                    "citations the document makes.")
    title = doc.get("title") or Path(doc.get("source", "Document")).stem
    fill = {
        "%%PAGE_TITLE%%": esc(rail.get("page_title") or (" ".join(title.split()[:5]) + " Figure Map")),
        "%%RAIL_HEADING%%": esc(rail.get("heading", "Aims")),
        "%%RAIL_LABEL%%": esc(rail.get("label", "")),
        "%%RAIL_NOTE%%": esc(rail.get("note", default_note)),
        "%%RAIL%%": "\n".join(rail_html), "%%DOC%%": "\n".join(body), "%%THUMBS%%": thumbs,
        "%%DOC_TITLE%%": esc(title), "%%DOC_SUBTITLE%%": esc(doc.get("subtitle", "")),
        "%%SOURCE_LINE%%": esc("Source: %s. Blue tags in the text are figure citations; click one to show that figure."
                               % doc.get("source", "")),
        "%%FIGS%%": json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
        "%%AIMS%%": json.dumps(meta, ensure_ascii=False).replace("</", "<\\/"),
        "%%RAIL_META%%": json.dumps({"linksHeading": rail.get("links_heading", "Related to"), "inferred": inferred}),
    }
    page = (Path(__file__).resolve().parent.parent / "assets" / "template.html").read_text()
    for key, value in fill.items():
        page = page.replace(key, value)
    if single or "--standalone" in argv:
        page = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                '<style>body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n'
                + page + "\n</body>\n</html>\n")
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page)
    if not single and (work / "figures").resolve() != (out / "figures").resolve():
        (out / "figures").mkdir(exist_ok=True)
        for n in order:
            if figs[n].get("image"):
                shutil.copy2(work / figs[n]["image"], out / figs[n]["image"])

    print("wrote", out / "index.html", "(%d KB%s)" % (len(page) // 1024, ", figures embedded" if single else ""))
    for n in order:
        d = data[n]
        print("Figure %s | placed: %s | panels: %s | cited %d× %s | linked to: %s" % (
            n, d["placement"] or "NOT PLACED", "".join(p["k"] for p in d["panels"]) or "-", len(d["cites"]),
            [c["label"] for c in d["cites"]], [a["id"] for a in d["aims"]] or "-"))
    never = [n for n in order if not data[n]["cites"]]
    if never:
        print("Not cited anywhere in the text: Figure", ", ".join(never))
    lost = [l["to"] for n in links for l in links[n] if l["to"] not in meta]
    if lost:
        print("WARNING: links point at ids that are not in the rail:", sorted(set(lost)))


if __name__ == "__main__":
    main(sys.argv[1:])
