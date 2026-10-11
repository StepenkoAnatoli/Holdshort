# Credential rotation runbook — this machine *(OWNER: every step that handles a value)*

Placement is [GO_LIVE_RUNBOOK.md](GO_LIVE_RUNBOOK.md) §1: the key goes into the gitignored `.env`
and nowhere else. **Removal and replacement are this document.** It exists because the hard part of
rotation is not minting a new value — it is finding every copy of the old one and making sure git
and gh actually *use* the new one. On this machine two credential stores serve the same host, and
the one git consults is not the one `gh auth status` reports (§2).

Every discovery and verification command here is read-only and prints **names, hosts, accounts,
counts and digests — never a secret value**.

## 0. Invariants

Every procedure below is one application of these five rules.

1. **Never delete a credential you have not replaced.** Verify the new value works *before* removing
   the old one, or you lock yourself out of the repo mid-rotation.
2. **Invalidate before you scrub.** Revoking the value at the provider — or overwriting it — is the
   only action that makes every existing copy worthless at once. Deleting one copy while the value
   is still live is false progress: the other copies are still copies.
3. **One owner per host.** For `github.com`, exactly one store answers. A credential stored twice is
   how a rotation silently fails to take effect — you rotate the store the chain no longer reads and
   keep using the one it does.
4. **Never move a value through a medium that keeps it.** Not chat, not a command line (shell
   history is a plaintext file — §4), not a tracked file, not a PR body, not a log. Read from a file
   or stdin into the one destination.
5. **Verify by using, not by looking.** A store entry and a green `gh auth status` are claims; a
   successful authenticated action is evidence (§5).

Two consequences worth stating plainly: nothing in this repo rotates anything for you, and the
repo's checks are **detectors, not protectors** — they can refuse the *next* leak, never remove an
existing one.

## 1. Inventory — what this machine holds

Row 4 of the 10-11 audit ("the key for live dispatch stays out of the repo") is the Anthropic key;
the rest is the credential inventory that audit produced. State verified on this machine 2026-10-12:

| # | Credential | Purpose | Where it lives | Procedure | State 2026-10-12 |
|---|---|---|---|---|---|
| 1 | Anthropic API key | live-dispatch model calls | `<checkout>/.env` (gitignored, untracked) | §3.1 | not present in the current checkout |
| 2 | GitHub credential for `git` over https | push/pull of this repo | WinCred: `git:https://github.com` (GCM) and `gh:github.com:<user>` + `gh:github.com:` (gh) | §3.2 | both stores hold one; only the gh store is consulted (§2) |
| 3 | `gh` CLI session for `github.com` | PR/run inspection, `gh auth git-credential` | `%APPDATA%\GitHub CLI\hosts.yml` **and** WinCred tokens | §3.2 | no `hosts.yml` → gh reports no session while git still authenticates through the tokens |
| 4 | CI canary token *(optional)* | `tools/strict_canary.py`, only if the repo forbids Actions-created PRs | GitHub Actions secret `CANARY_TOKEN` | §3.3 | unset — the canary uses the run's own `github.token` |
| 5 | Plaintext credential files | account recovery, personal tooling | Desktop, other checkouts, backups | §3.4 | three credential-class files on the Desktop (51–206 B) |

Re-derive this table before acting on it — a rotation runbook that trusts recorded state is how you
rotate the wrong store:

```bash
# git/gh targets in the OS store (target names only, never values)
MSYS_NO_PATHCONV=1 cmdkey.exe /list | grep -aE 'Target:.*(git:|gh:)'
# which credential helpers git consults, and which config file each comes from
git config --show-origin --get-regexp '^credential.*\.helper$'
# the accounts GCM knows (names only)
MSYS_NO_PATHCONV=1 git-credential-manager --no-ui github list
# gh's session index (exit 1 = no session file — which does NOT mean no stored token)
gh auth status || true
# this repo's store check: 0 = clean/baselined, 1 = new finding, 2 = fail-closed
python tools/check_credential_hygiene.py
```

## 2. Why deleting is the hard part on Windows (the orphan class)

GCM and `gh` both keep credentials in Windows Credential Manager, and neither store is
self-describing: the index that decides whether an entry is *used* lives somewhere else. **GCM**
writes `git:<url>` and is read only when the effective helper chain contains `manager`. **gh** writes
`gh:<host>[:<user>]` — the active token also occupies an empty-user slot `gh:<host>:` — and is
indexed by `%APPDATA%\GitHub CLI\hosts.yml`.

This machine, 2026-10-12, has both failure modes at once:

```text
file:C:/Program Files/Git/etc/gitconfig   credential.helper manager
file:C:/Users/<you>/.gitconfig            credential.https://github.com.helper        (empty)
file:C:/Users/<you>/.gitconfig            credential.https://github.com.helper        !'…\gh.exe' auth git-credential
file:C:/Users/<you>/.gitconfig            credential.https://gist.github.com.helper   (empty)
file:C:/Users/<you>/.gitconfig            credential.https://gist.github.com.helper   !'…\gh.exe' auth git-credential
```

`gh auth setup-git` writes a **URL-scoped reset**: an empty `helper` value clears every helper
inherited for that URL (gitcredentials(7) semantics), and then gh's own helper is added. So the
store holds:

- `git:https://github.com` — a **live GCM credential git can never read again**, because `manager`
  is cleared for that URL. Nothing reports it: it is not in use, so nothing complains.
- `gh:github.com:<user>` and `gh:github.com:` — **live tokens with no `hosts.yml`**. `gh auth
  status` says "not logged in" (nothing indexes them) while gh's own git-credential helper still
  serves them; with no session file, `git ls-remote origin` succeeds *only* through this path
  (§7). **Deleting the file-side index does not delete the token.**

The consequence for rotation: rotate in the wrong store and the only thing you have invalidated is
the copy nobody was using. Every rotation below therefore ends with an **explicit per-target
delete**, then a use-test:

```bash
# OWNER: one target string per command; `cmdkey /list` prints the exact strings
MSYS_NO_PATHCONV=1 cmdkey.exe /delete:"git:https://github.com"
MSYS_NO_PATHCONV=1 cmdkey.exe /delete:"gh:github.com:<user>"
MSYS_NO_PATHCONV=1 cmdkey.exe /delete:"gh:github.com:"
```

`gh auth logout` is not a substitute: it removes the session and does not reliably remove the named
`gh:<host>:<user>` target when more than one account exists for the host. GCM's own CLI exposes
`get`/`store`/`erase`, but `erase` takes a credential *description* on stdin rather than a target
name, and `get` prints the value — so never run `get` in a logged session.

`tools/check_credential_hygiene.py` exists to make this state visible and to refuse new instances:
orphaned gh keyring tokens, stale tokens for accounts `hosts.yml` no longer lists, `git:` entries the
effective chain no longer reads, `hosts.yml` hosts with no token, and `.git-credentials` lines no
`store` helper reads. It rides the pre-commit gate, never executes a credential helper, never prints
a value — and it deliberately does **not** probe liveness, because a checker that reads tokens is
itself a credential surface. Treat every entry it names as live until a rotation proves otherwise.
The three entries above are triaged in
[`tools/credential_hygiene_baseline.json`](../tools/credential_hygiene_baseline.json); "baselined"
means *known and visible*, not *harmless*.

## 3. Procedures

### 3.1 Anthropic live-dispatch key *(OWNER: key pasting)*

1. Mint a new key in the Anthropic console, and keep the old one alive for now (invariant 1).
2. Place the new key by hand — pasted into `.env`, never through a command line:
   ```bash
   cp .env.example .env      # if absent; the OWNER pastes ANTHROPIC_API_KEY=… into it by hand
   ```
3. Verify placement ×3, the GO_LIVE_RUNBOOK §1 ritual:
   ```bash
   git check-ignore .env                 # exit 0 = ignored
   git ls-files | grep -x '.env'         # empty = never tracked
   python tools/check_secrets.py         # clean
   ```
4. Verify the new key *is the one in use*: run the GO_LIVE_RUNBOOK §5 live smoke with it. "The file
   has the new value" is not evidence.
5. Revoke the old key in the console — the step that kills every copy at once (old checkouts,
   backups, and §4's leak surfaces).
6. Scrub the copies (§4), then re-run §5. A revoked value still sitting in a transcript is a
   historical record; a *non-revoked* value sitting there is a live secret.

### 3.2 The GitHub credential for `git` over https *(OWNER)*

Decide **in writing** which store owns `github.com`, then remove the other. Step 0 is observation:

```bash
git config --show-origin --get-regexp '^credential.*\.helper$'
```

An empty value is a reset: it clears the helpers inherited for that URL.

**Path A — `gh` owns it (this machine's current chain; recommended).** The chain already consults gh
and this clone authenticates through it, so choosing A deletes the orphan instead of the working
credential.

1. Mint a fine-grained PAT with `contents: write` for this repo (add `workflow` if you push workflow
   files). Put it in a temporary file, then feed it from that file — never as an argument:
   ```bash
   gh auth login --hostname github.com --with-token < /path/to/new-token-file
   gh auth status          # reports the account; hosts.yml now exists, so the keyring
                           # tokens are indexed rather than orphaned
   ```
   `gh auth setup-git` has already wired the URL-scoped helper on this machine; nothing to redo.
2. Verify with a use-test, not a status line: `git ls-remote origin -h refs/heads/main` (SHAs only),
   then push a throwaway branch and open a PR (§5).
3. Revoke the superseded GitHub credential. A PAT is deleted in GitHub → Settings → Developer
   settings. If the old credential came from `gh`'s OAuth flow, deleting the token locally does not
   revoke the server-side grant — revoke it at GitHub → Settings → Applications → **Authorized OAuth
   Apps**.
4. Delete the now-redundant GCM entry (§2) and the temporary token file:
   ```bash
   MSYS_NO_PATHCONV=1 cmdkey.exe /delete:"git:https://github.com"
   ```
5. Re-run §5, including pruning the resolved baseline row (§5.3).

**Path B — GCM owns it.** Choose this only if you want the GUI-managed credential; it changes which
store git consults, so step 1 is the pivot.

1. Remove the URL-scoped reset and gh helper, so the system-level `credential.helper manager` applies
   again:
   ```bash
   git config --global --unset-all 'credential.https://github.com.helper'
   git config --global --unset-all 'credential.https://gist.github.com.helper'
   ```
   Re-running `gh auth setup-git` undoes this; don't.
2. Store a fresh credential through GCM explicitly:
   ```bash
   MSYS_NO_PATHCONV=1 git-credential-manager --no-ui github login    # interactive: adds an account
   MSYS_NO_PATHCONV=1 git-credential-manager --no-ui github list     # names only
   ```
3. Verify `git ls-remote origin -h refs/heads/main` still succeeds *before* deleting anything
   (invariant 5).
4. Delete the gh-side tokens (§2's `cmdkey` deletes, or
   `git-credential-manager --no-ui github logout <account>`), revoke the superseded value at the
   provider, and re-run §5.

Either path ends the state this section exists to fix: one host, one credential, one store.

### 3.3 Optional: the CI canary token

Unused today. The gate workflow authenticates with the run's own `github.token`
(`secrets.CANARY_TOKEN || github.token`) because this repo enabled `can_approve_pull_request_reviews`
in the 10-11 strict-mode upgrade. `CANARY_TOKEN` exists for the case where that setting is turned
back off; `tools/strict_canary.py` needs `contents: write`, `pull-requests: write` and
`checks: write`.

```bash
gh secret set CANARY_TOKEN < /path/to/new-token-file   # from a file, never as an argument
gh secret list                                         # name + updated date only; values are never shown
```

Verify by using it: dispatch the gate workflow's canary job and read its conclusion
(`gh run list --limit 5`). A missing or under-scoped token surfaces as *misconfiguration* (exit 3),
never as PASS. Then revoke the superseded token at the provider.

### 3.4 Recovery codes and other plaintext files *(OWNER)*

A plaintext credential file is not rotatable in place, and GitHub recovery codes are not rotated at
all — they are *regenerated* (Settings → Password and authentication → Recovery codes → regenerate),
which invalidates every previously printed code. If such a file was ever exposed, regenerate, delete
the file, and keep the new codes in a password manager rather than in a text file.

Last inventoried 2026-10-12: `Research-Kit`'s root held no key or token files (the 10-11 audit's
finding there is resolved), while the Desktop held three credential-class files, 51–206 B (an API
key, a dated token export, GitHub recovery codes). Re-derive rather than trust this line:

```bash
find "$USERPROFILE/Desktop" "$USERPROFILE/Research-Kit" -maxdepth 1 -type f \
     \( -iname '*token*' -o -iname '*key*' -o -iname '*credential*' -o -iname '*.env' \) \
     -printf '%s\t%f\n'
```

This runbook names classes and sizes rather than file names because this repository is public; the
machine-local detail belongs on the machine. A plaintext file whose only content *is* a credential
has no safe steady state: revoke the value, then delete the file.

## 4. Scrub the copies a leaked value left behind

Do this **after** revocation (invariant 2). None of it is tracked by this repo, so no check here can
see it — which is exactly why it is a manual step.

**Shell history.** PowerShell's PSReadLine appends every command line to a plaintext file, so an
inline `curl -H "Authorization: Bearer …"` lands there permanently. Report counts, never matches:

```bash
h="$APPDATA/Microsoft/Windows/PowerShell/PSReadLine/ConsoleHost_history.txt"
for p in 'sk-ant-[A-Za-z0-9_-]{10,}' 'ghp_[A-Za-z0-9]{36}' 'Bearer +[A-Za-z0-9._-]{20,}'; do
  printf '%s: %s hit(s)\n' "$p" "$(grep -caE "$p" "$h" 2>/dev/null || echo 0)"
done
```

Clean hits by editing the file (`notepad "$h"`), and prefer config-file or environment indirection
over inline headers so they stop recurring. (This machine: 0 / 0 / 0 on 2026-10-12.)

**App transcript stores.** The Freebuff Desktop app persists thread transcripts under
`%USERPROFILE%\.config\freebuff-desktop\projects\*\desktop-v2.db*`. A secret echoed into a chat is
written there and is invisible to `check_secrets.py`, whose corpus is exactly `git ls-files`. Count
only:

```bash
E=''   # split literal, so this command's own text cannot count itself
for s in "$USERPROFILE"/.config/freebuff-desktop/projects/*/desktop-v2.db; do
  [ -f "$s" ] && printf '%s: %s hit(s)\n' "$(basename "$(dirname "$s")")" \
    "$(grep -aoE "github_pat_$E[A-Za-z0-9_]{20,}|ghp_$E[A-Za-z0-9]{36}|sk-ant-$E[A-Za-z0-9_-]{10,}" "$s" | wc -l)"
done
```

Read the number as a tripwire, not a ledger: it also counts rows where the *pattern text itself* was
stored — commands like this one, diffs, earlier audits — so a nonzero count means "this surface holds
token-shaped text", not "N live secrets". **Do not edit the database**: the app owns it and is
usually running. The supported levers are the app's own data controls, plus rotation, which makes
every stored copy worthless at once.

**Other checkouts, backups and exports.** Every clone has its own `.env` and its own `.git/config`
credentials, and every backup archive has its own copy of the Desktop. Grep them by class *after*
revoking, remembering that a revoked value in an old archive is already inert.

**What this repo covers, and its blind spots.** `.gitignore` excludes `.env`, `*.pem`, `*.key`,
`credentials*.json` and `secrets*.json`; `check_secrets.py` scans *tracked* files and fails closed on
anything it cannot decode; `check_credential_hygiene.py` scans the local git and gh stores. By
construction, none of them can see untracked plaintext files outside the repo, app databases, shell
history, or any other machine. §4 is the manual cover for that gap.

## 5. Verification — run after every rotation

### 5.1 The stores are in the state you think they are

```bash
python tools/check_credential_hygiene.py                        # 0 clean/baselined; 1 act on it; 2 fail-closed
git config --show-origin --get-regexp '^credential.*\.helper$'  # exactly one owner for github.com
MSYS_NO_PATHCONV=1 cmdkey.exe /list | grep -aE 'Target:.*(git:|gh:)'   # deleted targets are gone
```

### 5.2 The credential actually works

```bash
git ls-remote origin -h refs/heads/main                # read path; SHAs only
git push -u origin HEAD:refs/heads/<throwaway-branch>  # write path; delete the branch afterwards
gh run list --limit 5                                  # CI green on the pushed commit
python tools/run_regression.py                         # full local gate: exit 0 = pass
```

A store entry without a successful use is an unverified claim. And a `ls-remote` that still succeeds
while the entry you meant to delete is gone means the *other* store answered — the two-store state
of §2, not a clean result.

### 5.3 The next rotation starts clean

The gate's baseline is keyed by finding **subject** (a store target, or `file:<host>` /
`hosts.yml:<host>`), and `--update-baseline --note "…"` only *adds*. So once an entry is genuinely
gone, remove its row from
[`tools/credential_hygiene_baseline.json`](../tools/credential_hygiene_baseline.json) and re-run the
check: a resolved row left in place silently silences a *recurrence* of that same target. Re-add an
entry only after triage, never to turn a red check green.

## 6. Stop conditions and non-goals

- **No value, ever.** No step here reads, prints or validates a secret, and the checks never execute
  a credential helper. Nothing in this document can be run to leak.
- **No automatic rotation.** Every step that handles a value is OWNER; this is a procedure, not a
  tool.
- **Provider-side revocation is the only revocation.** Deleting a copy is cleanup, never
  invalidation.
- **Assume compromise** for anything that was ever exposed beyond its intended destination —
  including a token that briefly appeared in a chat, a commit or a public repo. Revoke first, ask
  questions after.
- **Windows-scoped mechanics.** `cmdkey`, the two-store split and PSReadLine are Windows surfaces; on
  POSIX the same rules apply to Keychain/libsecret and `.bash_history` / `.zsh_history`.
- **Not an incident response.** If a token reached a public place, GitHub's secret scanning may
  already have revoked it and notified you; check before assuming the value is still live.

## 7. Traceability — what was verified on 2026-10-12, and how

| Claim | Evidence |
|---|---|
| git consults gh, not GCM, for `github.com` | `git config --show-origin --get-regexp` output quoted in §2, user path elided (empty reset, then gh's helper) |
| the gh keyring tokens are *live* orphans | `git ls-remote origin -h refs/heads/main` → `b550109…`, with no `hosts.yml` present |
| GCM's entry is unreachable | the same chain output: no `manager` survives the reset for that URL |
| the store's contents | `cmdkey /list`: three `git:`/`gh:` targets, plus 5 unrelated entries the check reports as unjudged |
| GCM's real CLI surface | `git-credential-manager --version` → 2.9.1, with `--help` and `github --help` listing `list`/`login`/`logout` (§3.2) |
| `CANARY_TOKEN` is unused | `gh secret list` empty; workflow reads `secrets.CANARY_TOKEN \|\| github.token` |
| the §4 surfaces and their state | the history loop → 0/0/0; the app-store loop → `desktop-v2.db` holds token-shaped text |
| the store check's verdict | `python tools/check_credential_hygiene.py` → 0 (clean, 3 baselined) |

**Not exercised here, and marked as such:** the `cmdkey /delete`, `gh auth login --with-token`,
`gh secret set` and `git-credential-manager github login/logout` steps are prescribed from their
verified CLI surface but were not run — they are destructive or interactive, and this document was
written read-only. The first rotation performed from this runbook should correct it in place.
