# paper-figure-map

A Claude skill that turns a paper or grant proposal (.docx or PDF) into an interactive reading page: every figure is linked to the passages that cite it, and a pinned panel keeps the objectives, research questions or sections in view.

The page has three resizable columns:

- **Pinned panel**: objectives and subaims, research questions, or the section list, with tags that open the related figures.
- **Text**: the full text, with every figure citation turned into a link.
- **Figure**: the selected figure, the sentences that cite it, the pinned items it serves, and its legend split by panel.

## Install

Copy or clone this folder into your Claude skills folder:

```bash
git clone https://github.com/alexpengyl1/paper-figure-map.git ~/.claude/skills/paper-figure-map
```

The scripts need Python 3 with Pillow and PyMuPDF:

```bash
pip install pillow pymupdf
```

## Use

Ask Claude, for example: "Make a figure map of this paper" or "把这篇论文的每个 figure 和对应的正文联系起来，做成可交互的页面". The steps Claude follows are in [SKILL.md](SKILL.md); the two JSON formats are in [references/formats.md](references/formats.md).

The scripts also run on their own:

```bash
python scripts/extract_docx.py paper.docx work
```

```bash
python scripts/build_viewer.py work out --standalone
```

Then open `out/index.html` in a browser. Use `--single-file` instead of `--standalone` to embed the figures, so the one HTML file can be copied or sent on its own.

## Files

| Path | Purpose |
|---|---|
| `SKILL.md` | Instructions for Claude |
| `scripts/extract_docx.py` | .docx → `document.json` and figure images |
| `scripts/extract_pdf.py` | PDF → `document.json` and figure images |
| `scripts/build_viewer.py` | `document.json` (+ `rail.json`) → `index.html` |
| `scripts/figmap_common.py` | Helpers shared by the scripts |
| `assets/template.html` | The page: layout, styles and behaviour |
| `references/formats.md` | Format of `document.json` and `rail.json` |

## What has been tested

- The .docx route on one real grant proposal (eight figures, three of them EMF pictures, legends in text boxes).
- The PDF route on a two-column PDF generated from that same content, not yet on a journal PDF. Expect to correct some figure crops and heading levels by hand on real papers; `SKILL.md` describes how.

## Limits

Only main figures ("Figure N", "Fig. N") are mapped. Tables, supplementary figures, scanned PDFs and equations are not handled.

## License

MIT. See [LICENSE](LICENSE).
