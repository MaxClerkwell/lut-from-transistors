# The same LUT in atopile

The look-up table of this repository, described a second time in
[atopile](https://atopile.io) instead of Python and SKiDL.

| File | Content |
|---|---|
| `parts/MOS4/MOS4.ato` | the two transistors, NMOS4 and PMOS4, with four terminals |
| `blocks.ato` | `Inverter`, `SwitchTgate`, `SwitchPass`, `Mux2Tgate`, `Mux2Pass`, `Buffer`, `SramCell` |
| `lut2.ato` | the three variants `Lut2Tgate`, `Lut2Pass`, `Lut2Sram` |
| `ato.yaml` | one build per variant |
| `layouts/<variant>/<variant>.kicad_pcb` | result of the build: footprints and nets |

Modules, instances and ports have the same names as the sheets generated
from `lut.py`. An inverter in atopile:

```
module Inverter:
    power = new ElectricPower
    signal IN
    signal OUT

    qp = new PMOS4
    qn = new NMOS4

    qp.G ~ IN
    qn.G ~ IN
    qp.D ~ OUT
    qn.D ~ OUT
    qp.S ~ power.hv
    qp.B ~ power.hv
    qn.S ~ power.lv
    qn.B ~ power.lv
```

`Lut2Sram` is derived from `Lut2Tgate` and adds the four memory cells.

## What atopile produces, and what it does not

atopile is a tool for designing boards. It compiles the description into a
KiCad board file with one footprint per component and the net of every pad.

| Output | atopile | This repository |
|---|---|---|
| netlist | yes, inside the board file | read back by `ato_netlist.py` |
| board with footprints | yes | not used; the transistors are generic |
| schematic | no | drawn by `hier.py` from `lut.py` |
| SPICE netlist | no | written by `simulate.py --source atopile` |
| sources, test bench | not part of a board | added by `simulate.py` |

So atopile replaces SKiDL as the description of the circuit, but not the
rest of the chain. The schematics still come from `lut.py`, because only
that description contains the placement of the symbols.

## Verification

```sh
uv run verify_atopile.py                 # from the repository root
uv run simulate.py --source atopile
```

`verify_atopile.py` compares the atopile build with the design in `lut.py`:
the same transistors, of the same type, at the same place in the hierarchy,
and every net connecting the same pins. References differ between the two,
so parts are identified by their address, such as `mux_n0.sw0.qn`.

| Variant | Transistors | Nets | Parts | Connectivity |
|---|---|---|---|---|
| `tgate` | 20 | 15 | identical | identical |
| `pass` | 14 | 11 | identical | identical |
| `sram` | 44 | 25 | identical | identical |

The simulation from the atopile netlist gives the same numbers as the
simulation from the KiCad schematic, digit by digit
(`results/atopile/summary.md` and `results/summary.md`).

## Building

The board files are committed, so verification and simulation work without
atopile. To rebuild:

```sh
ATO=/path/to/ato ./build.sh
```

Built with atopile 0.15.8 on Python 3.14.

## Things to know about atopile

- **The command line is at the end of its life.** Version 0.15.8 is the
  last release of the classic command line and in maintenance mode. From
  0.16 on atopile is an application at app.atopile.io. This project uses
  the command line only, locally.
- **atopile changes the KiCad configuration.** On every start it writes a
  plugin loader into KiCad's scripting directory and enables the KiCad API
  server in `kicad_common.json`. `build.sh` prevents this by giving atopile
  a home directory of its own.
- **Every component has to be a purchasable part.** A component needs a
  footprint and a supplier part number, and LCSC is the only supplier
  atopile accepts. The generic transistors of this design therefore carry
  a SOT-143 footprint and the placeholder `PLACEHOLDER-NMOS4` as part
  number. This is not a real LCSC number and nothing can be ordered with
  it. `build.sh` runs without network access, so nothing is looked up.
- **Net names** are chosen by atopile unless they are set. `lut2.ato` sets
  them for the signals of the top level with `override_net_name`. For the
  supply this had no effect; the nets are called `hv` and `lv`.
- **The footprint** `SOT-143.kicad_mod` is a copy from the KiCad footprint
  library, which is licensed CC BY-SA 4.0 with an exception for use in
  designs.
