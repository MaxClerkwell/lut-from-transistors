#!/usr/bin/env python3
"""
Compare the atopile description of the LUT with the one in lut.py.

The two descriptions were written independently, in two languages. They
describe the same circuit if they contain the same transistors, of the same
type, at the same place in the hierarchy, and if every net connects the same
transistor pins. References differ (atopile numbers the parts in its own
order), so parts are identified by their address, e.g. mux_n0.sw0.qn.

Usage: uv run verify_atopile.py
"""

import sys

import ato_netlist
from lut import VARIANTS, design


def reference(variant):
    """Transistors of the design in lut.py: address -> (type, {pin: net object})."""
    d = design(variant)
    parts, groups = {}, set()
    by_ref = {p.ref: p for p in d.circuit.parts}
    for ref, address in d.addresses.items():
        parts[address] = "NMOS4" if by_ref[ref].value == "NMOS" else "PMOS4"
    for net in d.circuit.nets:
        pins = frozenset((d.addresses[p.part.ref], str(p.num)) for p in net.pins
                         if p.part.ref in d.addresses)
        if len(pins) > 1:
            groups.add(pins)
    return parts, groups


def main():
    ok = True
    for variant in VARIANTS:
        ref_parts, ref_groups = reference(variant)
        ato = ato_netlist.load(variant)
        ato_parts = {p.address: p.kind for p in ato}
        ato_groups = ato_netlist.connectivity(ato, key=lambda p: p.address)
        same_parts = ref_parts == ato_parts
        same_nets = ref_groups == ato_groups
        ok &= same_parts and same_nets
        print(f"{variant}: {len(ato_parts)} transistors, {len(ato_groups)} nets")
        print("  transistors (address and type):", "IDENTICAL" if same_parts else "MISMATCH")
        print("  connectivity:                  ", "IDENTICAL" if same_nets else "MISMATCH")
        for a in sorted(set(ref_parts) ^ set(ato_parts)):
            print("    only in", "lut.py: " if a in ref_parts else "atopile:", a)
        for g in sorted(ref_groups - ato_groups, key=sorted):
            print("    only in lut.py: ", sorted(g))
        for g in sorted(ato_groups - ref_groups, key=sorted):
            print("    only in atopile:", sorted(g))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
