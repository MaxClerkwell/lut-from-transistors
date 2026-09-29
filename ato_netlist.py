"""
Read the result of an atopile build.

atopile compiles a design to a KiCad board file: one footprint per component,
with the net of every pad. This module reads the components, their place in
the hierarchy (the property `atopile_address`, e.g. mux_n0.sw0.qn) and their
nets back from that file, so the design can be compared with the one in
lut.py and simulated.
"""

from pathlib import Path

from kicad_sch import find, find_all, parse, unq

HERE = Path(__file__).resolve().parent
PINS = {"1": "D", "2": "G", "3": "S", "4": "B"}


class AtoPart:
    def __init__(self, ref, address, kind, pads):
        self.ref, self.address, self.kind, self.pads = ref, address, kind, pads

    def __repr__(self):
        return f"{self.ref} {self.address} {self.kind} {self.pads}"


def load(variant, directory=None):
    """Components of the atopile build `variant`, sorted by address."""
    directory = Path(directory or HERE / "atopile")
    pcb = directory / "layouts" / variant / f"{variant}.kicad_pcb"
    root = parse(pcb.read_text())[0]
    parts = []
    for fp in find_all(root, "footprint"):
        props = {unq(p[1]): unq(p[2]) for p in find_all(fp, "property")}
        pads = {}
        for pad in find_all(fp, "pad"):
            net = find(pad, "net")
            if net is not None:
                pads[unq(pad[1])] = unq(net[-1])
        parts.append(AtoPart(props["Reference"], props["atopile_address"],
                             props["Partnumber"], pads))
    return sorted(parts, key=lambda p: p.address)


def connectivity(parts, key=lambda p: p.ref):
    """Pin groups {frozenset((part, pin), ...)} of all nets with more than one pin."""
    nets = {}
    for p in parts:
        for pad, net in p.pads.items():
            nets.setdefault(net, set()).add((key(p), pad))
    return {frozenset(g) for g in nets.values() if len(g) > 1}
