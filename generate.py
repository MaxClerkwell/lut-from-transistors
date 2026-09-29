#!/usr/bin/env python3
"""
Generate netlist and schematic of both LUT variants from their SKiDL
description and verify that the schematic describes the same circuit.

Usage: uv run generate.py
  -> <name>.net          KiCad netlist written by SKiDL
  -> <name>.kicad_sch    KiCad schematic (also runs in the KiCad simulator)
  -> docs/<name>.svg     rendering of the schematic
  -> docs/<name>.pdf
"""

import shutil
import subprocess
import sys
from pathlib import Path

from lut import VARIANTS, lut2
from kicad_sch import find, find_all, parse, unq, write_schematic

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"


def skidl_connectivity(circuit):
    groups = set()
    for net in circuit.nets:
        pins = frozenset((p.part.ref, str(p.num)) for p in net.pins)
        if len(pins) > 1:
            groups.add(pins)
    return groups


def kicad_connectivity(sch):
    """Export the schematic netlist with kicad-cli and return its pin groups."""
    out = BUILD / (sch.stem + "_export.net")
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
    (HERE / "docs").mkdir(exist_ok=True)
    have_cli = shutil.which("kicad-cli") is not None
    ok = True
    for variant in VARIANTS:
        m = lut2(variant)
        name = m.name
        m.circuit.generate_netlist(file_=str(HERE / f"{name}.net"))
        sch = write_schematic(m.circuit, HERE / f"{name}.kicad_sch", m.placements, m.wires,
                              m.junctions, m.labels, m.power_symbols, m.texts,
                              title=f"LUT with two inputs ({variant})", paper=m.paper)
        print(f"{name}: {len(m.circuit.parts)} parts, written {sch.name}, {name}.net")
        if not have_cli:
            print("  kicad-cli not found: consistency check and rendering skipped")
            continue
        a, b = skidl_connectivity(m.circuit), kicad_connectivity(sch)
        same = a == b
        ok &= same
        print("  schematic <-> SKiDL netlist:", "IDENTICAL" if same else "MISMATCH")
        for g in sorted(b - a, key=sorted):
            print("    only in schematic:", sorted(g))
        for g in sorted(a - b, key=sorted):
            print("    only in SKiDL:    ", sorted(g))
        subprocess.run(["kicad-cli", "sch", "export", "svg", "--exclude-drawing-sheet",
                        "--no-background-color", "-o", str(BUILD), str(sch)],
                       check=True, capture_output=True)
        shutil.copy(BUILD / f"{name}.svg", HERE / "docs" / f"{name}.svg")
        subprocess.run(["kicad-cli", "sch", "export", "pdf", "--exclude-drawing-sheet",
                        "--no-background-color", "-o", str(HERE / "docs" / f"{name}.pdf"), str(sch)],
                       check=True, capture_output=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
