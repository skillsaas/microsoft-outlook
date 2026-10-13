# Changelog

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
