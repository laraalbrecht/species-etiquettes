"""Species label generator: turn a CSV of taxa into a printable PDF of colored
etiquettes.

Audience note for R users:
- Coordinates are in PostScript points; 1 pt = 1/72 inch. ReportLab draws on a
  blank PDF much like grid graphics: you place rectangles and text by absolute
  x/y positions.
- The origin (0, 0) is at the bottom-left corner of the page (x rightwards, y
  upwards) — unlike the usual plot axes you might set up in ggplot2 where you
  often think top-to-bottom.

What this file does (high level):
1) Read a CSV with at least the columns 'taxon' and 'biogeographische_region'
   and optionally 'Autor_Jahr'.
2) For each taxon, derive one or two labels depending on whether it contains
   two or three words (genus species [subspecies]).
3) Paint a label background colored by zoogeographic region, place a white
   inner box (exact size taken from the original museum template), and draw
   the species epithet (bold, with optional underline) plus the author/year.
4) Lay labels on an A4 page in a regular grid (rows × columns), continue onto
   as many pages as needed, and save as a PDF.
"""

from reportlab.lib import colors
from reportlab.lib.colors import CMYKColor, Color
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas  # pyright: ignore[reportMissingTypeStubs]
import csv

# KONFIGURATION
from typing import TypedDict, Mapping, Any


class Margins(TypedDict):
    """Page margins in points (pt).

    These margins define the "usable" area on the sheet where the grid of labels
    will be placed. Everything is measured from the physical page edges towards
    the center.
    """

    left: float
    right: float
    top: float
    bottom: float


class Padding(TypedDict):
    """Inner padding between the white box and its contents, in points.

    Think of this like `plot.margin` or `panel.spacing` in ggplot2 terms — a
    small buffer so text does not touch the borders.
    """

    x: float
    y: float


class Config(TypedDict):
    """All tunable layout parameters collected in one place.

    - rows/cols: How many labels per page (rows × cols).
    - margins: Page margins in points.
    - name_font: Family and size used for the main species epithet.
    - author_font: Family and size for the 'Autor_Jahr' note.
    - line_width: Default frame width (used only for certain regions).
    - padding: Inner spacing in the white box so text has breathing room.
    - underline_offset: Vertical gap between text baseline and underline.
    """

    rows: int
    cols: int
    margins: Margins
    name_font: tuple[str, float]
    author_font: tuple[str, float]
    line_width: float
    padding: Padding
    underline_offset: float


class LabelSpec(TypedDict):
    """Concrete drawing instructions for one label.

    This is the "render-ready" format after we interpret the CSV row. Keeping
    this object small and explicit makes the rendering step simple and robust.
    """

    region_code: str
    main_text: str
    underline: bool
    author_text: str


# Global layout configuration for the whole sheet.
#
# Units are PostScript points (pt): 72 pt = 1 inch ≈ 2.54 cm.
# Tip: If you want slightly larger/smaller labels, adjust rows/cols or margins
# rather than the inner box dimensions (see EXACT_INNER_W/H below), which are
# tied to the visual template.
CONFIG: Config = {
    "rows": 17,
    "cols": 6,
    "margins": {"left": 20.0, "right": 20.0, "top": 20.0, "bottom": 20.0},  # pt
    "name_font": ("Helvetica", 12.0),  # (Fontname, Größe)
    "author_font": ("Helvetica", 6.0),
    "line_width": 1.2,  # Rahmenstärke (used for non-Europe where needed)
    "padding": {"x": 6.0, "y": 6.0},  # Innenabstand Text zu Rand
    "underline_offset": 2.0,  # Abstand Unterstreichung unter Grundlinie
}

# Background colors per faunal region.
# The CMYK values come from the original templates in `assets/…pdf`.
# For Europe ("PA") the outer field is intentionally white; only the inner
# box may have a black stroke to match the museum style.
REGION_COLOR: dict[str, colors.Color] = {
    # Exact CMYK extracted from templates (0..100 scale)
    # Europe outer is white; black is only used for stroke
    "PA": colors.white,  # Europa – field white
    "AF": CMYKColor(0, 100, 100, 0),  # Afrika – (0,1,1,0)
    "AS": CMYKColor(100, 0, 100, 0),  # Asien – keep standard unless specified
    "O": colors.HexColor("#215394"),  # Australien – RGB(33,83,148)
    "NW": CMYKColor(0, 0, 100, 0),  # Amerika – (0,0,1,0)
}

# Exact inner white box dimensions extracted from the PDFs [pt].
# These are the sizes of the white rectangle that sits inside the colored
# field. We center this rectangle within each cell to faithfully reproduce the
# look of the historic labels.
EXACT_INNER_W = 80.787
EXACT_INNER_H = 34.016
# Exact Europe stroke width [pt] — thickness of the black border on PA labels.
EUROPE_STROKE_W = 3.0


# return= REGION_COLOR?
def color_from_location(code: str) -> colors.Color | None:
    """Map a short region code (PA, AF, AS, O, NW) to its fill color.

    Returns None if the code is unknown; the caller then falls back to white.
    """
    return REGION_COLOR.get(code)


def load_data(csv_path: str) -> list[dict[str, str]]:
    """Read the CSV robustly and return a list of rows as dicts.

    The project has seen two slightly different CSV flavors:
    - "Original": semicolon-separated and without an 'Autor_Jahr' column.
    - "Cleaned": comma-separated with an 'Autor_Jahr' column.

    To be friendly to both, we:
    1) Peek at the first line to guess the delimiter (',' vs ';').
    2) Use csv.DictReader so rows are dictionaries keyed by column names.

    For an R analogy: this is a tiny, dependency-free version of
    readr::read_delim() with a little delimiter sniffing.
    """
    # "Versuch_Python.csv" eintragen!
    # The project currently uses two slightly different CSV layouts:
    # - Original: semicolon-separated without an Autor_Jahr column.
    # - Cleaned: comma-separated with an additional Autor_Jahr column.
    #
    # To keep this function robust, we auto-detect the delimiter so that both
    # variants are parsed correctly and Autor_Jahr is available when present.
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        # Peek at the first line to decide which delimiter is likely in use.
        first_line = f.readline()
        # Reset to the beginning for DictReader.
        f.seek(0)
        if ";" in first_line and "," not in first_line.split(";", 1)[0]:
            delimiter = ";"
        else:
            # Default to comma if we either see commas first or have a mixed header
            # like "taxon,biogeographische_region,..." from the cleaned file.
            delimiter = ","
        reader = csv.DictReader(f, delimiter=delimiter)
        return list(reader)  # type: ignore[no-any-return]


def compute_cell_size(page_width: float, page_height: float) -> tuple[float, float]:
    """Compute the width/height of one label cell given the page and margins.

    We subdivide the "usable" page area (after subtracting margins) into a
    simple rows × cols grid. Each grid cell hosts one label.
    """
    cols = CONFIG["cols"]
    rows = CONFIG["rows"]
    margins = CONFIG["margins"]

    usable_width = page_width - margins["left"] - margins["right"]
    usable_height = page_height - margins["top"] - margins["bottom"]
    cell_w = usable_width / cols
    cell_h = usable_height / rows
    return cell_w, cell_h


def compute_global_font_size(c: canvas.Canvas, labels: list[LabelSpec]) -> float:
    """
    Return a single "base" font size for all labels.

    We deliberately do **not** shrink this based on very long taxa names. Instead,
    we use this base size for all labels that fit, and handle exceptional long
    cases with a per-label dynamic downscaling in the drawing routine.
    """
    # If you are looking for a global "cex" knob (R terminology), this is it.
    # Increase the size in CONFIG["name_font"] to make everything larger; the
    # rendering code will still gracefully shrink extra-long words as needed.
    name_font = CONFIG["name_font"]
    return float(name_font[1])


def build_label_specs(data: list[dict[str, str]]) -> list[LabelSpec]:
    """
    Convert CSV rows into a flat list of label specifications.

    Rules:
    - If the taxon consists of exactly two words:
      * Use the second word (species epithet) as bold, underlined center text.
      * Show the Autor_Jahr in the lower right corner.
    - If the taxon consists of exactly three words:
      * Create two labels with the same region color:
        1. First label: second word, bold and underlined, no Autor_Jahr.
        2. Second label: third word, bold (no underline) and Autor_Jahr in the lower right.
    - All other cases fall back to a single label using the full normalized taxon string
      as the center text, without underlining; Autor_Jahr is printed if present.
    """
    specs: list[LabelSpec] = []

    for item in data:
        # Pull and normalize the taxon string. We strip and collapse whitespace
        # so that "Homo  sapiens " becomes "Homo sapiens". This makes the
        # subsequent word counting reliable.
        raw_taxon = item.get("taxon") or ""
        # Normalize whitespace:
        # - strip leading/trailing spaces (gets rid of the trailing space in case 1)
        # - collapse multiple internal spaces to a single space
        normalized_taxon = " ".join(raw_taxon.split())
        words = normalized_taxon.split(" ") if normalized_taxon else []

        # Region and author/year are read as-is (trimmed). Region codes are the
        # short strings used in the templates: PA, AF, AS, O, NW. Accept both CSV
        # column spellings: "biogeographische_region" (underscore) and
        # "biogeographische.region" (dot) — the cleaned file uses the latter.
        region_code = (
            item.get("biogeographische_region")
            or item.get("biogeographische.region")
            or ""
        ).strip()
        autor_jahr = (item.get("Autor_Jahr") or "").strip()

        if len(words) == 2:
            # Case 1: exactly two words – single label with the second word underlined
            specs.append(
                {
                    "region_code": region_code,
                    "main_text": words[1],
                    "underline": True,
                    "author_text": autor_jahr,
                }
            )
        elif len(words) == 3:
            # Case 2: exactly three words – two labels with identical color
            # 1) Second word, underlined, without Autor_Jahr
            specs.append(
                {
                    "region_code": region_code,
                    "main_text": words[1],
                    "underline": True,
                    "author_text": "",
                }
            )
            # 2) Third word, not underlined, with Autor_Jahr
            specs.append(
                {
                    "region_code": region_code,
                    "main_text": words[2],
                    "underline": False,
                    "author_text": autor_jahr,
                }
            )
        else:
            # Fallback: for 1-word taxa or >3 words, keep the normalized string as-is
            # without underlining. This avoids hard failures on imperfect input.
            specs.append(
                {
                    "region_code": region_code,
                    "main_text": normalized_taxon,
                    "underline": False,
                    "author_text": autor_jahr,
                }
            )

    return specs


def draw_labels(output_pdf: str, csv_path: str) -> None:
    """Render all labels from a CSV into a multi-page A4 PDF.

    Overview of the drawing pipeline:
    1) Load and parse the CSV rows.
    2) Translate each row into one or two LabelSpec objects (the "what").
    3) Loop through LabelSpecs in order, locating each in a grid cell (the "where").
    4) For each cell:
       - Paint the colored field for the region.
       - Center the white inner box; add black stroke for Europe ("PA") only.
       - Draw the main word, left-aligned inside the white box, bold and scaled
         down only if it would overflow.
       - Optionally underline the main word (exact width of the word).
       - Draw 'Autor_Jahr' in the lower right of the white box when present.

    Coordinate system refresher:
    - The point (0, 0) is bottom-left of the page; y increases upwards.
    - We compute the top-left of the usable area via margins, then step through
      the grid by column and row to place each label precisely.
    """
    c = canvas.Canvas(output_pdf, pagesize=A4)
    page_width, page_height = A4

    data = load_data(csv_path)
    if not data:
        c.save()
        return

    label_specs = build_label_specs(data)
    if not label_specs:
        c.save()
        return

    cols = CONFIG["cols"]
    rows = CONFIG["rows"]
    margins = CONFIG["margins"]
    padding = CONFIG["padding"]
    line_width: float = CONFIG["line_width"]
    author_font = CONFIG["author_font"]

    padding_x: float = padding["x"]
    padding_y: float = padding["y"]

    cell_w, cell_h = compute_cell_size(page_width, page_height)

    # Inner white box dimensions per template
    inner_w = EXACT_INNER_W
    inner_h = EXACT_INNER_H

    name_font = CONFIG["name_font"]
    name_font_name = name_font[0]
    # Use a bold face for the main label text; if the configured font is already bold,
    # re-use it as-is.
    bold_name_font_name = (
        name_font_name if name_font_name.endswith("-Bold") else f"{name_font_name}-Bold"
    )

    global_name_font_size = compute_global_font_size(c, label_specs)
    author_font_name = author_font[0]
    author_font_size = author_font[1]
    underline_offset: float = CONFIG["underline_offset"]

    labels_per_page = rows * cols

    for idx, spec in enumerate(label_specs):
        # Determine which page we are on and the index within that page.
        page_index = idx // labels_per_page
        index_on_page = idx % labels_per_page

        if index_on_page == 0 and idx > 0:
            # Start a new page after the previous one filled up.
            c.showPage()

        # Compute the target grid cell from the index. Column increases left→right,
        # row increases top→bottom inside the usable area.
        col = index_on_page % cols
        row = index_on_page // cols

        # Origin for this cell (bottom-left of colored field)
        x = margins["left"] + col * cell_w
        # row 0 is at the top inside the usable area
        y = page_height - margins["top"] - (row + 1) * cell_h

        region_code = spec["region_code"]
        field_color = color_from_location(region_code) or colors.white
        # For Europe (PA), the outside is white per template
        if region_code == "PA":
            field_color = colors.white

        # Draw colored field (background of the label)
        c.setFillColor(field_color)
        c.setStrokeColor(field_color)
        c.rect(x, y, cell_w, cell_h, fill=1, stroke=0)

        # Draw inner white box with a black border, always same size
        # Center the exact-size inner white box within the cell
        box_x = x + (cell_w - inner_w) / 2.0
        box_y = y + (cell_h - inner_h) / 2.0

        c.setFillColor(colors.white)
        # For non-Europe regions: no stroke around the white inner box
        # For Europe: white fill with black stroke of template thickness
        if region_code == "PA":
            c.setStrokeColor(colors.black)
            c.setLineWidth(EUROPE_STROKE_W)
            c.rect(box_x, box_y, inner_w, inner_h, fill=1, stroke=1)
        else:
            c.rect(box_x, box_y, inner_w, inner_h, fill=1, stroke=0)

        # Draw the main taxon element (word or full taxon) left-aligned inside the white box.
        # We start from a global base font size and shrink only for those rare cases
        # where the text would not fit into the inner box. The width measurement uses
        # ReportLab's stringWidth(), which returns the width in points for a given font.
        main_text = spec["main_text"]
        if main_text:
            c.setFillColor(colors.black)
            # Start with the global, shared font size for all "normal" labels.
            label_font_size = global_name_font_size

            # Check whether the current text would fit into the inner width
            # (respecting horizontal padding). If not, shrink only for this label.
            max_text_width = (inner_w - 2 * padding_x) * 0.95
            text_width = c.stringWidth(main_text, bold_name_font_name, label_font_size)
            if text_width > max_text_width and text_width > 0:
                scale = max_text_width / text_width
                # Avoid making the font unreadably small; 4pt is a conservative floor.
                label_font_size = max(global_name_font_size * scale, 4.0)
                text_width = c.stringWidth(
                    main_text, bold_name_font_name, label_font_size
                )

            c.setFont(bold_name_font_name, label_font_size)
            # Left alignment: keep the same vertical placement but align text to the
            # inner left edge, observing the horizontal padding.
            text_x = box_x + padding_x
            # approximate vertical centering (slightly below the geometric center)
            text_y = box_y + inner_h / 2.0 - label_font_size * 0.3
            c.drawString(text_x, text_y, main_text)

            # Optional underline for Case 1 and the first label of Case 2
            if spec["underline"]:
                underline_y = text_y - underline_offset
                # For left-aligned text, the underline should span exactly the word
                # width, starting at the same x-position as the text anchor.
                line_x0 = text_x
                line_x1 = text_x + text_width
                c.setStrokeColor(colors.black)
                c.setLineWidth(0.5)
                c.line(line_x0, underline_y, line_x1, underline_y)

        # Draw the author and year (if requested for this label) in the lower right corner
        author_text = spec["author_text"]
        if author_text:
            c.setFillColor(colors.black)
            c.setFont(author_font_name, author_font_size)
            author_x = box_x + inner_w - padding_x
            # Move the author label slightly further down within the inner box to
            # visually separate it from the main text.
            author_y = box_y + padding_y - 1.5
            c.drawRightString(author_x, author_y, author_text)

    c.save()


if __name__ == "__main__":
    # output_pdf: name of the output pdf file
    # csv_path: path to the csv file

    # example: draw_labels(output_pdf="output/family1.pdf", csv_path="data/Versuch_Python.csv")
    # -> creates a pdf file called "family1.pdf" in the "output" folder 
    # with the labels from the csv file "Versuch_Python.csv" in the "data" folder

    draw_labels(output_pdf="output/Etiketten_Cassidinae.pdf", csv_path="data/Cassidinae_Python_cleaned.csv")
