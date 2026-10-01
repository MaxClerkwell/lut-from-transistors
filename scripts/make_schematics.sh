#!/bin/sh
# Convert the schematic sheets that the paper shows from SVG (written by
# generate.py into docs/sheets/) to cropped PDF in paper/figures/.
set -e
cd "$(dirname "$0")/.."
mkdir -p paper/figures
for s in lut2 lut2-mux_n0 lut2-mux_n0-sw0 lut2-inv_a lut2-buffer; do
    inkscape "docs/sheets/$s.svg" --export-type=pdf --export-filename="paper/figures/sch_$s.pdf"
    pdfcrop --margins 6 "paper/figures/sch_$s.pdf" "paper/figures/sch_$s.pdf" >/dev/null
    echo "  wrote sch_$s.pdf"
done
