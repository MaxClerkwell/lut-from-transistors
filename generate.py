#!/usr/bin/env python3
"""
Generate netlist and hierarchical schematic of the LUT from its description
and verify that the schematic describes the same circuit.

Usage: uv run generate.py
  -> schematic/lut2.kicad_sch      root sheet
     schematic/mux2.kicad_sch, switch.kicad_sch, inverter.kicad_sch, buffer.kicad_sch
  -> schematic/lut2.net            KiCad netlist written by SKiDL (flat)
  -> docs/sheets/*.svg             one rendering per sheet
  -> docs/lut2.pdf                 all sheets in one file
"""

import shutil
import subprocess
import sys
from pathlib import Path

from kicad_sch import find, find_all, parse, unq
from lut import design

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SCHEMATIC = HERE / "schematic"
DOCS = HERE / "docs"


def kicad_connectivity(sch):
    """Export the schematic netlist with kicad-cli and return its pin groups."""
    out = BUILD / "lut2_export.net"
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadsexpr",
                    "-o", str(out), str(sch)], check=True, capture_output=True)
    root = parse(out.read_text())[0]
    groups = set()
    for net in find_all(find(root, "nets"), "net"):
        pins = frozenset((unq(find(n, "ref")[1]), unq(find(n, "pin")[1]))
                         for n in find_all(net, "node"))
        pins = frozenset(p for p in pins if not p[0].startswith("#"))
        if len(pins) > 1:
            groups.add(pins)
    return groups


def main():
    BUILD.mkdir(exist_ok=True)
    DOCS.mkdir(exist_ok=True)
    d = design()
    sch = d.write(SCHEMATIC)
    d.circuit.generate_netlist(file_=str(SCHEMATIC / "lut2.net"))
    uses = {}
    for _, block in d.instances:
        uses[block.filename] = uses.get(block.filename, 0) + 1
    print(f"lut2: {len(d.circuit.parts)} parts on {len(d.instances)} sheets from "
          f"{len(uses)} files: " + ", ".join(f"{f} x{n}" for f, n in uses.items()))
    if shutil.which("kicad-cli") is None:
        print("  kicad-cli not found: consistency check and rendering skipped")
        sys.exit(0)
    a, b = d.connectivity(), kicad_connectivity(sch)
    same = a == b
    print("  schematic <-> SKiDL netlist:", "IDENTICAL" if same else "MISMATCH")
    for g in sorted(b - a, key=sorted):
        print("    only in schematic:", sorted(g))
    for g in sorted(a - b, key=sorted):
        print("    only in SKiDL:    ", sorted(g))
    svg = BUILD / "sheets"
    shutil.rmtree(svg, ignore_errors=True)
    subprocess.run(["kicad-cli", "sch", "export", "svg", "--exclude-drawing-sheet",
                    "--no-background-color", "-o", str(svg), str(sch)],
                   check=True, capture_output=True)
    shutil.rmtree(DOCS / "sheets", ignore_errors=True)
    shutil.copytree(svg, DOCS / "sheets")
    subprocess.run(["kicad-cli", "sch", "export", "pdf", "--exclude-drawing-sheet",
                    "--no-background-color", "-o", str(DOCS / "lut2.pdf"), str(sch)],
                   check=True, capture_output=True)
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
