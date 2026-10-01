#!/usr/bin/env python3
"""Regenerate all figures for the transistor-lut paper.

Usage:
    python3 scripts/make_figures.py            # build all figures
    python3 scripts/make_figures.py fig_xor    # build a single figure

Reads the model parameters from lut.py and the simulation results from
results/ (run `uv run simulate.py` first). Output: paper/figures/<name>.pdf.
The schematic sheets are converted separately from docs/sheets/*.svg by
scripts/make_schematics.sh (inkscape and pdfcrop).
"""
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle, Polygon, Circle

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from lut import VDD, NMOS_PARAMS, PMOS_PARAMS  # noqa: E402

OUT = HERE / "paper" / "figures"
RESULTS = HERE / "results"
OUT.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.constrained_layout.use": True,
})

C_A = "#1a6faf"       # input A, NMOS
C_B = "#c23b22"       # input B, PMOS
C_N0 = "#2e8b57"
C_N1 = "#8a5cd6"
C_Y = "#e07b1a"
C_GREY = "#555555"


def params(s):
    """SPICE parameter string -> dict of floats (SI units)."""
    scale = {"u": 1e-6, "n": 1e-9, "p": 1e-12, "m": 1e-3, "k": 1e3}
    out = {}
    for k, v, suf in re.findall(r"(\w+)=(-?[\d.]+(?:[eE][+-]?\d+)?)([a-zA-Z]?)", s):
        out[k] = float(v) * (scale[suf] if suf else 1.0)
    return out


NM = params(NMOS_PARAMS)
PM = params(PMOS_PARAMS)


def _save(fig, name):
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)
    print(f"  wrote {name}.pdf")


# ---------------------------------------------------------------------------
# Level-1 MOS model, as ngspice evaluates it (lambda neglected where noted)
# ---------------------------------------------------------------------------
def vth_n(vsb):
    """Threshold of the NMOS with body effect: VT0 + gamma (sqrt(phi+VSB) - sqrt(phi))."""
    return NM["vto"] + NM["gamma"] * (np.sqrt(NM["phi"] + vsb) - np.sqrt(NM["phi"]))


def ids_n(vgs, vds):
    vt = NM["vto"]
    k = NM["kp"] * NM["w"] / NM["l"]
    vgs, vds = np.asarray(vgs, float), np.asarray(vds, float)
    sat = k / 2 * np.clip(vgs - vt, 0, None) ** 2
    lin = k * ((vgs - vt) * vds - vds ** 2 / 2)
    return np.where(vgs <= vt, 0.0, np.where(vds >= vgs - vt, sat, lin))


def ids_p(vsg, vsd):
    vt = -PM["vto"]
    k = PM["kp"] * PM["w"] / PM["l"]
    vsg, vsd = np.asarray(vsg, float), np.asarray(vsd, float)
    sat = k / 2 * np.clip(vsg - vt, 0, None) ** 2
    lin = k * ((vsg - vt) * vsd - vsd ** 2 / 2)
    return np.where(vsg <= vt, 0.0, np.where(vsd >= vsg - vt, sat, lin))


def pass_level():
    """Highest voltage an NMOS with its gate at VDD can pass: V = VDD - VT(V)."""
    v = 0.0
    for _ in range(100):
        v = VDD - vth_n(v)
    return v


def inverter_vtc(n=2001):
    """Static transfer curve of the inverter: V_out(V_in) from I_n = I_p."""
    vin = np.linspace(0, VDD, n)
    vout = np.empty_like(vin)
    grid = np.linspace(0, VDD, 4001)
    for i, vi in enumerate(vin):
        diff = ids_n(vi, grid) - ids_p(VDD - vi, VDD - grid)
        # the output is where the NMOS current equals the PMOS current
        j = np.argmin(np.abs(diff))
        vout[i] = grid[j]
    return vin, vout


def switching_threshold():
    vin, vout = inverter_vtc()
    j = np.argmin(np.abs(vout - vin))
    return vin[j]


# ---------------------------------------------------------------------------
# Data from the simulation
# ---------------------------------------------------------------------------
def load_csv():
    path = RESULTS / "lut2.csv"
    if not path.exists():
        raise SystemExit("results/lut2.csv not found; run `uv run simulate.py` first")
    data = np.genfromtxt(path, delimiter=",", names=True)
    return data


def load_vcd_reals(path):
    """Read the real-valued signals of a VCD written by vcd.py."""
    text = Path(path).read_text().splitlines()
    ids, names = {}, {}
    i = 0
    while not text[i].startswith("$enddefinitions"):
        m = re.match(r"\$var real \d+ (\S+) (\S+) \$end", text[i])
        if m:
            ids[m.group(1)] = m.group(2)
        i += 1
    series = {n: ([], []) for n in ids.values()}
    t = 0
    for line in text[i + 1:]:
        if line.startswith("#"):
            t = int(line[1:]) * 1e-12
        elif line.startswith("r"):
            val, code = line[1:].split()
            if code in ids:
                series[ids[code]][0].append(t)
                series[ids[code]][1].append(float(val))
    return {n: (np.array(a), np.array(b)) for n, (a, b) in series.items()}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def fig_truth_tables():
    """The 16 functions of two inputs as 4-bit patterns."""
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.set_axis_off()
    names = ["0", "NOR", "A·B̄", "B̄", "Ā·B", "Ā", "XOR", "NAND",
             "AND", "XNOR", "A", "A+B̄", "B", "Ā+B", "OR", "1"]
    for f in range(16):
        x0 = f * 0.9
        for idx in range(4):
            bit = f >> idx & 1
            y0 = 3 - idx
            ax.add_patch(Rectangle((x0, y0), 0.8, 0.9, facecolor=C_A if bit else "white",
                                   edgecolor=C_GREY, lw=0.8))
            ax.text(x0 + 0.4, y0 + 0.45, str(bit), ha="center", va="center",
                    color="white" if bit else C_GREY, fontsize=9)
        ax.text(x0 + 0.4, 4.15, f"{f:04b}", ha="center", va="bottom", fontsize=7.5,
                family="monospace")
        ax.text(x0 + 0.4, -0.25, names[f], ha="center", va="top", fontsize=7.5)
    for idx, lab in enumerate(["T0 (A=0,B=0)", "T1 (A=1,B=0)", "T2 (A=0,B=1)", "T3 (A=1,B=1)"]):
        ax.text(-0.2, 3 - idx + 0.45, lab, ha="right", va="center", fontsize=8)
    ax.set_xlim(-2.6, 16 * 0.9)
    ax.set_ylim(-0.9, 4.9)
    _save(fig, "fig_truth_tables")


def fig_mux_tree():
    """The multiplexer tree of the LUT, drawn as blocks."""
    fig, ax = plt.subplots(figsize=(7.4, 3.6))
    ax.set_axis_off()

    def mux(x, y, sel, color):
        ax.add_patch(Polygon([(x, y - 1.0), (x, y + 1.0), (x + 1.2, y + 0.5), (x + 1.2, y - 0.5)],
                             closed=True, facecolor="white", edgecolor="black", lw=1.2))
        ax.text(x + 0.25, y + 0.45, "0", fontsize=8, va="center")
        ax.text(x + 0.25, y - 0.45, "1", fontsize=8, va="center")
        ax.annotate("", xy=(x + 0.6, y - 0.75), xytext=(x + 0.6, y - 1.6),
                    arrowprops=dict(arrowstyle="-", color=color, lw=1.4))
        ax.text(x + 0.6, y - 1.75, sel, ha="center", va="top", color=color, fontsize=10,
                fontweight="bold")

    def wire(x0, y0, x1, y1, label=None, color="black"):
        ax.plot([x0, x1], [y0, y1], color=color, lw=1.2)
        if label:
            ax.text(x0 - 0.15, y0, label, ha="right", va="center", fontsize=10)

    # first level
    for k, (yc, ins) in enumerate(((3.0, ("T0", "T1")), (-0.5, ("T2", "T3")))):
        mux(1.5, yc, "A", C_A)
        wire(0.2, yc + 0.45, 1.5, yc + 0.45, ins[0])
        wire(0.2, yc - 0.45, 1.5, yc - 0.45, ins[1])
    # second level
    mux(4.5, 1.25, "B", C_B)
    wire(2.7, 3.0, 3.6, 3.0, color=C_N0); wire(3.6, 3.0, 3.6, 1.7, color=C_N0)
    wire(3.6, 1.7, 4.5, 1.7, color=C_N0)
    wire(2.7, -0.5, 3.6, -0.5, color=C_N1); wire(3.6, -0.5, 3.6, 0.8, color=C_N1)
    wire(3.6, 0.8, 4.5, 0.8, color=C_N1)
    ax.text(3.1, 3.15, "N0", color=C_N0, fontsize=9, ha="center", va="bottom")
    ax.text(3.1, -0.65, "N1", color=C_N1, fontsize=9, ha="center", va="top")
    # buffer
    wire(5.7, 1.25, 6.4, 1.25, color=C_Y)
    ax.text(6.05, 1.4, "YI", color=C_Y, fontsize=9, ha="center", va="bottom")
    for x in (6.4, 7.6):
        ax.add_patch(Polygon([(x, 0.75), (x, 1.75), (x + 0.9, 1.25)], closed=True,
                             facecolor="white", edgecolor="black", lw=1.2))
        ax.add_patch(Circle((x + 1.0, 1.25), 0.1, facecolor="white", edgecolor="black", lw=1.2))
        wire(x + 1.1, 1.25, x + 1.2, 1.25)
    wire(8.8, 1.25, 9.6, 1.25, color=C_Y)
    ax.text(9.75, 1.25, "Y", fontsize=11, va="center", fontweight="bold")
    ax.text(0.2, 4.6, "table bits\n(configuration)", fontsize=9, va="top")
    ax.text(1.6, 4.6, "level 1: selected by A", fontsize=9, va="top", color=C_A)
    ax.text(4.5, 4.6, "level 2: selected by B", fontsize=9, va="top", color=C_B)
    ax.text(7.3, 4.6, "buffer", fontsize=9, va="top")
    ax.set_xlim(-0.6, 10.3)
    ax.set_ylim(-2.4, 4.8)
    _save(fig, "fig_mux_tree")


def fig_pass_level():
    """Why an NMOS alone cannot pass a 1: the threshold rises with the source voltage."""
    v = np.linspace(0, VDD, 400)
    vt = vth_n(v)
    vmax = pass_level()
    fig, ax = plt.subplots(1, 2, figsize=(7.4, 3.0))
    ax[0].plot(v, vt, color=C_A, lw=2)
    ax[0].axhline(NM["vto"], color=C_GREY, lw=0.8, ls="--")
    ax[0].text(0.1, NM["vto"] + 0.04, r"$V_{T0}$", color=C_GREY, va="bottom")
    ax[0].set_xlabel(r"source-to-bulk voltage $V_{SB}$ [V]")
    ax[0].set_ylabel(r"threshold $V_T$ [V]")
    ax[0].set_title("Body effect", loc="left", fontsize=10, fontweight="bold")

    ax[1].plot(v, VDD - vt, color=C_A, lw=2, label=r"$V_{DD}-V_T(V)$")
    ax[1].plot(v, v, color=C_GREY, lw=1, ls="--", label=r"$V$")
    ax[1].plot([vmax], [vmax], "o", color=C_B)
    ax[1].annotate(f"{vmax:.2f} V", xy=(vmax, vmax), xytext=(1.2, 4.3), color=C_B,
                   arrowprops=dict(arrowstyle="->", color=C_B))
    ax[1].set_xlabel("output voltage $V$ [V]")
    ax[1].set_ylabel("[V]")
    ax[1].set_title("Highest level an NMOS passes", loc="left", fontsize=10, fontweight="bold")
    ax[1].legend(frameon=False, loc="lower right")
    _save(fig, "fig_pass_level")


def fig_inverter_vtc():
    """Static transfer curve of the CMOS inverter and its supply current."""
    vin, vout = inverter_vtc()
    vm = switching_threshold()
    i = ids_n(vin, vout)
    fig, ax = plt.subplots(1, 2, figsize=(7.4, 3.0))
    ax[0].plot(vin, vout, color=C_A, lw=2)
    ax[0].plot(vin, vin, color=C_GREY, lw=0.8, ls="--")
    ax[0].plot([vm], [vm], "o", color=C_B)
    ax[0].annotate(f"$V_M$ = {vm:.2f} V", xy=(vm, vm), xytext=(2.9, 3.6), color=C_B,
                   arrowprops=dict(arrowstyle="->", color=C_B))
    ax[0].set_xlabel(r"$V_{in}$ [V]"); ax[0].set_ylabel(r"$V_{out}$ [V]")
    ax[0].set_title("Transfer curve", loc="left", fontsize=10, fontweight="bold")
    ax[1].plot(vin, i * 1e3, color=C_Y, lw=2)
    ax[1].set_xlabel(r"$V_{in}$ [V]"); ax[1].set_ylabel("supply current [mA]")
    ax[1].set_title("Current through both transistors", loc="left", fontsize=10,
                    fontweight="bold")
    _save(fig, "fig_inverter_vtc")


def fig_xor():
    """One function window of the simulation: the LUT configured as XOR."""
    d = load_csv()
    t_func, f0 = 800e-9, 6
    m = (d["t"] >= f0 * t_func - 20e-9) & (d["t"] <= (f0 + 1) * t_func + 20e-9)
    tn = (d["t"][m] - f0 * t_func) * 1e9
    fig, ax = plt.subplots(4, 1, figsize=(7.4, 7.0), sharex=True)
    for k, c in zip(range(4), (C_GREY, C_A, C_B, C_Y)):
        ax[0].plot(tn, d[f"t{k}"][m] + k * 0.15, color=c, lw=1.2, label=f"T{k}")
    ax[1].plot(tn, d["a"][m], color=C_A, label="A")
    ax[1].plot(tn, d["b"][m], color=C_B, label="B")
    ax[2].plot(tn, d["n0"][m], color=C_N0, lw=1.2, label="N0")
    ax[2].plot(tn, d["n1"][m], color=C_N1, lw=1.2, label="N1")
    ax[2].plot(tn, d["yi"][m], color=C_Y, label="YI")
    ax[3].plot(tn, d["y"][m], color=C_Y, label="Y")
    titles = ("Configuration: table bits (offset for visibility)", "Inputs",
              "Inside the multiplexer tree", "Output")
    for a, title in zip(ax, titles):
        a.set_title(title, loc="left", fontsize=10, fontweight="bold")
        a.set_ylabel("[V]"); a.set_ylim(-0.6, VDD + 1.0)
        a.grid(True, color="#d9d8d3", linewidth=0.6)
        a.legend(frameon=False, loc="upper right", ncol=4, fontsize=8)
    for a in ax:
        for x in (100, 200, 400, 600):
            a.axvline(x, color="#bbbbbb", lw=0.6, ls=":")
    ax[-1].set_xlabel("time within the function window [ns]")
    _save(fig, "fig_xor")


def fig_delay():
    """Zoom on one edge: A rises, N0 and YI follow, the buffer restores Y."""
    d = load_csv()
    t0 = 6 * 800e-9 + 200e-9                   # XOR window, A rises at 200 ns
    m = (d["t"] >= t0 - 3e-9) & (d["t"] <= t0 + 40e-9)
    tn = (d["t"][m] - t0) * 1e9
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    ax.plot(tn, d["a"][m], color=C_A, label="A")
    ax.plot(tn, d["n0"][m], color=C_N0, lw=1.2, label="N0")
    ax.plot(tn, d["yi"][m], color=C_Y, lw=1.2, ls="--", label="YI")
    ax.plot(tn, d["yb"][m], color=C_GREY, lw=1.0, label="YB (after inverter 1)")
    ax.plot(tn, d["y"][m], color=C_Y, lw=2, label="Y")
    ax.axhline(VDD / 2, color="#bbbbbb", lw=0.8, ls=":")
    ax.set_xlabel("time after the edge of A [ns]"); ax.set_ylabel("[V]")
    ax.legend(frameon=False, loc="center right", fontsize=9)
    ax.set_title("XOR, index 0 to 1: the table entry 1 travels to the output", loc="left",
                 fontsize=10, fontweight="bold")
    _save(fig, "fig_delay")


def fig_glitch():
    """The glitch experiment: both inputs change at once."""
    s = load_vcd_reals(RESULTS / "lut2_glitch.vcd")
    fig, ax = plt.subplots(2, 1, figsize=(7.4, 4.6), sharex=True)
    for name, c, lab in (("v_a", C_A, "A"), ("v_b", C_B, "B")):
        t, v = s[name]
        ax[0].step(t * 1e9, v, where="post", color=c, label=lab)
    for name, c, lab, lw in (("v_n0", C_N0, "N0", 1.0), ("v_n1", C_N1, "N1", 1.0),
                             ("v_yi", C_Y, "YI", 1.2), ("v_y", "black", "Y", 2)):
        t, v = s[name]
        ax[1].plot(t * 1e9, v, color=c, lw=lw, label=lab)
    ax[1].axhline(VDD / 2, color="#bbbbbb", lw=0.8, ls=":")
    ax[0].set_title("Inputs: A and B change within 1 ns", loc="left", fontsize=10,
                    fontweight="bold")
    ax[1].set_title("Tree and output: the table entry is 1 before and after", loc="left",
                    fontsize=10, fontweight="bold")
    for a in ax:
        a.set_ylabel("[V]"); a.set_ylim(-0.6, VDD + 1.0)
        a.legend(frameon=False, loc="upper right", ncol=4, fontsize=8)
        a.grid(True, color="#d9d8d3", linewidth=0.6)
    ax[0].text(50, 5.6, "table 0110 (XOR)", fontsize=8, color=C_GREY)
    ax[0].text(450, 5.6, "table 1001 (XNOR)", fontsize=8, color=C_GREY)
    ax[-1].set_xlabel("time [ns]")
    _save(fig, "fig_glitch")


FIGURES = {
    "fig_truth_tables": fig_truth_tables,
    "fig_mux_tree": fig_mux_tree,
    "fig_pass_level": fig_pass_level,
    "fig_inverter_vtc": fig_inverter_vtc,
    "fig_xor": fig_xor,
    "fig_delay": fig_delay,
    "fig_glitch": fig_glitch,
}


def main():
    wanted = sys.argv[1:] or list(FIGURES)
    print(f"NMOS pass level: {pass_level():.3f} V, inverter threshold: "
          f"{switching_threshold():.3f} V")
    for name in wanted:
        FIGURES[name]()


if __name__ == "__main__":
    main()
