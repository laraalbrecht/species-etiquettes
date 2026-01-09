# Species Etiquettes

A simple PDF creation tool using ReportLab.

## Installation

Install dependencies with Poetry:

```bash
poetry install
```

## Usage

Run the PDF creation script:

```bash
poetry run python src/create_pdf.py
```

This will create an `output.pdf` file in the current directory.

Generate the Unit Tray labels with the museum layout by running:

```bash
poetry run python src/create_unit_tray_labels.py \
  --csv data/Cassidinae_Python_cleaned.csv \
  --output output/UnitTray_Labels.pdf
```

## Dependencies

- Python ^3.9
- ReportLab ^4.4.4


