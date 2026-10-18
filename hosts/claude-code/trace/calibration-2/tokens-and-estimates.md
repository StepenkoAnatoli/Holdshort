| profile | task | tokens | ms | est. $ (all-input .. all-output) | result |
|---|---|---|---|---|---|
| haiku-low | pin | 122,194 | 68,417 | 0.01 .. 0.06 | PASS |
| haiku-low | fix | 139,679 | 148,170 | 0.01 .. 0.07 | PASS |
| haiku-low | review | 174,821 | 234,326 | 0.02 .. 0.09 | FAIL |
| haiku-medium | pin | 125,966 | 63,824 | 0.01 .. 0.06 | PASS |
| haiku-medium | fix | 138,770 | 149,703 | 0.01 .. 0.07 | PASS |
| haiku-medium | review | 182,199 | 266,627 | 0.02 .. 0.09 | FAIL |
| haiku-high | pin | 135,343 | 113,768 | 0.01 .. 0.07 | PASS |
| haiku-high | fix | 170,424 | 234,413 | 0.02 .. 0.09 | PASS |
| haiku-high | review | 196,355 | 341,684 | 0.02 .. 0.10 | FAIL |
| sonnet-low | pin | 101,390 | 40,524 | 0.20 .. 1.01 | PASS |
| sonnet-low | fix | 106,006 | 80,517 | 0.21 .. 1.06 | PASS |
| sonnet-low | review | 113,230 | 47,573 | 0.23 .. 1.13 | PARTIAL |
| sonnet-medium | pin | 108,251 | 42,985 | 0.22 .. 1.08 | PASS |
| sonnet-medium | fix | 120,149 | 119,497 | 0.24 .. 1.20 | PASS |
| sonnet-medium | review | 127,804 | 115,885 | 0.26 .. 1.28 | FAIL |
| sonnet-high | pin | 119,783 | 56,307 | 0.24 .. 1.20 | PASS |
| sonnet-high | fix | 124,739 | 113,343 | 0.25 .. 1.25 | PASS |
| sonnet-high | review | 182,356 | 390,740 | 0.36 .. 1.82 | PASS |
| sonnet-xhigh | review | 327,759 | 2,296,489 | 0.66 .. 3.28 | PASS |
| opus-medium | pin | 115,308 | 68,626 | 0.46 .. 2.31 | PASS |
| opus-medium | fix | 123,461 | 116,588 | 0.49 .. 2.47 | PASS |
| opus-medium | review | 153,636 | 148,763 | 0.61 .. 3.07 | FAIL |
| opus-high | pin | 122,111 | 92,895 | 0.49 .. 2.44 | PASS |
| opus-high | fix | 132,019 | 142,239 | 0.53 .. 2.64 | PASS |
| opus-high | review | 171,293 | 316,306 | 0.69 .. 3.43 | PASS |
| opus-xhigh | pin | 152,218 | 257,055 | 0.61 .. 3.04 | PASS |
| opus-xhigh | fix | 169,745 | 368,645 | 0.68 .. 3.39 | PASS |
| opus-xhigh | review | 239,582 | 831,180 | 0.96 .. 4.79 | PASS |
| opus-max | review | 306,927 | 1,378,024 | 1.23 .. 6.14 | PASS |
| fable-medium | pin | 118,845 | 92,354 | 1.19 .. 5.94 | PASS |
| fable-medium | fix | 131,479 | 189,507 | 1.31 .. 6.57 | PASS |
| fable-medium | review | 171,828 | 450,067 | 1.72 .. 8.59 | PASS |
| fable-high | pin | 123,338 | 116,884 | 1.23 .. 6.17 | PASS |
| fable-high | fix | 148,456 | 317,730 | 1.48 .. 7.42 | PASS |
| fable-high | review | 196,292 | 614,640 | 1.96 .. 9.81 | PASS |
| fable-xhigh | pin | 140,504 | 291,899 | 1.41 .. 7.03 | PASS |
| fable-xhigh | fix | 160,017 | 395,385 | 1.60 .. 8.00 | PASS |
| fable-xhigh | review | 235,680 | 1,006,104 | 2.36 .. 11.78 | PASS |
| fable-max | review | 229,283 | 1,092,062 | 2.29 .. 11.46 | PASS |

Totals: pin 1,485,251; fix 1,664,944; review 3,009,045; graders (opus high) 1,713,036; run 7,872,276 tokens (the workflow reported 7,872,276).
