| cluster | title | members | grader says | lenses (holds/reachable) | verdict |
|---|---|---|---|---|---|
| C-1 | Body read (and fetch await) not raced against the bounded signal: a stalled body that ignores abort hangs past requestTimeoutMs | haiku-medium R-3, haiku-high R-3, sonnet-medium R-4, opus-medium R-5, opus-xhigh R-4, opus-max R-3, haiku-low R-3 | true, true, true, false, true, true, false | REPRODUCE: holds/yes; reachability: holds/yes; REFUTE: holds/yes | REAL (3/3) |
| C-2 | Awaited body/reader cancel() has no bound: a cancel that never settles holds back an already-decided result | haiku-medium R-4, sonnet-medium R-3, opus-xhigh R-3, opus-max R-4 | true, true, true, true | REPRODUCE: holds/yes; reachability: holds/yes; REFUTE: no/yes | REAL (2/3) |
| C-3 | Combined: the body phase (read and cancel) never observes the timeout signal, so a stalled stream or a never-settling cancel hangs the call | sonnet-low R-3, opus-high R-3, sonnet-xhigh R-4, fable-xhigh R-3 | true, false, true, true | reproduce: holds/yes; REACHABILITY: holds/yes; REFUTE: holds/yes | REAL (3/3) |
| C-4 | ERROR_CODE /^[a-z_]{1,64}$/ lets a token-shaped error value through verbatim as the result code | haiku-medium R-6, haiku-high R-2 | false, false | REPRODUCE: holds/yes; reachability: holds/yes; REFUTE: no/yes | REAL (2/3) |
| C-5 | parseBody's flat-object check rejects a 2xx token answer that has a boolean or null field | haiku-medium R-5 | false | REPRODUCE: holds/yes; reachability: holds/yes; REFUTE: no/yes | REAL (2/3) |

Verdict rule as preregistered: a lens votes real when `holds` and `reachable` is not `no`; majority of three. See lead-notes G-2: the schema carries no `forbidden` prong, and for C-4 and C-5 the lenses' prose says the specification permits the behaviour.
