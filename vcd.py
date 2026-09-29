"""
Minimal writer for Value Change Dump (VCD) files, the waveform format that
GTKWave reads (IEEE 1364, section 18).

A VCD file is a header that declares the signals, followed by a list of
time stamps, each with the signals that change at that time. Besides bits
and bit vectors the format knows real numbers, which GTKWave can draw as
analog traces (Data Format -> Analog). That makes it possible to put the
logic values and the voltages of a circuit simulation into one file.
"""

import datetime
import itertools


class Signal:
    def __init__(self, name, kind, width, code):
        self.name, self.kind, self.width, self.code = name, kind, width, code
        self.changes = []                   # list of (time in units of the timescale, value)

    def format(self, value):
        if self.kind == "real":
            return f"r{value:.6g} {self.code}"
        if self.width == 1:
            return f"{int(value)}{self.code}"
        return f"b{int(value):0{self.width}b} {self.code}"


class VCD:
    """
    vcd = VCD("1ps", scope="lut2")
    a = vcd.wire("a")                # one bit
    t = vcd.wire("table", 4)         # bit vector
    v = vcd.real("v_y")              # real number
    vcd.change(a, 0.0, 0)            # time in seconds
    vcd.write("out.vcd")
    """

    UNITS = {"1s": 1.0, "1ms": 1e-3, "1us": 1e-6, "1ns": 1e-9, "1ps": 1e-12, "1fs": 1e-15}

    def __init__(self, timescale="1ps", scope="top", comment=""):
        self.timescale, self.scope, self.comment = timescale, scope, comment
        self.unit = self.UNITS[timescale]
        self.signals = []
        self._codes = self._code_generator()

    @staticmethod
    def _code_generator():
        chars = [chr(c) for c in range(33, 127)]        # printable ASCII, as the standard demands
        for n in itertools.count(1):
            for combo in itertools.product(chars, repeat=n):
                yield "".join(combo)

    def _add(self, name, kind, width):
        s = Signal(name, kind, width, next(self._codes))
        self.signals.append(s)
        return s

    def wire(self, name, width=1):
        return self._add(name, "wire", width)

    def real(self, name):
        return self._add(name, "real", 64)

    def change(self, signal, time, value):
        """Record a value; consecutive identical values are dropped."""
        t = int(round(time / self.unit))
        if signal.changes and signal.changes[-1][1] == value:
            return
        if signal.changes and signal.changes[-1][0] == t:
            signal.changes[-1] = (t, value)
            return
        signal.changes.append((t, value))

    def write(self, path, end_time=None):
        lines = [f"$date {datetime.date.today().isoformat()} $end",
                 "$version transistor-lut vcd.py $end"]
        if self.comment:
            lines.append(f"$comment {self.comment} $end")
        lines += [f"$timescale {self.timescale} $end", f"$scope module {self.scope} $end"]
        for s in self.signals:
            rng = f" [{s.width - 1}:0]" if s.kind == "wire" and s.width > 1 else ""
            lines.append(f"$var {s.kind} {s.width} {s.code} {s.name}{rng} $end")
        lines += ["$upscope $end", "$enddefinitions $end"]

        events = {}
        for s in self.signals:
            for t, v in s.changes:
                events.setdefault(t, []).append(s.format(v))
        first = True
        for t in sorted(events):
            lines.append(f"#{t}")
            if first:
                lines.append("$dumpvars")
            lines += events[t]
            if first:
                lines.append("$end")
                first = False
        if end_time is not None:
            lines.append(f"#{int(round(end_time / self.unit))}")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        return path
