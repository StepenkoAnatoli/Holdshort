| profile | task | tokens | ms | est. $ (all-input .. all-output) | result |
|---|---|---|---|---|---|
| haiku-low | pin | 118,993 | 89,800 | 0.01 .. 0.06 | PASS |
| haiku-low | fix | 116,605 | 85,426 | 0.01 .. 0.06 | PASS |
| haiku-low | review | 130,440* | 117,306 | 0.01 .. 0.07 | PASS |
| haiku-medium | pin | 114,463 | 51,172 | 0.01 .. 0.06 | PASS |
| haiku-medium | fix | 142,018 | 159,702 | 0.01 .. 0.07 | PASS |
| haiku-medium | review | 138,791 | 143,252 | 0.01 .. 0.07 | PASS |
| haiku-high | pin | 119,515 | 69,117 | 0.01 .. 0.06 | PASS |
| haiku-high | fix | 142,418* | 131,479 | 0.01 .. 0.07 | PASS |
| haiku-high | review | 174,287 | 236,225 | 0.02 .. 0.09 | PASS |
| sonnet-low | pin | 99,291 | 30,847 | 0.20 .. 0.99 | PASS |
| sonnet-low | fix | 104,911 | 59,651 | 0.21 .. 1.05 | PASS |
| sonnet-low | review | 109,426 | 58,558 | 0.22 .. 1.09 | PASS |
| sonnet-medium | pin | 101,399 | 28,838 | 0.20 .. 1.01 | PASS |
| sonnet-medium | fix | 107,145 | 66,476 | 0.21 .. 1.07 | PASS |
| sonnet-medium | review | 125,630 | 116,886 | 0.25 .. 1.26 | PASS |
| sonnet-high | pin | 113,314 | 40,155 | 0.23 .. 1.13 | PASS |
| sonnet-high | fix | 121,541 | 171,017 | 0.24 .. 1.22 | PASS |
| sonnet-high | review | 159,276 | 240,778 | 0.32 .. 1.59 | PASS |
| sonnet-xhigh | review | 227,264 | 622,072 | 0.45 .. 2.27 | PASS |
| opus-medium | pin | 103,643 | 57,702 | 0.41 .. 2.07 | PASS |
| opus-medium | fix | 107,815 | 138,801 | 0.43 .. 2.16 | PASS |
| opus-medium | review | 127,281 | 140,777 | 0.51 .. 2.55 | PASS |
| opus-high | pin | 108,414 | 78,894 | 0.43 .. 2.17 | PASS |
| opus-high | fix | 119,586 | 118,436 | 0.48 .. 2.39 | PASS |
| opus-high | review | 141,662 | 187,896 | 0.57 .. 2.83 | PASS |
| opus-xhigh | pin | 137,110 | 198,752 | 0.55 .. 2.74 | PASS |
| opus-xhigh | fix | 154,590 | 294,159 | 0.62 .. 3.09 | PASS |
| opus-xhigh | review | 182,333 | 475,508 | 0.73 .. 3.65 | PASS |
| opus-max | review | 266,339 | 1,010,251 | 1.07 .. 5.33 | PASS |
| fable-medium | pin | 108,498 | 75,297 | 1.08 .. 5.42 | FAIL |
| fable-medium | fix | 116,496 | 189,301 | 1.16 .. 5.82 | PASS |
| fable-medium | review | 148,926 | 260,658 | 1.49 .. 7.45 | PASS |
| fable-high | pin | 120,400 | 99,463 | 1.20 .. 6.02 | PASS |
| fable-high | fix | 141,930 | 269,151 | 1.42 .. 7.10 | PASS |
| fable-high | review | 147,254 | 302,260 | 1.47 .. 7.36 | PASS |
| fable-xhigh | pin | 140,242 | 232,838 | 1.40 .. 7.01 | PASS |
| fable-xhigh | fix | 166,060 | 443,792 | 1.66 .. 8.30 | PASS |
| fable-xhigh | review | 186,589 | 609,038 | 1.87 .. 9.33 | PASS |
| fable-max | review | 189,364 | 640,389 | 1.89 .. 9.47 | PASS |

Totals (scored cells): pin 1,385,282; fix 1,541,115; review 2,454,862; graders, clustering and lenses (opus high, both runs) 3,440,417. Main run 8,531,566 tokens (the workflow reported 8,531,566), of which the two void cells and the void grade 255,026; supplementary run 456,376 (reported 456,376); both runs 8,987,942. `*` = supplementary run. Estimates apply tools/prices-2.json rows to harness-reported tokens; not a bill.
