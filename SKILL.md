---
name: paper-figure-map
description: Turn a paper, manuscript, thesis chapter or grant proposal (.docx or PDF) into an interactive three-pane reading page that links every figure to the passages that cite it, with a pinned panel (objectives and subaims, research questions, or sections) that stays in view. Use this whenever the user wants to read or check a document figure by figure, see which part of the text each figure belongs to, keep the aims or questions visible while reading, or asks for a figure–text map, an interactive paper viewer, 图文对照, 把每个 figure 和对应的部分联系起来, 可交互地看论文, even if they only say "help me go through this paper and its figures". Not for summarising or translating a paper, and not for redrawing figures.
---

# Paper figure map

Build one page that lets a reader move between a document's figures and its text without losing the thread.

The page has three columns, each resizable by dragging the handle between them:

| Column | Holds | What the reader can do |
|---|---|---|
| Pinned panel (left) | Objectives and subaims, research questions, or the section list | Always in view. Tags under each item open the related figures; "In text" jumps to where the item is defined. |
| Text (middle) | The full text, verbatim | Every "Figure 3A–C" is a blue tag that opens that figure. |
| Figure (right) | One figure at a time | Enlarge it; see each sentence that cites it (click to jump back); see which pinned items it serves; read the legend split by panel. |

Selecting a figure lights up its citations in the text and its items in the pinned panel. Below about 1180 px the pinned panel becomes a strip on top; below about 760 px text and figure become two tabs.

## Workflow

Work in a scratch folder (`WORK`); the finished page goes to an output folder (`OUT`) next to the source file unless the user names another place. The scripts need Python 3 with Pillow, and PyMuPDF for PDFs and for EMF pictures (`pip install pillow pymupdf`).

### 1. Extract a draft

```bash
python scripts/extract_docx.py "paper.docx" WORK
```

```bash
python scripts/extract_pdf.py "paper.pdf" WORK
```

Both write `WORK/document.json` (headings, paragraphs and figure positions, in reading order), `WORK/figures/figN.jpg`, and `WORK/contact_sheet.png`, and print a report: title, heading outline, one line per figure, warnings.

Prefer the .docx when the user has both. Word keeps real paragraphs and the original pictures; a PDF has to be reverse-engineered from positioned text.

### 2. Check the draft, then fix it

The extraction is a guess, and a wrong guess here becomes a wrong link on the page. Before building:

- **Look at `contact_sheet.png`.** Each tile must show the whole figure and nothing else, under the right number.
- **Read the heading outline in the report.** Levels decide the section path shown for every figure and citation.
- **Read the warnings.** A figure with a legend but no picture, or a picture no legend claimed, needs a decision.

`document.json` is plain JSON and is meant to be edited: change an item's `type` (`h1`, `h2`, `h3`, `p`, `li`, `quote`, `ref`), fix a title, move a `fig` item, point a figure's `image` at another file. Common corrections:

- A line such as "OBJECTIVE 1. Profile …" that ends with a full stop is read as a paragraph. Make it a heading if the document uses it as one.
- Manuscripts often put all legends at the end and upload figures separately. The page then shows the legends without pictures; say so, and ask for the figure files if the user wants them shown (save each as `WORK/figures/figN.jpg` and set `image`, `w`, `h`).
- PDF only: a wrong crop. Render the page, read the box off the image, pass it back:

```bash
python scripts/extract_pdf.py "paper.pdf" WORK --pages 5
```

  Then write `boxes.json` as `{"3": {"page": 5, "bbox": [36, 60, 560, 410]}}` (points; the page image is 2 px per point) and rerun with `--boxes boxes.json`. Rerunning rewrites `document.json`, so settle the boxes before hand-editing it.

### 3. Write the pinned panel (`WORK/rail.json`)

The panel is what the reader keeps in view, so it should hold whatever the document is organised around:

| Document | Pin |
|---|---|
| Grant proposal, project plan | Objectives and their subaims |
| Research paper | The questions or hypotheses the paper sets out to answer (usually the end of the introduction), or its main claims |
| Thesis chapter, review | Its stated aims, or leave the automatic section list |

If the user names what to keep visible, pin that. Copy statements from the document word for word and give each an `anchor` (the `id` of the item in `document.json` where it is stated), so the reader can jump to the source.

Then link each figure to the items it serves, with the panels concerned and one line of reason:

```json
"links": {"7": [{"to": "O1-III", "panels": "C–F", "why": "Module–symptom correlations and the genes selected from them"}]}
```

These links are your reading of the figures. The document does not state them, and the page says so next to them; the "Cited in the text" list is the part that comes from the document. Keep that distinction honest: link a figure only where its content clearly bears on the item, and leave a figure unlinked when it is background.

The full format, with an example, is in `references/formats.md`. Without a `rail.json` the panel lists the top-level sections and the figures placed in each, which is a reasonable default for a first pass through a paper.

### 4. Build

```bash
python scripts/build_viewer.py WORK OUT
```

This writes `OUT/index.html` and `OUT/figures/`, and prints one line per figure: where it sits, the panels found in its legend, every citation, its links. Read that output. It is the cheapest place to catch a figure cited zero times (true, or a citation style the parser missed?) and a link pointing at an id that does not exist.

`index.html` is a page fragment, which is what the Artifact tool publishes. Add `--standalone` to get a complete HTML file that opens from disk.

### 5. Look once, then deliver

Take one screenshot before handing over (headless Chrome on a `--standalone` build works), mainly to confirm the figure shows and the three columns are laid out. Then:

- **Artifact tool available:** publish `OUT/index.html` with the files in `OUT/figures/` as supporting files, and leave it private.
- **Otherwise:** build with `--standalone` and give the user the path to `OUT/index.html`.

### 6. Tell the user what the page revealed

Keep it short. Worth saying: figures never cited in the text; legends that do not match their figure; figures you could not extract; what you pinned and why. Say plainly which links are yours.

## Ground rules

- **The text stays verbatim.** The page is a way to read the document, so nothing in the middle column is paraphrased, reordered beyond reading order, or corrected. Splitting one long paragraph into items is fine; rewording is not.
- **Unpublished work stays private.** Drafts, manuscripts under review and proposals often belong to someone other than the user. Keep the artifact private, keep extracted text and figures out of this skill's folder and out of any repository, and do not send them to other services.
- **Interface labels are in English**, whatever language the user writes in, unless they ask otherwise. The strings live in `assets/template.html` and in `rail.json`.
- **Change the look in the template.** Colours are CSS variables at the top of `assets/template.html`; both light and dark themes are defined there.

## Limits

- Only main figures numbered "Figure N" or "Fig. N" are mapped. Tables, supplementary and extended-data figures are left as ordinary text.
- Scanned PDFs (images of pages, no text layer) give no text; run OCR first or ask for another file.
- PDF paragraphs that break at a sentence end across columns or pages stay split; equations come through as plain text.
- EMF and WMF pictures in a .docx convert only when they carry an embedded PDF copy, which Word for Mac writes.
