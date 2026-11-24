# File formats

Two JSON files drive the page. `document.json` is written by the extract scripts and corrected by hand. `rail.json` is written by hand.

## document.json

```json
{
  "title": "Title of the document",
  "subtitle": "Optional second line",
  "source": "paper.docx",
  "items": [
    {"type": "h1", "id": "b1", "text": "INTRODUCTION"},
    {"type": "p",  "id": "b2", "runs": [{"text": "Plain text, ", "b": false, "i": false, "sup": false},
                                        {"text": "bold text", "b": true, "i": false, "sup": false}]},
    {"type": "fig", "id": "b3", "n": 1},
    {"type": "li", "id": "b4", "mark": "I", "runs": [{"text": "A list item; mark is optional"}]}
  ],
  "figures": {
    "1": {"title": "Short title", "image": "figures/fig1.jpg", "w": 2000, "h": 1200,
          "caption": [{"text": "Figure 1. Short title. A. First panel. B. Second panel.", "b": false, "i": false, "sup": false}]}
  }
}
```

| Field | Meaning |
|---|---|
| `items` | Everything in reading order. `id` is unique and is what `anchor` in `rail.json` points at. |
| `type` | `h1`, `h2`, `h3` (headings), `p`, `li` (list item), `quote`, `ref` (one reference), `fig` (where figure `n` sits in the text). |
| `runs` | Pieces of text with the same formatting. `sup` marks superscripts such as citation numbers. Missing flags count as false. |
| `figures` | Keyed by figure number as a string. `caption` is the whole legend, starting with its "Figure N." label. `image` is relative to the work folder, or `null` when the source holds no picture. `page` and `bbox` appear for PDFs. |

What the build step works out from this, so it need not be written by hand:

- **Citations.** "Figure 2", "Fig. 3a,b", "Figures 4A–C", "Figure 7 and 8" in any `runs` become links, unless preceded by "Supplementary" or "Extended Data".
- **Section paths.** From the headings above each figure and citation.
- **Legend panels.** A legend is split where consecutive letters open a part: `A.` `B.`, `a,` `b,`, `(A)` `(B)`, `a |` `b |`.

## rail.json

```json
{
  "heading": "Objectives and subaims",
  "label": "Short name of the document",
  "links_heading": "Related objective and subaim",
  "detail_label": "Approach",
  "groups": [
    {
      "id": "O1", "tag": "Objective 1", "badge": "PROJECT", "anchor": "b23",
      "statement": "The objective, word for word.",
      "figures_label": "Background",
      "items": [
        {"id": "O1-I", "mark": "I", "anchor": "b26",
         "title": "The subaim, word for word.",
         "detail": "Optional: how it will be done, shown when the reader opens it."}
      ]
    }
  ],
  "links": {
    "5": [{"to": "O1-I", "why": "One line on what in the figure bears on this item"}],
    "7": [{"to": "O1-I", "panels": "A–B", "why": "…"}, {"to": "O1", "why": "…"}]
  }
}
```

| Field | Meaning |
|---|---|
| `heading` | Title of the panel: "Objectives and subaims", "Research questions", "Main claims". |
| `label` | Small grey text beside the heading. Optional. |
| `links_heading` | Heading above a figure's links in the right column. Default "Related to". |
| `detail_label` | Text of the button that opens an item's `detail`. Default "Detail". |
| `groups` | One block per objective, question or claim. `tag` is its short label, `badge` an optional second label, `statement` its text, `anchor` the `id` of the item in `document.json` where it is stated. |
| `groups[].items` | Optional sub-items. `mark` is what is shown in the small box (I, II, a, 1). |
| `groups[].figures_label` | Label before the figure tags that link to the group itself (rather than to one of its items). |
| `links` | Figure number → list of `{to, panels, why}`. `to` is a group `id` or an item `id`. `panels` is optional. |
| `note` | Replaces the explanatory note at the bottom of the panel. Optional. |
| `page_title` | Replaces the browser-tab title. Optional. |

A paper usually needs groups only:

```json
{
  "heading": "Research questions",
  "links_heading": "Answers which question",
  "groups": [
    {"id": "Q1", "tag": "Question 1", "anchor": "b9", "statement": "Does X depend on Y?"},
    {"id": "Q2", "tag": "Question 2", "anchor": "b9", "statement": "Is the effect cell-type specific?"}
  ],
  "links": {"2": [{"to": "Q1", "panels": "a–c", "why": "Dose–response of X to Y"}]}
}
```
