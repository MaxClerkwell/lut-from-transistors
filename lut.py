"""
A look-up table (LUT) built from MOS transistors, as a hierarchical design.

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

Hierarchy (sheet, file, how often it is used):

    lut2       lut2.kicad_sch       1   sources, load and the sheets below
      inverter   inverter.kicad_sch   2   AN = not A, BN = not B
      mux2       mux2.kicad_sch       3   2:1 multiplexer
        switch     switch.kicad_sch     2 per mux2, 6 in total
      buffer     buffer.kicad_sch     1   output buffer
        inverter   inverter.kicad_sch   2 per buffer

Three variants are provided:

    tgate   switches are transmission gates, NMOS and PMOS in parallel;
            the table bits are voltage sources
    pass    switches are single NMOS pass transistors (a 1 loses one
            threshold voltage); the table bits are voltage sources
    sram    transmission gates; the table bits are stored in four SRAM cells
            of six transistors each, written through a pair of bit lines and
            one word line per cell

In the variant `sram` the sheet sram_cell.kicad_sch is added, used 4 times,
with two more inverters each.
"""

from hier import Block, Design, U

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

VARIANTS = ("tgate", "pass", "sram")


# Pins of the transistors: 1 = drain, 2 = gate, 3 = source, 4 = bulk
def nmos(b, at, drain, gate, source, bulk="GND", rot=0, text=None):
    text = text or ((10.16, -1.27), (10.16, 1.27))
    return b.part("Simulation_SPICE", "NMOS_Substrate", "Q", "NMOS", at,
                  {1: drain, 2: gate, 3: source, 4: bulk}, rot=rot,
                  fields={"Sim.Device": "NMOS", "Sim.Type": "MOS1",
                          "Sim.Pins": "1=D 2=G 3=S 4=B", "Sim.Params": NMOS_PARAMS},
                  ref_at=text[0], val_at=text[1])


def pmos(b, at, drain, gate, source, bulk="+5V", rot=0, mirror=None, text=None):
    text = text or ((10.16, -1.27), (10.16, 1.27))
    return b.part("Simulation_SPICE", "PMOS_Substrate", "Q", "PMOS", at,
                  {1: drain, 2: gate, 3: source, 4: bulk}, rot=rot, mirror=mirror,
                  fields={"Sim.Device": "PMOS", "Sim.Type": "MOS1",
                          "Sim.Pins": "1=D 2=G 3=S 4=B", "Sim.Params": PMOS_PARAMS},
                  ref_at=text[0], val_at=text[1])


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------
def inverter_block():
    """CMOS inverter: OUT = not IN."""
    b = Block("inverter", "inverter.kicad_sch", title="CMOS inverter")
    ox, oy = 56 * U, 40 * U
    qp = pmos(b, (ox, oy - 3 * U), "OUT", "IN", "+5V", mirror="x")
    qn = nmos(b, (ox, oy + 3 * U), "OUT", "IN", "GND")

    gx = b.pin(qp, 2)[0]                                   # gates
    b.wire(b.pin(qp, 2), (gx, oy), b.pin(qn, 2))
    b.wire((ox - 8 * U, oy), (gx, oy))
    b.dot((gx, oy))
    b.port("IN", "input", (ox - 8 * U, oy), 180)
    dx = b.pin(qp, 1)[0]                                   # drains
    b.wire(b.pin(qp, 1), (dx, oy), b.pin(qn, 1))
    b.wire((dx, oy), (ox + 9 * U, oy))
    b.dot((dx, oy))
    b.port("OUT", "output", (ox + 9 * U, oy), 0)
    for qx, name, dy in ((qp, "+5V", -U), (qn, "GND", U)):  # source and bulk to the rail
        sx, sy = b.pin(qx, 3)
        b.wire((sx, sy), b.pin(qx, 4))
        b.wire((sx, sy), (sx, sy + dy))
        b.dot((sx, sy))
        b.power(name, (sx, sy + dy), 0)
    b.text("CMOS inverter: OUT = not IN\n"
           "The PMOS conducts for IN = 0, the NMOS for IN = 1.", (ox - 8 * U, oy - 14 * U))
    return b


def switch_block(variant):
    """Analog switch between IN and OUT, closed when ON = 1 (and ON_N = 0)."""
    kind = "transmission gate" if variant == "tgate" else "NMOS pass transistor"
    b = Block("switch", "switch.kicad_sch", title=f"Analog switch: {kind}")
    cx, cy = 56 * U, 40 * U
    xl, xr = cx - 3 * U, cx + 3 * U

    qn = nmos(b, (cx, cy + 4 * U), "IN", "ON", "OUT", rot=90, text=((-7.62, 5.08), (7.62, 5.08)))
    b.wire(b.pin(qn, 1), (xl, cy + 3 * U), (xl, cy))
    b.wire(b.pin(qn, 3), (xr, cy + 3 * U), (xr, cy))
    gx, gy = b.pin(qn, 2)
    b.wire((gx, gy), (gx, cy + 8 * U), (cx - 12 * U, cy + 8 * U))
    b.port("ON", "input", (cx - 12 * U, cy + 8 * U), 180)
    b.power("GND", b.pin(qn, 4), 180)

    if variant == "tgate":
        qp = pmos(b, (cx, cy - 4 * U), "OUT", "ON_N", "IN", rot=270,
                  text=((-7.62, -5.08), (7.62, -5.08)))
        b.wire(b.pin(qp, 3), (xl, cy - 3 * U), (xl, cy))
        b.wire(b.pin(qp, 1), (xr, cy - 3 * U), (xr, cy))
        gx, gy = b.pin(qp, 2)
        b.wire((gx, gy), (gx, cy - 8 * U), (cx - 12 * U, cy - 8 * U))
        b.port("ON_N", "input", (cx - 12 * U, cy - 8 * U), 180)
        b.power("+5V", b.pin(qp, 4), 180)
        b.dot((xl, cy))
        b.dot((xr, cy))

    b.wire((cx - 12 * U, cy), (xl, cy))
    b.port("IN", "passive", (cx - 12 * U, cy), 180)
    b.wire((xr, cy), (cx + 12 * U, cy))
    b.port("OUT", "passive", (cx + 12 * U, cy), 0)
    if variant == "tgate":
        b.text("Transmission gate: IN and OUT are connected when ON = 1 and ON_N = 0.\n"
               "The NMOS passes a 0 well, the PMOS passes a 1 well; together they pass both.",
               (cx - 12 * U, cy - 14 * U))
    else:
        b.text("Pass transistor: IN and OUT are connected when ON = 1.\n"
               "A 1 arrives one threshold voltage below the gate voltage.",
               (cx - 12 * U, cy - 14 * U))
    return b


def mux_block(variant, switch):
    """2:1 multiplexer: OUT = IN1 if SEL else IN0."""
    b = Block("mux2", "mux2.kicad_sch", title="2:1 multiplexer")
    x0, x1 = 22 * U, 94 * U
    controls = ["ON", "ON_N"] if variant == "tgate" else ["ON"]
    size = (14 * U, (len(controls) + 2) * 2 * U)
    for i, (name, inp, on, on_n) in enumerate((("sw0", "IN0", "SEL_N", "SEL"),
                                               ("sw1", "IN1", "SEL", "SEL_N"))):
        connect = {"IN": inp, "OUT": "OUT", "ON": on}
        if variant == "tgate":
            connect["ON_N"] = on_n
        c = b.child(switch, name, (52 * U, 18 * U + i * 20 * U), size,
                    ["IN"] + controls, ["OUT"], connect)
        for pin, net in connect.items():
            b.stub(c, pin, net)
    for i, (name, shape) in enumerate((("IN0", "passive"), ("IN1", "passive"),
                                       ("SEL", "input"), ("SEL_N", "input"))):
        y = 22 * U + i * 6 * U
        b.port(name, shape, (x0, y), 180)
        b.wire((x0, y), (x0 + 5 * U, y))
        b.label(name, (x0 + 5 * U, y), 0)
    y = 31 * U
    b.port("OUT", "passive", (x1, y), 0)
    b.wire((x1, y), (x1 - 5 * U, y))
    b.label("OUT", (x1 - 5 * U, y), 180)
    b.text("2:1 multiplexer: OUT = IN1 if SEL = 1, otherwise IN0.\n"
           "Exactly one of the two switches is closed.", (x0 - 2 * U, 10 * U))
    return b


def buffer_block(inverter):
    """Two inverters in series: restores the level and drives the load."""
    b = Block("buffer", "buffer.kicad_sch", title="Output buffer")
    size = (12 * U, 4 * U)
    c1 = b.child(inverter, "inv1", (40 * U, 30 * U), size, ["IN"], ["OUT"],
                 {"IN": "IN", "OUT": "MID"})
    c2 = b.child(inverter, "inv2", (66 * U, 30 * U), size, ["IN"], ["OUT"],
                 {"IN": "MID", "OUT": "OUT"})
    y = c1.pin("IN")[1]
    b.port("IN", "input", (28 * U, y), 180)
    b.wire((28 * U, y), c1.pin("IN"))
    b.wire(c1.pin("OUT"), c2.pin("IN"))
    b.port("OUT", "output", (90 * U, y), 0)
    b.wire(c2.pin("OUT"), (90 * U, y))
    b.label("MID", (59 * U, y), 0)                         # name of the node in between
    b.text("Output buffer: two inverters in series.\n"
           "The first one restores the logic level, the second one restores the polarity.",
           (28 * U, 20 * U))
    return b


def sram_cell_block(inverter):
    """
    SRAM cell with six transistors: two inverters that hold each other, and
    two access transistors that connect the cell to the bit lines while the
    word line WL is high. The output Q is taken directly from the cell.
    """
    b = Block("sram_cell", "sram_cell.kicad_sch", title="SRAM cell (6T)")
    y = 26 * U
    text = ((-7.62, 5.08), (7.62, 5.08))
    size = (12 * U, 4 * U)

    qa = nmos(b, (30 * U, 27 * U), "BL", "WL", "Q", rot=90, text=text)
    b.port("BL", "input", (18 * U, y), 180)
    b.wire((18 * U, y), b.pin(qa, 1))
    b.wire(b.pin(qa, 3), (36 * U, y))
    b.label("Q", (36 * U, y), 0)
    qb = nmos(b, (74 * U, 27 * U), "QN", "WL", "BLN", rot=90, text=text)
    b.wire((68 * U, y), b.pin(qb, 1))
    b.label("QN", (68 * U, y), 180)
    b.wire(b.pin(qb, 3), (86 * U, y))
    b.port("BLN", "input", (86 * U, y), 0)
    for qx in (qa, qb):
        gx, gy = b.pin(qx, 2)
        b.wire((gx, gy), (gx, 31 * U))
        b.label("WL", (gx, 31 * U), 270)
        b.power("GND", b.pin(qx, 4), 180)

    for name, at, inp, out in (("inv_q", (46 * U, 24 * U), "QN", "Q"),
                               ("inv_qn", (46 * U, 36 * U), "Q", "QN")):
        c = b.child(inverter, name, at, size, ["IN"], ["OUT"], {"IN": inp, "OUT": out})
        b.stub(c, "IN", inp)
        b.stub(c, "OUT", out)

    b.port("WL", "input", (18 * U, 38 * U), 180)
    b.wire((18 * U, 38 * U), (24 * U, 38 * U))
    b.label("WL", (24 * U, 38 * U), 0)
    b.port("Q", "output", (86 * U, 38 * U), 0)
    b.wire((86 * U, 38 * U), (80 * U, 38 * U))
    b.label("Q", (80 * U, 38 * U), 180)
    b.text("SRAM cell with six transistors.\n"
           "Two inverters hold each other: Q = not QN, QN = not Q.\n"
           "While WL = 1 the access transistors connect the cell to the bit lines,\n"
           "and the bit lines, driven from outside, overwrite the stored value.",
           (18 * U, 10 * U))
    return b


def source(b, at, kind, net, value, params, flag=False):
    v = b.part("Simulation_SPICE", kind, "V", value, at, {1: net, 2: "GND"},
               fields={"Sim.Params": params}, ref_at=(3.81, -1.27), val_at=(3.81, 1.27))
    xt, yt = b.pin(v, 1)
    xb, yb = b.pin(v, 2)
    b.wire((xb, yb), (xb, yb + U))
    b.power("GND", (xb, yb + U), 0)
    b.wire((xt, yt), (xt, yt - 2 * U))
    if net == "+5V":
        b.power("+5V", (xt, yt - 2 * U), 0)
    else:
        b.label(net, (xt, yt - 2 * U), 90)
    if flag:
        b.power("PWR_FLAG", (xt, yt - U), 90)
        b.dot((xt, yt - U))
        b.power("PWR_FLAG", (xb, yb + U), 90)


def lut2(variant="tgate", table=0b0110):
    """
    LUT with two inputs. `table` holds the four bits T3 T2 T1 T0; the default
    0b0110 is XOR. Returns the root block of the hierarchy.
    """
    assert variant in VARIANTS
    sram = variant == "sram"
    switch = "pass" if variant == "pass" else "tgate"
    inverter = inverter_block()
    mux = mux_block(switch, switch_block(switch))
    buffer = buffer_block(inverter)
    kind = "transmission gates" if switch == "tgate" else "NMOS pass transistors"
    if sram:
        kind += " and SRAM cells"
    b = Block("lut2", "lut2.kicad_sch", title=f"LUT with two inputs ({kind})")

    # sources; the order fixes the references V1 (supply), V2 (A), V3 (B), V4..V7 (table)
    source(b, (8 * U, 18 * U), "VDC", "+5V", f"{VDD:g}", f"dc={VDD:g}", flag=True)
    source(b, (8 * U, 38 * U), "VPULSE", "A", "A",
           f"y1=0 y2={VDD:g} td=200n tr=1n tf=1n tw=399n per=800n")
    source(b, (18 * U, 38 * U), "VPULSE", "B", "B",
           f"y1=0 y2={VDD:g} td=400n tr=1n tf=1n tw=399n per=800n")
    if sram:
        # bit lines and word lines; simulate.py replaces the waveforms by the write sequence
        source(b, (8 * U, 72 * U), "VDC", "BL", "0", "dc=0")
        source(b, (18 * U, 72 * U), "VDC", "BLN", f"{VDD:g}", f"dc={VDD:g}")
        for i in range(4):
            source(b, (32 * U + i * 10 * U, 72 * U), "VDC", f"WL{i}", "0", "dc=0")
        cell = sram_cell_block(inverter)
        for i in range(4):
            c = b.child(cell, f"cell{i}", (9 * U + i * 22 * U, 50 * U), (10 * U, 8 * U),
                        ["BL", "BLN", "WL"], ["Q"],
                        {"BL": "BL", "BLN": "BLN", "WL": f"WL{i}", "Q": f"T{i}"})
            for pin, net in c.connect.items():
                b.stub(c, pin, net)
        b.text("Configuration memory: four SRAM cells hold the table bits T0..T3", (5 * U, 46 * U))
        b.text("Bit lines BL, BLN (data) and word lines WL0..WL3 (address)", (5 * U, 64 * U))
    else:
        for i in range(4):
            bit = (table >> i) & 1
            source(b, (8 * U + i * 9 * U, 60 * U), "VDC", f"T{i}", f"{bit * VDD:g}",
                   f"dc={bit * VDD:g}")
        b.text("Table bits T0..T3 (in an FPGA: SRAM cells)", (5 * U, 51 * U))
    b.text("Supply", (5 * U, 9 * U))
    b.text("Inputs A and B", (5 * U, 29 * U))

    # sheets
    inv = (10 * U, 4 * U)
    mx = (12 * U, 10 * U)
    sheets = [
        (inverter, "inv_a", (32 * U, 16 * U), inv, ["IN"], ["OUT"], {"IN": "A", "OUT": "AN"}),
        (inverter, "inv_b", (32 * U, 30 * U), inv, ["IN"], ["OUT"], {"IN": "B", "OUT": "BN"}),
        (mux, "mux_n0", (52 * U, 12 * U), mx, ["IN0", "IN1", "SEL", "SEL_N"], ["OUT"],
         {"IN0": "T0", "IN1": "T1", "SEL": "A", "SEL_N": "AN", "OUT": "N0"}),
        (mux, "mux_n1", (52 * U, 30 * U), mx, ["IN0", "IN1", "SEL", "SEL_N"], ["OUT"],
         {"IN0": "T2", "IN1": "T3", "SEL": "A", "SEL_N": "AN", "OUT": "N1"}),
        (mux, "mux_y", (72 * U, 21 * U), mx, ["IN0", "IN1", "SEL", "SEL_N"], ["OUT"],
         {"IN0": "N0", "IN1": "N1", "SEL": "B", "SEL_N": "BN", "OUT": "YI"}),
        (buffer, "buffer", (92 * U, 21 * U), (10 * U, 4 * U), ["IN"], ["OUT"],
         {"IN": "YI", "OUT": "Y"}),
    ]
    for block, name, at, size, left, right, connect in sheets:
        c = b.child(block, name, at, size, left, right, connect)
        for pin, net in connect.items():
            b.stub(c, pin, net)

    cl = b.part("Device", "C", "CL", C_LOAD, (110 * U, 40 * U), {1: "Y", 2: "GND"},
                ref_at=(3.81, -1.27), val_at=(3.81, 1.27))
    x, y = b.pin(cl, 1)
    b.wire((x, y), (x, y - U))
    b.label("Y", (x, y - U), 90)
    x, y = b.pin(cl, 2)
    b.wire((x, y), (x, y + U))
    b.power("GND", (x, y + U), 0)
    b.text("Load", (108 * U, 33 * U))

    note = "table written through the bit lines" if sram else f"table T3 T2 T1 T0 = {table:04b}"
    b.text(f"Look-up table with two inputs, built from {kind}\n"
           f"Y = T[2 B + A], {note}", (5 * U, 4 * U))
    return b


def design(variant="tgate", table=0b0110):
    """Elaborated design: SKiDL circuit plus everything needed to write the sheets."""
    return Design(lut2(variant, table), "lut2")
