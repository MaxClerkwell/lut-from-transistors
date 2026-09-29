"""
Hierarchical circuits: one description, a SKiDL netlist and KiCad sheets.

A `Block` describes one schematic sheet: its parts, its wires, its ports
(hierarchical labels) and the sub-sheets it contains. A block can be used
many times; `Design` walks the hierarchy from the root, and for every use
of a block it

  * creates the parts and nets in a flat SKiDL circuit, and
  * records under which sheet path each symbol got which reference,

and then writes every block as one `.kicad_sch` file. KiCad stores the
references of a reused sheet per instance path, so a sheet that is used
six times is drawn once and annotated six times.
"""

import os
import uuid

os.environ.setdefault("KICAD10_SYMBOL_DIR", "/usr/share/kicad/symbols")

from pathlib import Path

from skidl import KICAD10, POWER, Circuit, Net, Part, set_default_tool

from kicad_sch import (Placement, _prop, dump, find_all, junction, label, lib_symbol,
                       pin_offsets, q, text, unq, wire)

set_default_tool(KICAD10)

U = 2.54                                    # schematic grid unit [mm]
POWER_NETS = ("GND", "+5V")


def new_uuid():
    return str(uuid.uuid4())


class Child:
    """One use of a block inside another block: a sheet symbol."""

    def __init__(self, block, name, at, size, left, right, connect):
        self.block, self.name, self.at, self.size = block, name, at, size
        self.connect = connect              # port of the child -> net of the parent
        self.uuid = new_uuid()
        x, y = at
        self.pins = {}
        for side, names, px, rot in (("left", left, x, 180), ("right", right, x + size[0], 0)):
            for i, n in enumerate(names):
                self.pins[n] = (round(px, 2), round(y + (i + 1) * 2 * U, 2), rot)

    def pin(self, name):
        return self.pins[name][:2]


class Block:
    """A schematic sheet."""

    def __init__(self, name, filename, title="", paper="A4"):
        self.name, self.filename, self.title, self.paper = name, filename, title, paper
        self.uuid = new_uuid()
        self.ports = {}                     # name -> (shape, position, rotation)
        self.parts = []                     # dicts, see part()
        self.children = []
        self.wires, self.junctions, self.labels, self.texts = [], [], [], []
        self.powers = []                    # (name, position, rotation)
        self.text_positions = {}

    # -- content -----------------------------------------------------------
    def part(self, lib, name, prefix, value, at, pins, rot=0, mirror=None, fields=None,
             ref_at=None, val_at=None, label=None):
        """
        pins: pin number -> name of the net inside this block.
        label: name of the part inside the block, e.g. "qn"; together with the
        names of the sheets it gives the part a path such as mux_n0.sw0.qn.
        """
        p = dict(lib=lib, name=name, prefix=prefix, value=value, pins=pins, fields=fields or {},
                 label=label,
                 placement=Placement(lib, name, at, rot, mirror, ref_at, val_at),
                 uuid=new_uuid(), local=len(self.parts))
        self.parts.append(p)
        return p

    def child(self, block, name, at, size, left, right, connect):
        c = Child(block, name, at, size, left, right, connect)
        self.children.append(c)
        return c

    def port(self, name, shape, at, rot):
        """Hierarchical label. rot 180: on the left, text to the left; rot 0: on the right."""
        self.ports[name] = (shape, (round(at[0], 2), round(at[1], 2)), rot)

    @staticmethod
    def pin(part, num):
        return part["placement"].pin(num)

    def wire(self, *pts):
        self.wires.append([(round(x, 2), round(y, 2)) for x, y in pts])

    def dot(self, p):
        self.junctions.append((round(p[0], 2), round(p[1], 2)))

    def label(self, name, p, rot=0):
        self.labels.append((name, (round(p[0], 2), round(p[1], 2)), rot))

    def power(self, name, p, rot=0):
        self.powers.append(dict(name=name, at=(round(p[0], 2), round(p[1], 2)), rot=rot,
                                uuid=new_uuid(), local=len(self.powers)))

    def text(self, txt, p):
        self.texts.append((txt, p))

    def stub(self, child, pin, net, length=3):
        """Short wire with a net label at a pin of a sheet symbol."""
        x, y, rot = child.pins[pin]
        d = -length * U if rot == 180 else length * U
        self.wire((x, y), (x + d, y))
        self.label(net, (x + d, y), rot)


# ---------------------------------------------------------------------------
class Design:
    """Elaborates a hierarchy of blocks and writes netlist and schematic sheets."""

    def __init__(self, root, project):
        self.root, self.project = root, project
        self.circuit = Circuit()
        self.count = {}
        self.pages = 0
        self.symbol_refs = {}               # (block file, part uuid) -> [(path, reference)]
        self.addresses = {}                 # reference -> path of names, e.g. "mux_n0.sw0.qn"
        self.sheet_pages = {}               # child uuid -> [(path of the parent, page)]
        self.blocks = {}                    # file name -> block
        self.instances = []                 # (hierarchical name, block)
        self.globals = {}
        for n in POWER_NETS:
            self.globals[n] = Net(n, circuit=self.circuit)
            self.globals[n].drive = POWER
        self.pages += 1
        self._elaborate(root, "/" + root.uuid, "", {})

    def _ref(self, prefix):
        self.count[prefix] = self.count.get(prefix, 0) + 1
        return f"{prefix}{self.count[prefix]}"

    def _elaborate(self, block, path, name, port_nets):
        self.blocks[block.filename] = block
        self.instances.append((name or "/", block))
        local = {}

        def net(n):
            if n in POWER_NETS:
                return self.globals[n]
            if n in port_nets:
                return port_nets[n]
            if n not in local:
                local[n] = Net(f"{name}/{n}".lstrip("/"), circuit=self.circuit)
            return local[n]

        for p in block.parts:
            ref = self._ref(p["prefix"])
            part = Part(p["lib"], p["name"], ref=ref, value=p["value"], circuit=self.circuit)
            part.footprint = "simulation:none"      # simulation model, there is no board
            part.fields.update(p["fields"])
            for num, n in p["pins"].items():
                part[num] += net(n)
            self.symbol_refs.setdefault((block.filename, p["uuid"]), []).append((path, ref))
            if p["label"]:
                self.addresses[ref] = f"{name}/{p['label']}".strip("/").replace("/", ".")
        for pw in block.powers:
            prefix = "#FLG" if pw["name"] == "PWR_FLAG" else "#PWR"
            ref = f"{prefix}{self.count.get(prefix, 0) + 1:03d}"
            self.count[prefix] = self.count.get(prefix, 0) + 1
            self.symbol_refs.setdefault((block.filename, pw["uuid"]), []).append((path, ref))
        for c in block.children:
            self.pages += 1
            self.sheet_pages.setdefault(c.uuid, []).append((path, self.pages))
            self._elaborate(c.block, f"{path}/{c.uuid}", f"{name}/{c.name}",
                            {port: net(n) for port, n in c.connect.items()})

    # -- KiCad output ------------------------------------------------------
    def _symbol(self, lib_id, at, rot, mirror, value, fields, pins, refs, ref_at, val_at, uid):
        x, y = at
        node = ["symbol", ["lib_id", q(lib_id)], ["at", f"{x:g}", f"{y:g}", str(rot)]]
        if mirror:
            node.append(["mirror", mirror])
        node += [["unit", "1"], ["exclude_from_sim", "no"], ["in_bom", "yes"],
                 ["on_board", "yes"], ["dnp", "no"], ["uuid", q(uid)]]
        ref = refs[0][1]
        hidden = ref.startswith("#")
        if ref_at is None:
            ref_at, val_at = (3.81, -1.27), (3.81, 1.27)
        ang = rot if rot in (90, 270) else 0
        just = None if ang else "left"
        node.append(_prop("Reference", ref, x + ref_at[0], y + ref_at[1], hide=hidden,
                          justify=just, angle=ang))
        node.append(_prop("Value", value, x + val_at[0], y + val_at[1], hide=hidden,
                          justify=just, angle=ang))
        node.append(_prop("Footprint", "", x, y, hide=True))
        node.append(_prop("Datasheet", "", x, y, hide=True))
        for k, v in fields.items():
            node.append(_prop(k, v, x, y, hide=True))
        for num in pins:
            node.append(["pin", q(num), ["uuid", q(new_uuid())]])
        node.append(["instances", ["project", q(self.project)] + [
            ["path", q(path), ["reference", q(r)], ["unit", "1"]] for path, r in refs]])
        return node

    def _sheet(self, c):
        x, y = c.at
        w, h = c.size
        eff = ["effects", ["font", ["size", "1.27", "1.27"]]]
        node = ["sheet", ["at", f"{x:g}", f"{y:g}"], ["size", f"{w:g}", f"{h:g}"],
                ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                ["stroke", ["width", "0.1524"], ["type", "solid"]],
                ["fill", ["color", "255", "255", "194", "1.0000"]], ["uuid", q(c.uuid)],
                ["property", q("Sheetname"), q(c.name), ["at", f"{x:g}", f"{y - 0.7:g}", "0"],
                 eff + [["justify", "left", "bottom"]]],
                ["property", q("Sheetfile"), q(c.block.filename),
                 ["at", f"{x:g}", f"{y + h + 0.6:g}", "0"], eff + [["justify", "left", "top"]]]]
        for name, (px, py, rot) in c.pins.items():
            shape = c.block.ports[name][0]
            node.append(["pin", q(name), shape, ["at", f"{px:g}", f"{py:g}", str(rot)],
                         ["uuid", q(new_uuid())],
                         eff + [["justify", "left" if rot == 180 else "right"]]])
        node.append(["instances", ["project", q(self.project)] + [
            ["path", q(path), ["page", q(page)]] for path, page in self.sheet_pages[c.uuid]]])
        return node

    @staticmethod
    def _hier_label(name, shape, at, rot):
        return ["hierarchical_label", q(name), ["shape", shape],
                ["at", f"{at[0]:g}", f"{at[1]:g}", str(rot)],
                ["effects", ["font", ["size", "1.27", "1.27"]],
                 ["justify", "right" if rot == 180 else "left"]], ["uuid", q(new_uuid())]]

    def write(self, directory):
        directory = Path(directory)
        directory.mkdir(exist_ok=True)
        for block in self.blocks.values():
            libs, body = {}, []
            for p in block.parts:
                pl = p["placement"]
                lib_id = f"{pl.lib}:{pl.name}"
                libs.setdefault(lib_id, lib_symbol(pl.lib, pl.name))
                fields = {unq(f[1]): unq(f[2]) for f in find_all(libs[lib_id], "property")
                          if unq(f[1]).startswith("Sim.")}
                fields.update(p["fields"])
                if "Sim.Library" in fields:
                    fields["Sim.Library"] = fields["Sim.Library"].replace(
                        "${KICAD9_SYMBOL_DIR}", "${KICAD10_SYMBOL_DIR}")
                pins = sorted(pin_offsets(pl.lib, pl.name), key=int)
                body.append(self._symbol(lib_id, pl.at, pl.rot, pl.mirror, p["value"], fields, pins,
                                         self.symbol_refs[(block.filename, p["uuid"])],
                                         pl.ref_at, pl.val_at, p["uuid"]))
            for pw in block.powers:
                lib_id = f"power:{pw['name']}"
                libs.setdefault(lib_id, lib_symbol("power", pw["name"]))
                body.append(self._symbol(lib_id, pw["at"], pw["rot"], None, pw["name"], {}, ["1"],
                                         self.symbol_refs[(block.filename, pw["uuid"])],
                                         None, None, pw["uuid"]))
            for poly in block.wires:
                body += [wire(a, b) for a, b in zip(poly, poly[1:])]
            body += [junction(p) for p in block.junctions]
            body += [label(n, p, rot) for n, p, rot in block.labels]
            body += [self._hier_label(n, s, at, rot) for n, (s, at, rot) in block.ports.items()]
            body += [text(t, p) for t, p in block.texts]
            body += [self._sheet(c) for c in block.children]

            root = ["kicad_sch", ["version", "20250114"], ["generator", q("eeschema")],
                    ["generator_version", q("9.0")], ["uuid", q(block.uuid)],
                    ["paper", q(block.paper)],
                    ["title_block", ["title", q(block.title)],
                     ["comment", "1", q("Generated from the description in lut.py")]],
                    ["lib_symbols"] + list(libs.values())] + body
            if block is self.root:
                root.append(["sheet_instances", ["path", q("/"), ["page", q("1")]]])
            root.append(["embedded_fonts", "no"])
            (directory / block.filename).write_text(dump(root) + "\n")

        pro = directory / (Path(self.root.filename).stem + ".kicad_pro")
        if not pro.exists():
            pro.write_text('{\n  "meta": { "filename": "%s", "version": 3 },\n'
                           '  "schematic": { "legacy_lib_list": [] }\n}\n' % pro.name)
        return directory / self.root.filename

    def connectivity(self):
        groups = set()
        for net in self.circuit.nets:
            pins = frozenset((p.part.ref, str(p.num)) for p in net.pins)
            if len(pins) > 1:
                groups.add(pins)
        return groups
