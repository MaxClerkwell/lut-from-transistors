# LUT with two inputs: simulation results

One transient run covers all 16 functions. The inputs step through the four
combinations in Gray code (index 0, 1, 3, 2) in steps of 200 ns. The table is
rewritten every 800 ns, 100 ns after the inputs have returned to 00.

## Truth table

The output Y is sampled 5 ns before the end of every input combination.
The table is written as T3 T2 T1 T0, the index is 2 B + A.

| Table | Function | Measured |
|---|---|---|
| 0000 | 0 | 0000 ok |
| 0001 | NOR | 0001 ok |
| 0010 | A AND NOT B | 0010 ok |
| 0011 | NOT B | 0011 ok |
| 0100 | B AND NOT A | 0100 ok |
| 0101 | NOT A | 0101 ok |
| 0110 | XOR | 0110 ok |
| 0111 | NAND | 0111 ok |
| 1000 | AND | 1000 ok |
| 1001 | XNOR | 1001 ok |
| 1010 | A | 1010 ok |
| 1011 | A OR NOT B | 1011 ok |
| 1100 | B | 1100 ok |
| 1101 | B OR NOT A | 1101 ok |
| 1110 | OR | 1110 ok |
| 1111 | 1 | 1111 ok |

## Measurements

| Quantity | Value |
|---|---|
| Wrong entries out of 64 | 0 |
| Level of YI for a 1, mean | 5.000 V |
| Level of YI for a 1, lowest | 5.000 V |
| Level of YI for a 0, highest | 0.0 mV |
| Level of Y for a 1 | 5.000 V |
| Supply current at rest, smallest | 2e-05 µA |
| Supply current at rest, largest | 0.015 µA |
| Delay A to Y, rising | 12.2 ns (8 edges) |
| Delay A to Y, falling | 9.1 ns (8 edges) |
| Delay B to Y, rising | 10.8 ns (8 edges) |
| Delay B to Y, falling | 7.8 ns (8 edges) |
| Delay table bit to Y, rising | 11.1 ns (8 edges) |
| Delay table bit to Y, falling | 8.2 ns (7 edges) |

## Glitches

Both inputs change within 1 ns; the old and the new table entry are both 1, so
Y should stay at 1. Lowest voltage of YI and Y in the 90 ns after the change,
and the width of the pulse if Y crosses half the supply.

| Change | lowest YI | lowest Y | Glitch at Y |
|---|---|---|---|
| XOR, index 1 to 2 | 3.37 V | 5.00 V | none |
| XOR, index 2 to 1 | 3.58 V | 5.00 V | none |
| XNOR, index 0 to 3 | 3.14 V | 5.00 V | none |
| XNOR, index 3 to 0 | 3.74 V | 5.00 V | none |
