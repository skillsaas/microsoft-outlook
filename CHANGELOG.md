# Changelog

## 0.1.2 (2026-10-13)

- RTF hardening: `\u` values clamped to U+FFFD, `\ansicpg` checked with codecs.lookup (falls back to cp1252), `\binN` data skipped, MELA CRC must be 0, any decode error or truncation marks the parse incomplete with a report instead of exit 2 with nothing.
- One exit-code policy for incomplete parses: exit 1 with `status: incomplete` in every script; `inspect_mail.py --allow-incomplete` replaces `--strict`. Documented in SKILL.md and json-output.md.
- Timeout: a shared lock means only one result is printed, the timer is cancelled on exit, and a timeout during extraction removes the hidden `.extract-*` folder and reports it under `cleanup`.
- Attached .msg and winmail.dat files inside an .eml are detected by their bytes and parsed.
- inspect_ics.py: month 00 and year 9999 handled, ZoneInfo lookups guarded, catch-all JSON error.
- `boundary*=` depth bypass closed; `--js` and `--json=1` now give a JSON error (allow_abbrev off).
- Graph recipes re-checked against Microsoft Learn examples; third-party upload rule is now safety rule 2; quarantine is not a security boundary; PSL limit noted in the reply-to detail.
- New chained recipe (inspect, approval, extract), stated default caps, skill.json scripts map.
- REAL_FIXTURES_DIR hook; real Outlook files remain untested and the docs say so.
- Tests: 43 plus 3 optional (cross-check, TNEF corpus, real files). Frontmatter test checks the allowed keys.

## 0.1.1 (2026-10-13)
Round 1 review fixes (12 reviews; synthesis in the feedback folder). Not published.
- **Partial parses are never clean (H1).** MIME nesting past 50 levels, nested messages past 4,
  broken nested items, unreadable TNEF MAPI blocks, truncated TNEF and failed RTF bodies now set
  `complete: false`, list each gap in `incomplete` (copied up from nested messages), and add a
  medium `parse-incomplete` risk first in `risks`. `--strict` makes it exit 1.
  `extract_attachments.py` fails closed: nothing written, exit 1, unless `--allow-incomplete`.
- **Attachment count cap for .eml and .msg** (was TNEF only): 500 in total, nested included,
  `--max-attachments`; over it is exit 3 with nothing written. More than 2,000 declared MIME
  boundaries are refused before parsing, and a RecursionError is a refusal, not a traceback.
- **Wall-clock limit** `--timeout` on all three scripts (60 s inspect, 120 s extract): exit 3.
- **One meaning per exit code** and a JSON `status` field (`ok`, `incomplete`,
  `risk-threshold`, `risky-skipped`, `error`, `refused`). Usage errors are JSON under `--json`.
  `--version` on every script. The mailsafe docstring now matches SKILL.md.
- **Fixed JSON schema** for inspect_mail (`schema: microsoft-outlook/inspect-mail/1`), with
  `not_checked` and `complete`; documented in `references/json-output.md` with risk semantics.
- Risks: remote images reported (`html-remote-images`); `.html`/`.svg` attachments high, so
  extraction skips them by default; `.dat`, TNEF and attached messages are containers (medium);
  percent-encoded hosts flagged high and decoded before comparison; the extension of a very
  long padded name is now checked on the full name and kept when a saved name is shortened.
- Compressed RTF bodies decoded (`rtfbody.py`, MS-OXRTFCP with CRC check, HTML de-encapsulation
  per MS-OXRTFEX); flag `body-from-rtf`.
- Windows time zone names converted with the CLDR windowsZones table (142 zones, Unicode
  License v3); DST gap and overlap times flagged.
- Symlinked output parents (macOS `/tmp`, some home folders) are resolved, not refused. The
  manifest is written 0600. A short Compound File now reports truncation, not a bad signature.
- Docs: SKILL.md first screen is a task router with one merged safety list (approval bound to
  one action, never retry a write blindly, use an existing Graph connector); graph.md gains auth
  (device code, consent, Conditional Access), a Limits table and HTTP recipes; addins.md gains a
  typed OnMessageSend handler (type-checked) and corrects `sendModeOverride` (an
  `event.completed` option, promptUser only); formats.md gains a support matrix and caps table;
  .pst marked orientation only; last-verified dates on every reference.
- Tests: 31 to 40, including a SKILL.md frontmatter check.

## 0.1.0 (2026-10-13)
First version. Not published.
- SKILL.md router: decision guide with a first command per task, never-do and ask-first lists,
  safe workflow, exit code table, verification checklist, new vs classic Outlook notes.
- Scripts (Python 3.9+ standard library only): `inspect_mail.py` (.msg, .eml, winmail.dat),
  `extract_attachments.py` (safe names, risky types skipped or quarantined, manifest with
  SHA-256), `inspect_ics.py` (methods, zones, recurrence, links, alarms), with a hardened
  Compound File reader (`msgcfb.py`) and TNEF reader (`tnef.py`).
- Attachment risk uses Microsoft's list of 133 blocked extensions (read 2026-10-13) plus
  labelled heuristics for macro, browser-opened and container formats.
- References: formats, security, Graph mail (EWS retirement, REST v2 decommissioning), calendar,
  rules and signatures, search (AQS and KQL), add-ins (checked against @types/office-js
  1.0.611), four worked recipes, fallbacks (.pst via sandboxed readpst), troubleshooting.
- Tests: `tests/smoke_test.py` with synthetic fixtures from `tests/make_fixtures.py`, a network
  canary with a positive control, hardening cases, refusals and release consistency checks.
