"""
A look-up table (LUT) built from MOS transistors, described in SKiDL.

A LUT with k inputs stores the truth table of a logic function in 2^k memory
bits and selects one of them with a tree of 2:1 multiplexers. Each input
drives one level of the tree. Here k = 2:

    T0 --[A=0]--+
                +-- N0 --[B=0]--+
    T1 --[A=1]--+               +-- YI --|>o--|>o-- Y
    T2 --[A=0]--+               |
                +-- N1 --[B=1]--+
    T3 --[A=1]--+

The table index is 2*B + A. The four table bits T0..T3 are voltage sources;
in an FPGA they are SRAM cells written by the bitstream.

Two variants of the switch are provided:

    tgate   transmission gate, NMOS and PMOS in parallel (full swing)
    pass    a single NMOS pass transistor (loses one threshold voltage on a 1)

Every block function adds its parts to the SKiDL circuit and records the
placement and the wires for the schematic at the same time.
"""

import os

os.environ.setdefault("KICAD10_SYMBOL_DIR", "/usr/share/kicad/symbols")

from skidl import KICAD10, POWER, Circuit, Net, Part, set_default_tool

from kicad_sch import Placement

set_default_tool(KICAD10)

VDD = 5.0                   # supply voltage [V]
C_LOAD = "10p"              # load at the output

# Level-1 MOS models for a small enhancement MOSFET, W = L = 10 um, so KP is
# the transconductance parameter of the whole device. The numbers are chosen
# to be plausible, not to match a particular part or process:
#   threshold 1 V, on-resistance of the NMOS about 250 Ohm at 5 V gate drive,
#   PMOS half as strong, body effect (gamma) so that a pass transistor loses
#   more than one nominal threshold, junction capacitance 0.5 pF per terminal.
NMOS_PARAMS = ("w=10u l=10u vto=1 kp=1m gamma=0.4 phi=0.65 lambda=0.02 "
               "cgso=10n cgdo=10n cbd=0.5p cbs=0.5p")
PMOS_PARAMS = ("w=10u l=10u vto=-1 kp=0.5m gamma=0.4 phi=0.65 lambda=0.02 "
               "cgso=10n cgdo=10n cbd=0.5p cbs=0.5p")

U = 2.54                    # schematic grid unit [mm]
H = 1.27


class Sheet:
    """A SKiDL circuit plus the layout of its schematic."""

    # Where reference and value are written: offsets from the symbol origin.
    TEXT = {
        ("NMOS_Substrate", 0, None): ((10.16, -1.27), (10.16, 1.27)),
        ("PMOS_Substrate", 0, "x"): ((10.16, -1.27), (10.16, 1.27)),
        ("NMOS_Substrate", 90, None): ((-6.35, 3.81), (6.35, 3.81)),
        ("PMOS_Substrate", 270, None): ((-6.35, -3.81), (6.35, -3.81)),
        ("C", 0, None): ((3.81, -1.27), (3.81, 1.27)),
    }

    def __init__(self, name, paper="A3"):
        self.name, self.paper = name, paper
        self.circuit = Circuit()
        self.nets = {}
        self.placements, self.wires, self.junctions = {}, [], []
        self.labels, self.power_symbols, self.texts = [], [], []
        self.count = {}
        self.gnd = self.net("GND")
        self.vdd = self.net("+5V")
        self.gnd.drive = self.vdd.drive = POWER

    def net(self, name):
        if name not in self.nets:
            self.nets[name] = Net(name, circuit=self.circuit)
        return self.nets[name]

    def ref(self, prefix):
        self.count[prefix] = self.count.get(prefix, 0) + 1
        return f"{prefix}{self.count[prefix]}"

    def part(self, lib, name, ref, value, at, rot=0, mirror=None, fields=None):
        p = Part(lib, name, ref=ref, value=value, circuit=self.circuit)
        p.footprint = "simulation:none"          # simulation model, there is no board
        if fields:
            p.fields.update(fields)
        ref_at, val_at = self.TEXT.get((name, rot, mirror), (None, None))
        self.placements[ref] = Placement(lib, name, at, rot, mirror, ref_at, val_at)
        return p

    def nmos(self, at, rot=0, mirror=None):
        return self.part("Simulation_SPICE", "NMOS_Substrate", self.ref("Q"), "NMOS", at, rot,
                         mirror, {"Sim.Device": "NMOS", "Sim.Type": "MOS1",
                                  "Sim.Pins": "1=D 2=G 3=S 4=B", "Sim.Params": NMOS_PARAMS})

    def pmos(self, at, rot=0, mirror=None):
        return self.part("Simulation_SPICE", "PMOS_Substrate", self.ref("Q"), "PMOS", at, rot,
                         mirror, {"Sim.Device": "PMOS", "Sim.Type": "MOS1",
                                  "Sim.Pins": "1=D 2=G 3=S 4=B", "Sim.Params": PMOS_PARAMS})

    def pin(self, part, num):
        return self.placements[part.ref].pin(num)

    def wire(self, *pts):
        self.wires.append([(round(x, 2), round(y, 2)) for x, y in pts])

    def dot(self, p):
        self.junctions.append((round(p[0], 2), round(p[1], 2)))

    def label(self, name, p, rot=0):
        self.labels.append((name, (round(p[0], 2), round(p[1], 2)), rot, False))

    def power(self, name, p, rot=0):
        self.power_symbols.append((name, (round(p[0], 2), round(p[1], 2)), rot))

    def text(self, txt, p):
        self.texts.append((txt, p))


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------
def inverter(s, origin, inp, out, title=""):
    """CMOS inverter: out = not inp."""
    ox, oy = origin
    i, o = s.net(inp), s.net(out)
    qp = s.pmos((ox, oy - 3 * U), mirror="x")
    qn = s.nmos((ox, oy + 3 * U))
    qp[2] += i
    qn[2] += i
    qp[1] += o
    qn[1] += o
    qp[3] += s.vdd
    qp[4] += s.vdd
    qn[3] += s.gnd
    qn[4] += s.gnd

    # pins of the transistors: 1 = drain, 2 = gate, 3 = source, 4 = bulk
    gx = s.pin(qp, 2)[0]                                   # gates
    s.wire(s.pin(qp, 2), (gx, oy), s.pin(qn, 2))
    s.wire((ox - 4 * U, oy), (gx, oy))
    s.dot((gx, oy))
    s.label(inp, (ox - 4 * U, oy), 180)
    dx = s.pin(qp, 1)[0]                                   # drains
    s.wire(s.pin(qp, 1), (dx, oy), s.pin(qn, 1))
    s.wire((dx, oy), (ox + 5 * U, oy))
    s.dot((dx, oy))
    s.label(out, (ox + 5 * U, oy), 0)
    for q, name, dy in ((qp, "+5V", -U), (qn, "GND", U)):  # source and bulk to the rail
        sx, sy = s.pin(q, 3)
        s.wire((sx, sy), s.pin(q, 4))
        s.wire((sx, sy), (sx, sy + dy))
        s.dot((sx, sy))
        s.power(name, (sx, sy + dy), 0)
    if title:
        s.text(title, (ox - 4 * U, oy - 9 * U))


def switch(s, origin, inp, out, on_high, on_low, variant, title=""):
    """
    Analog switch between inp and out, closed when net `on_high` is 1.

    tgate : NMOS (gate = on_high) and PMOS (gate = on_low) in parallel
    pass  : the NMOS alone
    """
    cx, cy = origin
    i, o = s.net(inp), s.net(out)
    xl, xr = cx - 3 * U, cx + 3 * U

    qn = s.nmos((cx, cy + 4 * U), rot=90)
    qn[1] += i
    qn[3] += o
    qn[2] += s.net(on_high)
    qn[4] += s.gnd
    s.wire(s.pin(qn, 1), (xl, cy + 3 * U), (xl, cy))
    s.wire(s.pin(qn, 3), (xr, cy + 3 * U), (xr, cy))
    gx, gy = s.pin(qn, 2)
    s.wire((gx, gy), (gx, gy + U))
    s.label(on_high, (gx, gy + U), 270)
    s.power("GND", s.pin(qn, 4), 180)

    if variant == "tgate":
        qp = s.pmos((cx, cy - 4 * U), rot=270)
        qp[1] += o
        qp[3] += i
        qp[2] += s.net(on_low)
        qp[4] += s.vdd
        s.wire(s.pin(qp, 3), (xl, cy - 3 * U), (xl, cy))
        s.wire(s.pin(qp, 1), (xr, cy - 3 * U), (xr, cy))
        gx, gy = s.pin(qp, 2)
        s.wire((gx, gy), (gx, gy - U))
        s.label(on_low, (gx, gy - U), 90)
        s.power("+5V", s.pin(qp, 4), 180)
        s.dot((xl, cy))
        s.dot((xr, cy))

    s.wire((cx - 6 * U, cy), (xl, cy))
    s.label(inp, (cx - 6 * U, cy), 180)
    s.wire((xr, cy), (cx + 6 * U, cy))
    s.label(out, (cx + 6 * U, cy), 0)
    if title:
        s.text(title, (cx - 6 * U, cy - 8.5 * U))


def mux(s, origin, in0, in1, out, sel, sel_n, variant, title=""):
    """2:1 multiplexer: out = in1 if sel else in0."""
    cx, cy = origin
    switch(s, (cx, cy), in0, out, sel_n, sel, variant, title=f"{title}: {in0} if {sel} = 0")
    switch(s, (cx, cy + 18 * U), in1, out, sel, sel_n, variant, title=f"{in1} if {sel} = 1")


def source(s, origin, ref, kind, net, value, params, flag=False):
    ox, oy = origin
    v = s.part("Simulation_SPICE", kind, ref, value, (ox, oy), fields={"Sim.Params": params})
    v[1] += s.net(net)
    v[2] += s.gnd
    xt, yt = s.pin(v, 1)
    xb, yb = s.pin(v, 2)
    s.wire((xb, yb), (xb, yb + U))
    s.power("GND", (xb, yb + U), 0)
    if net == "+5V":
        s.wire((xt, yt), (xt, yt - 2 * U))
        s.power("+5V", (xt, yt - 2 * U), 0)
    else:
        s.wire((xt, yt), (xt, yt - 2 * U))
        s.label(net, (xt, yt - 2 * U), 90)
    if flag:
        s.power("PWR_FLAG", (xt, yt - U), 90)
        s.dot((xt, yt - U))
        s.power("PWR_FLAG", (xb, yb + U), 90)


def lut2(variant="tgate", table=0b0110):
    """
    LUT with two inputs. `table` holds the four bits T3 T2 T1 T0; the default
    0b0110 is XOR. Returns the Sheet.
    """
    assert variant in ("tgate", "pass")
    s = Sheet(f"lut2_{variant}")
    bits = [(table >> i) & 1 for i in range(4)]

    # sources, left column
    source(s, (10 * U, 20 * U), "V1", "VDC", "+5V", f"{VDD:g}", f"dc={VDD:g}", flag=True)
    source(s, (10 * U, 40 * U), "VA1", "VPULSE", "A", "A",
           f"y1=0 y2={VDD:g} td=100n tr=1n tf=1n tw=100n per=200n")
    source(s, (10 * U, 56 * U), "VB1", "VPULSE", "B", "B",
           f"y1=0 y2={VDD:g} td=200n tr=1n tf=1n tw=200n per=400n")
    for i, b in enumerate(bits):
        source(s, (10 * U + i * 8 * U, 76 * U), f"VT{i}", "VDC", f"T{i}",
               f"{b * VDD:g}", f"dc={b * VDD:g}")
    s.text("Supply", (6 * U, 10 * U))
    s.text("Inputs", (6 * U, 31 * U))
    s.text("Table bits T0..T3 (in an FPGA: SRAM cells)", (6 * U, 67 * U))

    # input inverters
    inverter(s, (34 * U, 22 * U), "A", "AN", title="Inverter: AN = not A")
    inverter(s, (34 * U, 48 * U), "B", "BN", title="Inverter: BN = not B")

    # multiplexer tree
    mux(s, (62 * U, 14 * U), "T0", "T1", "N0", "A", "AN", variant, title="Level 1")
    mux(s, (62 * U, 54 * U), "T2", "T3", "N1", "A", "AN", variant, title="Level 1")
    mux(s, (90 * U, 34 * U), "N0", "N1", "YI", "B", "BN", variant, title="Level 2")

    # output buffer and load
    inverter(s, (118 * U, 22 * U), "YI", "YB", title="Buffer, first stage")
    inverter(s, (118 * U, 48 * U), "YB", "Y", title="Buffer, second stage: Y")
    c = s.part("Device", "C", "CL1", C_LOAD, (140 * U, 50 * U))
    c[1] += s.net("Y")
    c[2] += s.gnd
    x, y = s.pin(c, 1)
    s.wire((x, y), (x, y - U))
    s.label("Y", (x, y - U), 90)
    x, y = s.pin(c, 2)
    s.wire((x, y), (x, y + U))
    s.power("GND", (x, y + U), 0)

    kind = ("transmission gates" if variant == "tgate" else "NMOS pass transistors")
    s.text(f"Look-up table with two inputs, built from {kind}\n"
           f"Y = T[2 B + A], table T3 T2 T1 T0 = {table:04b}", (6 * U, 4 * U))
    return s


VARIANTS = ("tgate", "pass")
