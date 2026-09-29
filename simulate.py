#!/usr/bin/env python3
"""
Simulate the LUT schematics with ngspice and write the result as a VCD file
for GTKWave.

The hierarchical schematic <variant>/lut2.kicad_sch is exported to a flat
SPICE netlist with `kicad-cli`. One transient
run covers all 16 functions of two inputs: every 800 ns the four table bits
are rewritten, the way a new bitstream would rewrite the SRAM cells of an
FPGA, while the inputs step through all four combinations in Gray code
(index 0, 1, 3, 2), so that only one input changes at a time. A second,
short run changes both inputs at the same instant and looks for glitches.

Usage: uv run simulate.py [--source kicad|atopile] [--results DIR]

With `--source atopile` the transistors and their nets are taken from the
board files of the atopile build (atopile/layouts/) instead of the KiCad
schematic; sources and load are added as a test bench. Results then go to
results/atopile/.

In the variant `sram` the table bits are not sources but SRAM cells. Each
rewrite of the table is a sequence of four write cycles: the bit lines are
set to the value, then the word line of one cell is pulsed.

Results, for each variant (tgate, pass, sram):
  results/lut2_<variant>.vcd     logic values and node voltages, for GTKWave
  results/lut2_<variant>.gtkw    GTKWave save file: signal list and analog traces
  results/lut2_<variant>_glitch.vcd, .gtkw    the glitch experiment
  results/lut2_<variant>.csv     the node voltages
  results/lut2_<variant>.cir     the simulated netlist
  results/lut2_<variant>.png     overview plot
  results/summary.md             truth tables, delays, levels, supply current

View:  gtkwave results/lut2_tgate.vcd results/lut2_tgate.gtkw
"""

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

import ato_netlist
from lut import C_LOAD, NMOS_PARAMS, PMOS_PARAMS, VARIANTS, VDD
from ngspice import NgSpice
from vcd import VCD

HERE = Path(__file__).resolve().parent

T_STEP = 200e-9             # duration of one input combination
T_FUNC = 4 * T_STEP         # duration of one function (four combinations)
T_EDGE = 1e-9               # rise and fall time of all sources
T_WRITE = T_STEP / 2         # the table is rewritten this long after the start of a function
T_END = 16 * T_FUNC
GRAY = (0, 1, 3, 2)         # table index during the four steps of a function

# write sequence of the SRAM variant, within the first T_WRITE of a function
T_CYCLE = 22e-9             # one write cycle per cell
T_SETUP = 3e-9              # bit lines are set this long before the word line rises
T_PULSE = 14e-9             # width of the word-line pulse
T_FIRST = 6e-9              # start of the first write cycle
SRAM_NODES = {"bl": "bl", "bln": "bln", "wl0": "wl0", "wl1": "wl1", "wl2": "wl2", "wl3": "wl3"}

FUNCTIONS = ["0", "NOR", "A AND NOT B", "NOT B", "B AND NOT A", "NOT A", "XOR", "NAND",
             "AND", "XNOR", "A", "A OR NOT B", "B", "B OR NOT A", "OR", "1"]
# name used in the results -> node of the netlist; nets inside a sheet carry its name
NODES = {"a": "a", "b": "b", "t0": "t0", "t1": "t1", "t2": "t2", "t3": "t3",
         "n0": "n0", "n1": "n1", "yi": "yi", "yb": "buffer_mid", "y": "y"}


# ---------------------------------------------------------------------------
# Netlist from the schematic
# ---------------------------------------------------------------------------
class Netlist:
    def __init__(self, sch):
        if not shutil.which("kicad-cli"):
            raise RuntimeError("kicad-cli not found; it is needed to export the netlist")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "netlist.cir"
            subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "spice",
                            "-o", str(out), str(sch)], check=True, capture_output=True)
            raw = out.read_text().splitlines()
        lines = []
        for l in raw:                                   # join continuation lines
            if l.startswith("+"):
                lines[-1] += " " + l[1:].strip()
            elif l.strip():
                lines.append(l.rstrip())
        self.lines = []
        for l in lines:
            if l.lower().startswith((".title", ".end", ".tran", ".save", ".probe")):
                continue
            tok = l.split()
            n = {"M": 4, "V": 2, "C": 2, "R": 2}.get(tok[0][0])
            if n:
                tok[1:1 + n] = [self.net(t) for t in tok[1:1 + n]]
                l = " ".join(tok)
            self.lines.append(l)

    @classmethod
    def from_atopile(cls, variant):
        """
        Netlist from the atopile build: the transistors with their nets, plus
        a test bench of sources and load. atopile describes the circuit that
        would go onto a board; the sources are not part of it.
        """
        nl = object.__new__(cls)
        nl.lines = []
        for kind, polarity, params in (("NMOS4", "NMOS", NMOS_PARAMS),
                                       ("PMOS4", "PMOS", PMOS_PARAMS)):
            model = " ".join(p for p in params.split() if p[:2] not in ("w=", "l="))
            nl.lines.append(f".model {kind} {polarity} {model}")
        size = " ".join(p for p in NMOS_PARAMS.split() if p[:2] in ("w=", "l="))
        for p in ato_netlist.load(variant):
            nets = " ".join(cls.net({"hv": "+5V", "lv": "GND"}.get(p.pads[k], p.pads[k]))
                            for k in ("1", "2", "3", "4"))
            nl.lines.append(f"M{p.ref} {nets} {p.kind} {size}")
        bench = ["V1 vdd 0 DC %g" % VDD, "VA1 a 0 DC 0", "VB1 b 0 DC 0"]
        if variant == "sram":
            bench += ["VBL1 bl 0 DC 0", "VBLN1 bln 0 DC %g" % VDD]
            bench += [f"VWL{k} wl{k} 0 DC 0" for k in range(4)]
        else:
            bench += [f"VT{k} t{k} 0 DC 0" for k in range(4)]
        nl.lines += bench + [f"CL1 y 0 {C_LOAD}"]
        return nl

    @staticmethod
    def net(name):
        n = name.lstrip("/").lower().replace("/", "_").replace("-", "_")
        return {"gnd": "0", "0": "0", "+5v": "vdd"}.get(n, n)

    def set_source(self, positive_net, spec):
        """Replace the waveform of the voltage source that drives `positive_net`."""
        for i, l in enumerate(self.lines):
            tok = l.split()
            if tok[0][0] == "V" and tok[1] == positive_net:
                self.lines[i] = f"{tok[0]} {tok[1]} {tok[2]} {spec}"
                return tok[0]
        raise KeyError(positive_net)

    def render(self, title):
        return "\n".join([title] + self.lines + [".end"]) + "\n"


def pwl(points):
    return "PWL(" + " ".join(f"{t:.6g} {v:g}" for t, v in points) + ")"


def stimulus(nl, sram=False):
    """
    Inputs in Gray code, A = 0 1 1 0 and B = 0 0 1 1 in steps of T_STEP. The
    table bits step through all 16 functions; function f is written T_WRITE
    after the start of its window, while both inputs are 0.
    """
    nl.set_source("a", f"PULSE(0 {VDD:g} {T_STEP:g} {T_EDGE:g} {T_EDGE:g} "
                       f"{2 * T_STEP - T_EDGE:g} {4 * T_STEP:g})")
    nl.set_source("b", f"PULSE(0 {VDD:g} {2 * T_STEP:g} {T_EDGE:g} {T_EDGE:g} "
                       f"{2 * T_STEP - T_EDGE:g} {4 * T_STEP:g})")
    if sram:
        stimulus_sram(nl, range(16), T_FUNC, T_END)
        return
    for bit in range(4):
        pts, level = [(0, 0)], 0
        for f in range(1, 16):
            new = f >> bit & 1
            if new != level:
                tw = f * T_FUNC + T_WRITE
                pts += [(tw, VDD * level), (tw + T_EDGE, VDD * new)]
                level = new
        pts.append((T_END, VDD * level))
        nl.set_source(f"t{bit}", pwl(pts))


def stimulus_sram(nl, tables, t_func, t_end):
    """
    Write sequence for the SRAM cells. `tables` lists the functions; function
    number n is written at the start of its window n * t_func, cell by cell:
    bit lines to the value, word line high for T_PULSE, word line low.
    """
    e = T_EDGE
    bl, bln = [(0, 0)], [(0, VDD)]
    wl = [[(0, 0)] for _ in range(4)]
    level = 0
    for n, f in enumerate(tables):
        for k in range(4):
            t0 = n * t_func + T_FIRST + k * T_CYCLE
            new = f >> k & 1
            if new != level:
                bl += [(t0, VDD * level), (t0 + e, VDD * new)]
                bln += [(t0, VDD * (1 - level)), (t0 + e, VDD * (1 - new))]
                level = new
            tw = t0 + T_SETUP
            wl[k] += [(tw, 0), (tw + e, VDD), (tw + T_PULSE, VDD), (tw + T_PULSE + e, 0)]
    bl.append((t_end, VDD * level))
    bln.append((t_end, VDD * (1 - level)))
    nl.set_source("bl", pwl(bl))
    nl.set_source("bln", pwl(bln))
    for k in range(4):
        nl.set_source(f"wl{k}", pwl(wl[k] + [(t_end, 0)]))


T_GLITCH = 800e-9


def stimulus_glitch(nl, sram=False):
    """
    Both inputs change at the same instant, and the output should not move.

      0..400 ns    table 0110 (XOR):   index 1 -> 2 at 100 ns, 2 -> 1 at 300 ns
      400..800 ns  table 1001 (XNOR):  index 0 -> 3 at 500 ns, 3 -> 0 at 700 ns
    """
    e = T_EDGE
    nl.set_source("a", pwl([(0, VDD), (100e-9, VDD), (100e-9 + e, 0), (300e-9, 0),
                            (300e-9 + e, VDD), (400e-9, VDD), (400e-9 + e, 0),
                            (500e-9, 0), (500e-9 + e, VDD), (700e-9, VDD), (700e-9 + e, 0),
                            (T_GLITCH, 0)]))
    nl.set_source("b", pwl([(0, 0), (100e-9, 0), (100e-9 + e, VDD), (300e-9, VDD),
                            (300e-9 + e, 0), (500e-9, 0), (500e-9 + e, VDD),
                            (700e-9, VDD), (700e-9 + e, 0), (T_GLITCH, 0)]))
    if sram:
        stimulus_sram(nl, (0b0110, 0b1001), 400e-9, T_GLITCH)
        return
    for bit, (xor, xnor) in enumerate(((0, 1), (1, 0), (1, 0), (0, 1))):
        nl.set_source(f"t{bit}", pwl([(0, VDD * xor), (400e-9, VDD * xor),
                                      (400e-9 + e, VDD * xnor), (T_GLITCH, VDD * xnor)]))


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
def crossings(t, v, level):
    """Times at which v crosses `level`, and the direction (+1 rising, -1 falling)."""
    s = v > level
    idx = np.where(s[1:] != s[:-1])[0]
    tc = t[idx] + (level - v[idx]) * (t[idx + 1] - t[idx]) / (v[idx + 1] - v[idx])
    return tc, np.where(s[idx + 1], 1, -1)


def truth_tables(t, v):
    """Sample Y shortly before the end of every input combination."""
    errors, tables = [], []
    for f in range(16):
        got = 0
        for k, idx in enumerate(GRAY):
            ts = f * T_FUNC + (k + 1) * T_STEP - 5e-9
            y = np.interp(ts, t, v["y"]) > VDD / 2
            got |= int(y) << idx
            if int(y) != (f >> idx & 1):
                errors.append((f, idx))
        tables.append(got)
    return tables, errors


def delays(t, v, inp, skip_boundaries=False):
    """
    Propagation delays from edges of `inp` to the edge of Y that follows
    (50 % to 50 %). `inp` is "a", "b" or "table" (any of the four table bits).
    With skip_boundaries, input edges at the start of a function window are
    left out, because the memory is being written at that time.
    """
    if inp == "table":
        ti = np.arange(1, 16) * T_FUNC + T_WRITE + T_EDGE / 2
    else:
        ti, _ = crossings(t, v[inp], VDD / 2)
    ty, dy = crossings(t, v["y"], VDD / 2)
    rise, fall = [], []
    for e in ti:
        if skip_boundaries and (e + 5e-9) % T_FUNC < 10e-9:
            continue
        m = (ty > e) & (ty < e + 0.9 * T_WRITE)
        if m.any():
            j = np.argmax(m)
            (rise if dy[j] > 0 else fall).append(ty[j] - e)
    return np.array(rise), np.array(fall)


def analyse_memory(t, v):
    """
    SRAM cells: are the stored bits what was written, and how far are the
    storage nodes pushed away from the rails while the LUT is being used?
    Looked at outside the write phase, from T_WRITE to the end of a function.
    """
    wrong, low, high = 0, 0.0, VDD
    for f in range(16):
        m = (t > f * T_FUNC + T_WRITE) & (t < (f + 1) * T_FUNC)
        for k in range(4):
            x = v[f"t{k}"][m]
            if f >> k & 1:
                high = min(high, np.min(x))
                wrong += int(np.any(x < VDD / 2))
            else:
                low = max(low, np.max(x))
                wrong += int(np.any(x > VDD / 2))
    return dict(mem_wrong=wrong, mem_low=low, mem_high=high)


def analyse(t, v, i_supply, sram=False):
    tables, errors = truth_tables(t, v)
    high, low, quiet = [], [], []
    for f in range(16):
        for k, idx in enumerate(GRAY):
            ts = f * T_FUNC + (k + 1) * T_STEP - 5e-9
            (high if f >> idx & 1 else low).append(np.interp(ts, t, v["yi"]))
            m = (t > ts - 20e-9) & (t < ts)          # at rest: the last 20 ns of a step
            quiet.append(np.mean(-i_supply[m]))
    res = dict(tables=tables, errors=errors, yi_high=np.mean(high), yi_high_min=np.min(high),
               yi_low=np.max(low), y_high=np.interp(6 * T_FUNC + 2 * T_STEP - 5e-9, t, v["y"]),
               i_quiet=np.max(quiet), i_quiet_min=np.min(quiet))
    for inp in ("a", "b", "table"):
        res[f"{inp}_rise"], res[f"{inp}_fall"] = delays(t, v, inp, sram)
    return res


def analyse_glitch(t, v):
    """Depth of the dip of Y (it should stay at 1) around the four input changes."""
    out = []
    for te, label in ((100e-9, "XOR, index 1 to 2"), (300e-9, "XOR, index 2 to 1"),
                      (500e-9, "XNOR, index 0 to 3"), (700e-9, "XNOR, index 3 to 0")):
        m = (t > te) & (t < te + 90e-9)
        ty, _ = crossings(t[m], v["y"][m], VDD / 2)
        width = ty[1] - ty[0] if len(ty) >= 2 else 0.0
        out.append(dict(label=label, y_min=np.min(v["y"][m]), yi_min=np.min(v["yi"][m]),
                        width=width))
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def write_vcd(path, t, v, variant, t_end=T_END):
    sram = "wl0" in v
    vcd = VCD("1ps", scope=f"lut2_{variant}",
              comment="logic values (threshold VDD/2) and node voltages from ngspice")
    names = ("a", "b", "y") + (("bl", "wl0", "wl1", "wl2", "wl3") if sram else ())
    wires = {n: vcd.wire(n) for n in names}
    table = vcd.wire("table", 4)
    index = vcd.wire("index", 2)
    analog = ("a", "b", "n0", "n1", "yi", "yb", "y") + (("t0", "t1", "t2", "t3") if sram else ())
    reals = {n: vcd.real(f"v_{n}") for n in analog}
    bits = {n: v[n] > VDD / 2 for n in names + ("t0", "t1", "t2", "t3")}
    last = {n: None for n in reals}
    for i, ti in enumerate(t):
        for n, w in wires.items():
            vcd.change(w, ti, int(bits[n][i]))
        vcd.change(table, ti, sum(int(bits[f"t{k}"][i]) << k for k in range(4)))
        vcd.change(index, ti, 2 * int(bits["b"][i]) + int(bits["a"][i]))
        for n, r in reals.items():
            x = float(v[n][i])
            if last[n] is None or abs(x - last[n]) > 2e-3 or i == len(t) - 1:
                vcd.change(r, ti, round(x, 4))
                last[n] = x
    vcd.write(path, end_time=t_end)


def write_gtkw(path, vcd_name, variant, zoom=-23.5, sram=False):
    """GTKWave save file: logic signals on top, node voltages as analog traces below."""
    scope = f"lut2_{variant}"
    out = ["[*] GTKWave save file written by simulate.py",
           f'[dumpfile] "{vcd_name}"',
           "[timestart] 0", "[size] 1700 950", "[pos] -1 -1",
           f"*{zoom:g} 0 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1",
           "[sst_width] 220", "[signals_width] 170", "[sst_expanded] 1", "[sst_vpaned_height] 280",
           "@200", "-Configuration",
           "@22", f"{scope}.table[3:0]"]
    if sram:
        out += ["@28", f"{scope}.bl"] + [f"{scope}.wl{k}" for k in range(4)]
    out += [
           "@200", "-Inputs",
           "@28", f"{scope}.a", f"{scope}.b",
           "@24", f"{scope}.index[1:0]",
           "@200", "-Output",
           "@28", f"{scope}.y",
           "@200", "-Node voltages"]
    cells = ("v_t0", "v_t1", "v_t2", "v_t3") if sram else ()
    for n in cells + ("v_a", "v_b", "v_n0", "v_n1", "v_yi", "v_yb", "v_y"):
        # 0x90022: analog interpolated, full scale, right justified; then room for the trace
        out += ["@90022", f"{scope}.{n}", "@20000", "-", "-"]
    out += ["[pattern_trace] 1", "[pattern_trace] 0"]
    path.write_text("\n".join(out) + "\n")


def plot(path, t, v, variant):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    f0 = 6                                      # XOR
    m = (t >= f0 * T_FUNC - 20e-9) & (t <= (f0 + 1) * T_FUNC + 20e-9)
    tn = (t[m] - f0 * T_FUNC) * 1e9
    sram = "wl0" in v
    fig, ax = plt.subplots(4 if sram else 3, 1, figsize=(8, 8.4 if sram else 6.4), sharex=True)
    titles = ("Inputs", "Inside the multiplexer tree", "Output")
    if sram:
        c4 = ("#2a78d6", "#eda100", "#1baf7a", "#8a5cd6")
        for k in range(4):
            ax[0].plot(tn, v[f"t{k}"][m], color=c4[k], label=f"T{k}")
            ax[0].plot(tn, v[f"wl{k}"][m], color=c4[k], lw=0.8, ls=":")
        ax[0].plot(tn, v["bl"][m], color="#52514e", lw=0.8, ls="--", label="BL")
        titles = ("Memory: cell outputs T0..T3, word lines (dotted), bit line (dashed)",) + titles
        ax = list(ax)
        first, ax = ax[0], ax[1:]
    ax[0].plot(tn, v["a"][m], color="#2a78d6", label="A")
    ax[0].plot(tn, v["b"][m], color="#eda100", label="B")
    ax[1].plot(tn, v["n0"][m], color="#1baf7a", lw=1.2, label="N0")
    ax[1].plot(tn, v["n1"][m], color="#8a5cd6", lw=1.2, label="N1")
    ax[1].plot(tn, v["yi"][m], color="#eb6834", label="YI (before the buffer)")
    ax[2].plot(tn, v["y"][m], color="#eb6834", label="Y")
    if sram:
        ax = [first] + ax
    for a, title in zip(ax, titles):
        a.set_title(title, loc="left", fontsize=10, fontweight="bold")
        a.set_ylabel("Voltage [V]"); a.set_ylim(-0.6, VDD + 0.9)
        a.grid(True, color="#d9d8d3", linewidth=0.6)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        a.legend(frameon=False, loc="upper right", ncol=3, fontsize=8)
    ax[-1].set_xlabel("Time [ns]")
    kind = {"tgate": "transmission gates", "pass": "NMOS pass transistors",
            "sram": "transmission gates and SRAM cells"}[variant]
    fig.suptitle(f"LUT configured as XOR (table 0110), {kind}", fontsize=11, fontweight="bold", x=0.02, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def ns(x):
    return "none observed" if len(x) == 0 else f"{np.mean(x) * 1e9:.1f} ns ({len(x)} edges)"


def run(ng, nl, name, t_end, sram=False):
    ng.command("destroy all")
    ng.load_netlist(nl.render(name))
    ng.run(f"tran 0.2n {t_end:g} 0 0.2n")
    nodes = dict(NODES, **SRAM_NODES) if sram else NODES
    return (ng.vector("time"), {n: ng.vector(f"v({node})") for n, node in nodes.items()},
            ng.vector("i(v1)"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("kicad", "atopile"), default="kicad")
    ap.add_argument("--results", type=Path, default=None)
    args = ap.parse_args()
    if args.results is None:
        args.results = HERE / "results" / ("atopile" if args.source == "atopile" else "")
    args.results.mkdir(parents=True, exist_ok=True)
    ng = NgSpice()
    results, glitch = {}, {}

    for variant in VARIANTS:
        name = f"lut2_{variant}"
        sram = variant == "sram"
        if args.source == "atopile":
            nl = Netlist.from_atopile(variant)
        else:
            nl = Netlist(HERE / variant / "lut2.kicad_sch")
        stimulus(nl, sram)
        (args.results / f"{name}.cir").write_text(nl.render(f"LUT with two inputs, {variant}"))
        t, v, i_supply = run(ng, nl, name, T_END, sram)
        keep = np.r_[True, np.diff(t) > 0]
        np.savetxt(args.results / f"{name}.csv", np.column_stack([t] + list(v.values()))[keep],
                   delimiter=",", header="t," + ",".join(v), comments="", fmt="%.6g")
        write_vcd(args.results / f"{name}.vcd", t, v, variant)
        write_gtkw(args.results / f"{name}.gtkw", f"{name}.vcd", variant, sram=sram)
        results[variant] = analyse(t, v, i_supply, sram)
        if sram:
            results[variant].update(analyse_memory(t, v))
            results[variant]["table_rise"] = results[variant]["table_fall"] = np.array([])
        plot(args.results / f"{name}.png", t, v, variant)
        print(f"{name}: {len(t)} time points, truth table errors: {len(results[variant]['errors'])}")

        stimulus_glitch(nl, sram)
        t, v, _ = run(ng, nl, name + "_glitch", T_GLITCH, sram)
        write_vcd(args.results / f"{name}_glitch.vcd", t, v, variant, T_GLITCH)
        write_gtkw(args.results / f"{name}_glitch.gtkw", f"{name}_glitch.vcd", variant,
                   zoom=-19.5, sram=sram)
        glitch[variant] = analyse_glitch(t, v)

    names = {"tgate": "Transmission gates", "pass": "Pass transistors", "sram": "SRAM cells"}
    head = " | ".join(names[x] for x in VARIANTS)
    sep = "|".join("---" for _ in range(len(VARIANTS) + 1))
    origin = {"kicad": "the KiCad schematics generated from lut.py",
              "atopile": "the board files of the atopile build"}[args.source]
    out = ["# LUT with two inputs: simulation results", "",
           f"Netlist taken from {origin}.", "",
           "One transient run per variant covers all 16 functions. The inputs step through",
           "the four combinations in Gray code (index 0, 1, 3, 2) in steps of 200 ns. The",
           "table is rewritten every 800 ns, while the inputs are 00: in the variants",
           "`tgate` and `pass` the sources change 100 ns after the start of the window, in",
           "the variant `sram` four write cycles fill the first 100 ns.", "",
           "## Truth tables", "",
           "The output Y is sampled 5 ns before the end of every input combination.",
           "The table is written as T3 T2 T1 T0, the index is 2 B + A.", "",
           f"| Table | Function | {head} |", f"|---|{sep}|"]
    for f in range(16):
        cells = []
        for variant in VARIANTS:
            got = results[variant]["tables"][f]
            cells.append(f"{got:04b} " + ("ok" if got == f else "WRONG"))
        out.append(f"| {f:04b} | {FUNCTIONS[f]} | " + " | ".join(cells) + " |")
    out += ["", "## Measurements", "", f"| Quantity | {head} |", f"|{sep}|"]
    rows = [("Wrong entries out of 64", lambda x: str(len(x["errors"]))),
            ("Level of YI for a 1, mean", lambda x: f"{x['yi_high']:.3f} V"),
            ("Level of YI for a 1, lowest", lambda x: f"{x['yi_high_min']:.3f} V"),
            ("Level of YI for a 0, highest", lambda x: f"{x['yi_low'] * 1e3:.1f} mV"),
            ("Level of Y for a 1", lambda x: f"{x['y_high']:.3f} V"),
            ("Supply current at rest, smallest", lambda x: f"{x['i_quiet_min'] * 1e6:.3g} µA"),
            ("Supply current at rest, largest", lambda x: f"{x['i_quiet'] * 1e6:.3g} µA"),
            ("Delay A to Y, rising", lambda x: ns(x["a_rise"])),
            ("Delay A to Y, falling", lambda x: ns(x["a_fall"])),
            ("Delay B to Y, rising", lambda x: ns(x["b_rise"])),
            ("Delay B to Y, falling", lambda x: ns(x["b_fall"])),
            ("Delay table bit to Y, rising",
             lambda x: "not measured" if "mem_wrong" in x else ns(x["table_rise"])),
            ("Delay table bit to Y, falling",
             lambda x: "not measured" if "mem_wrong" in x else ns(x["table_fall"]))]
    for label, fn in rows:
        out.append(f"| {label} | " + " | ".join(fn(results[x]) for x in VARIANTS) + " |")
    if "sram" in results:
        r = results["sram"]
        out += ["", "## Memory", "",
                "Storage nodes T0..T3 of the SRAM cells, looked at after the write phase, while",
                "the LUT is in use. A cell counts as disturbed if its node crosses half the supply.", "",
                "| Quantity | Value |", "|---|---|",
                f"| Cells disturbed, out of 64 (16 functions, 4 cells) | {r['mem_wrong']} |",
                f"| Lowest level of a node that stores a 1 | {r['mem_high']:.3f} V |",
                f"| Highest level of a node that stores a 0 | {r['mem_low'] * 1e3:.1f} mV |"]
    out += ["", "## Glitches", "",
            "Both inputs change within 1 ns; the old and the new table entry are both 1, so",
            "Y should stay at 1. Lowest voltage of YI and Y in the 90 ns after the change,",
            "and the width of the pulse if Y crosses half the supply.", "",
            "| Change | Variant | lowest YI | lowest Y | Glitch at Y |", "|---|---|---|---|---|"]
    for variant in VARIANTS:
        for g in glitch[variant]:
            w = f"{g['width'] * 1e9:.1f} ns" if g["width"] else "none"
            out.append(f"| {g['label']} | {variant} | {g['yi_min']:.2f} V | {g['y_min']:.2f} V | {w} |")
    out.append("")
    (args.results / "summary.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
