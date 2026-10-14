# Nesting Trendz – Marketing Brochure

Turns the raw product document (`source/*.pdf`) into a designed marketing brochure
(`output/Nesting-Trendz-Brochure.pdf`).

## Updating the brochure

1. Edit the raw document as usual (e.g. in Google Docs) and download it as PDF.
2. Drop the PDF into `source/` (replace the old one, or keep both: the newest is used).
3. Run:

   ```powershell
   .\build-brochure.ps1
   ```

4. Read the **Review** list printed at the end (missing images, photos with no
   name or description, unmatched specs, placeholder contact details, pages that
   were too long) and check the PDF.

First time on a new machine: `.\build-brochure.ps1 -Setup` (installs Python packages + Chromium).

## Writing the raw document so it converts cleanly

The converter reads the document structure, so keep these conventions:

| In the raw doc | Becomes |
| --- | --- |
| First heading + paragraph | Cover title and intro statement |
| Heading `Product Collections` | Start of the product pages |
| Heading `1. Name (Subtitle)` | One product page per number |
| Sub-headings containing *Highlights* / *Applications* | Highlight list / application tags |
| Bullets written `Label: description` | Bold label + description |
| Photos placed after a product heading | That product's photos (first is the hero) |
| A photo's alt text (its name and description) | The caption on that photo |
| Heading with *Specification* / *Matrix* + a table | Spec page; rows also appear on each product page |
| Heading with *Projects* / *Customers* | Portfolio photo pages |
| Heading with *Trend* / *Inspiration*, items `Trend 1: Name` | Inspiration page |
| Heading with *Ordering* / *Contact* / *Consultation* | Back cover |

Headings must use a different font from body text (the doc's heading styles do this).
Any other heading becomes a simple text page, so nothing is silently dropped.

## Settings – `brochure/config.yaml`

Branding colours, cover/back-cover photos, section labels, page size, and **contact
details** (the raw doc currently has Google Docs placeholders for these, so they are
left off until filled in here).

## Files

| Path | Purpose |
| --- | --- |
| `source/` | Raw PDF input |
| `brochure/extract.py` | Reads the raw PDF into structured content |
| `brochure/build.py` | Plans pages, renders HTML, prints PDF |
| `brochure/templates/` | Brochure design (HTML + CSS) |
| `brochure/fonts/` | Cormorant Garamond + Plus Jakarta Sans (OFL) |
| `output/` | Generated: PDF, `brochure.html`, `content.json`, images |
