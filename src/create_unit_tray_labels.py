"""Generate Unit Tray species labels mirroring the museum template."""
from __future__ import annotations

import argparse
import csv
import logging
from dataclasses import dataclass
from math import ceil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

logger = logging.getLogger("unit_tray_labels")


@dataclass(frozen=True)
class LabelSpec:
    """Lightweight structure describing the content and region of one label."""

    genus: str
    epithet: str
    author: str
    region: str


# Layout constants based on the provided Unit Tray template.
PAGE_WIDTH, PAGE_HEIGHT = A4
LABEL_WIDTH = 261.0
LABEL_HEIGHT = 92.0
COLUMNS = 2
ROWS = 8
LEFT_MARGIN = 41.0
TOP_MARGIN = 50.0
TEXT_PADDING_X = 12.0
BAR_STRIPE_WIDTH = 5.0
BAR_ORDER = ["PA", "AS", "NW", "AF", "O"]
BAR_AREA_WIDTH = BAR_STRIPE_WIDTH * len(BAR_ORDER)
LABEL_BORDER_WIDTH = 1.0
LABEL_VERTICAL_SPACING = 4.0

# Font definitions (chosen to balance readability with label height).
FONT_LINE1 = ("Helvetica", 16.0)
FONT_LINE2 = ("Helvetica-Oblique", 12.0)
FONT_LINE3 = ("Helvetica", 9.0)

REGION_COLORS: dict[str, colors.Color] = {
    "AF": colors.HexColor("#C8102E"),
    "NW": colors.HexColor("#FFCD00"),
    "AS": colors.HexColor("#1B8A3F"),
    "O": colors.HexColor("#1F5FAE"),
    "PA": colors.black,
}


def configure_logging() -> None:
    """Initialize logging with a consistent project-level format."""

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )


def load_csv(csv_path: Path) -> list[dict[str, str]]:
    """Read the CSV file as a list of dictionaries."""

    logger.info("Loading CSV data from %s", csv_path)
    if not csv_path.exists():
        logger.error("CSV file %s does not exist", csv_path)
        return []

    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = [row for row in reader]
    logger.info("Loaded %d rows from CSV", len(rows))
    return rows


def parse_taxon(taxon: str) -> tuple[str, str]:
    """Return the genus and the combined epithet pieces (italicized)."""

    cleaned = " ".join(taxon.strip().split())
    if not cleaned:
        return "", ""

    words = cleaned.split(" ")
    genus = words[0].capitalize()
    if len(words) >= 2:
        epithet_words = words[1:3]
        epithet = " ".join(epithet_words).lower()
    else:
        epithet = ""
    return genus, epithet


def build_label_specs(rows: list[dict[str, str]]) -> list[LabelSpec]:
    """Convert CSV rows into label specs that drive the drawing pipeline."""

    specs: list[LabelSpec] = []
    for row in rows:
        taxon = (row.get("taxon") or "").strip()
        if not taxon:
            logger.warning("Skipping row without a taxon entry: %s", row)
            continue

        genus, epithet = parse_taxon(taxon)
        autor_jahr = (row.get("Autor_Jahr") or "").strip()
        region = (
            row.get("biogeographische.region")
            or row.get("biogeographische_region")
            or ""
        ).strip().upper()
        specs.append(LabelSpec(genus=genus, epithet=epithet, author=autor_jahr, region=region))
    logger.info("Built %d label specs", len(specs))
    return specs


def _adjust_font_size(
    pdf: canvas.Canvas, text: str, font_name: str, base_size: float, max_width: float, min_size: float
) -> float:
    """Reduce the font size if the text does not fit; keep a sensible minimum."""

    if not text:
        return base_size

    width = pdf.stringWidth(text, font_name, base_size)
    if width <= max_width or width <= 0:
        return base_size
    scale = max_width / width
    new_size = max(base_size * scale, min_size)
    return new_size


def _compute_line_gap(sizes: tuple[float, float, float]) -> float:
    """Return the vertical gap used to equally space the three baselines."""

    max_visible = max((size for size in sizes if size > 0), default=FONT_LINE2[1])
    desired_gap = max_visible + LABEL_VERTICAL_SPACING * 2
    max_gap = max((LABEL_HEIGHT / 2) - 6.0, 4.0)
    return min(desired_gap, max_gap)


def _draw_centered_text(
    pdf: canvas.Canvas, text: str, font_name: str, font_size: float, center_x: float, baseline: float
) -> None:
    """Draw text centered around `center_x` with the specified baseline."""

    if not text:
        return
    pdf.setFont(font_name, font_size)
    pdf.setFillColor(colors.black)
    text_width = pdf.stringWidth(text, font_name, font_size)
    pdf.drawString(center_x - text_width / 2.0, baseline, text)


def _draw_colored_bars(pdf: canvas.Canvas, x: float, y: float, region: str) -> None:
    """Draw five vertical bar placeholders at the label's right edge."""

    bars_start_x = x + LABEL_WIDTH - BAR_AREA_WIDTH
    for index, code in enumerate(BAR_ORDER):
        bar_x = bars_start_x + index * BAR_STRIPE_WIDTH
        fill_color = REGION_COLORS.get(code, colors.white)
        if code != region:
            fill_color = colors.white
        pdf.setFillColor(fill_color)
        pdf.rect(
            bar_x,
            y,
            BAR_STRIPE_WIDTH,
            LABEL_HEIGHT,
            stroke=0,
            fill=1,
        )


def draw_labels(label_specs: list[LabelSpec], output_pdf: Path) -> None:
    """Lay out all labels onto an A4 canvas and write the final PDF."""

    c = canvas.Canvas(str(output_pdf), pagesize=A4)
    labels_per_page = ROWS * COLUMNS
    pages = ceil(len(label_specs) / labels_per_page)
    logger.info("Rendering %d pages for %d labels", pages, len(label_specs))

    for index, spec in enumerate(label_specs):
        if index > 0 and index % labels_per_page == 0:
            c.showPage()

        index_on_page = index % labels_per_page
        column = index_on_page % COLUMNS
        row = index_on_page // COLUMNS

        x = LEFT_MARGIN + column * LABEL_WIDTH
        y = PAGE_HEIGHT - TOP_MARGIN - (row + 1) * LABEL_HEIGHT

        c.setFillColor(colors.white)
        c.rect(x, y, LABEL_WIDTH, LABEL_HEIGHT, stroke=0, fill=1)

        _draw_colored_bars(c, x, y, spec.region)

        c.setLineWidth(LABEL_BORDER_WIDTH)
        c.setStrokeColor(colors.black)
        c.rect(x, y, LABEL_WIDTH, LABEL_HEIGHT, stroke=1, fill=0)

        text_area_left = x + TEXT_PADDING_X
        text_area_right = x + LABEL_WIDTH - BAR_AREA_WIDTH - TEXT_PADDING_X
        text_area_width = max(text_area_right - text_area_left, 1.0)
        text_center_x = text_area_left + text_area_width / 2.0
        center_y = y + LABEL_HEIGHT / 2.0

        line1_size = 0.0
        line2_size = 0.0
        line3_size = 0.0

        if spec.genus:
            line1_size = _adjust_font_size(
                c, spec.genus, FONT_LINE1[0], FONT_LINE1[1], text_area_width, 10.0
            )
        if spec.epithet:
            line2_size = _adjust_font_size(
                c, spec.epithet, FONT_LINE2[0], FONT_LINE2[1], text_area_width, 8.0
            )
        if spec.author:
            line3_size = _adjust_font_size(
                c, spec.author, FONT_LINE3[0], FONT_LINE3[1], text_area_width, 6.0
            )

        line_gap = _compute_line_gap((line1_size, line2_size, line3_size))
        line1_y = center_y + line_gap
        line2_y = center_y
        line3_y = center_y - line_gap

        if spec.genus:
            _draw_centered_text(c, spec.genus, FONT_LINE1[0], line1_size, text_center_x, line1_y)

        if spec.epithet:
            _draw_centered_text(c, spec.epithet, FONT_LINE2[0], line2_size, text_center_x, line2_y)

        if spec.author:
            _draw_centered_text(c, spec.author, FONT_LINE3[0], line3_size, text_center_x, line3_y)

    c.save()
    logger.info("Saved PDF with labels at %s", output_pdf)


def generate_pdf(csv_path: Path, output_path: Path) -> None:
    """Coordinate the workflow from CSV rows to rendered PDF."""

    rows = load_csv(csv_path)
    if not rows:
        logger.warning("No rows to render; exiting without creating a PDF")
        return

    specs = build_label_specs(rows)
    if not specs:
        logger.warning("No valid label specs extracted; exiting")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    draw_labels(specs, output_path)


def parse_arguments() -> argparse.Namespace:
    """Expose command-line options used to run the script."""

    parser = argparse.ArgumentParser(description="Generate Unit Tray species labels.")
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data/Cassidinae_Python_cleaned.csv"),
        help="Path to the CSV data file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/UnitTray_Labels.pdf"),
        help="Destination path for the generated PDF.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point used by Poetry when the script is executed."""

    args = parse_arguments()
    configure_logging()
    logger.info(
        "Creating labels for %s → %s",
        args.csv,
        args.output,
    )
    generate_pdf(args.csv, args.output)


if __name__ == "__main__":
    main()
