# Changelog

## 0.1.6 (2026-10-13)

- Hamza R6-A: an attached message whose contents were read (.eml, .msg, winmail.dat) is never written itself, with or without `--only-ext`; only its attachments are filtered and saved (as SKILL.md says). Test added.
- R6-B: `script-like-text` needs three code markers and most lines reading as code, so an ordinary .txt note with a code snippet is no longer held back.
- Tariq N16: UTF-32 text (with or without BOM) is decoded before the checks. N17: a leading pad of any length is scanned past; 1024 bytes or more is flagged `large-leading-padding` (medium). N18: HTML or script after leading `<!-- -->` comments is detected. N19: `tests/fetch_public_samples.py` contacts only raw.githubusercontent.com and refuses redirects.
- haiku (round 6, top): graph.md has a minimal MSAL device-code sketch (documented, not run) and links for other languages; SKILL.md says `--show-targets` shows full URLs as text and never connects, nested messages are risk-checked recursively, a partial parse is exit 1 `incomplete` with nothing written; safety rule 3 names the folders never to extract into (synced, Desktop, previewed, indexed); json-output.md says what to do for each exit-1 `status`; the domain comparison is text only (no PSL, no homoglyph check); addins.md says to try recipes in a test mailbox; "Load only the reference file named in the row's Load column"; tested_with names the fetch script.
- gpt-oss: a GitHub Actions workflow (`.github/workflows/test.yml`, Linux, Windows, macOS on Python 3.9 and 3.13; not run yet, the repo is not pushed); the output folder is to be treated as untrusted (rule 3). Not adopted: an option to skip the content check (it reads at most 8 KB per attachment); a Graph mock suite.
- gemma: calendar.md table of common IANA to Windows zone names from the bundled CLDR data. mistral-small and mini: a three-step quickstart line above the SKILL.md task table.
- Tests: 53 plus 3 optional.

## 0.1.5 (2026-10-13)

- Tariq (top): before the magic check the head is normalized (BOM, leading whitespace, nulls and junk stripped; UTF-16 decoded when the text is printable), and a PE header is searched. A document whose content does not match its type is held back from extract unless `--include-risky` (saved as `.quarantine`). LNK magic added.
- Tariq: plain JavaScript or JScript saved as .txt is `script-like-text` (held back). `tests/fetch_public_samples.py` fetches the 38 public samples pinned by commit and SHA-256; `tests/public_samples_expected.json` holds expected subjects and attachment names, checked by the REAL_FIXTURES_DIR test.
- Hamza: `--only-ext` no longer writes an unreadable container (a damaged .msg under `--only-ext .pdf`); a damaged non-mail Compound File is `damaged-compound-file`, not an Outlook message; a bad RTF CRC with a clean decode is a warning; extract uses `mailsafe.off_timeout` instead of a private global; the write lock is separate from the print lock; regression test that times out at the rename.
- haiku: Authentication-Results read as text, DKIM/SPF/DMARC not re-verified and link targets never fetched or resolved, even with `--show-targets` (security.md); Graph backoff without Retry-After. luna: verify against current Learn docs before a write; evals.json pointed to. mini: .pst and encrypted mail explicit in the task table and support matrix. gpt-oss: new reasons in json-output.md.
- Tests: 52 plus 3 optional (55 with corpora); also pass on Python 3.9.25.

## 0.1.4 (2026-10-13)

- Tariq (top): `text-shows-other-host` fires when the link text names a different host anywhere ("Please visit https://paypal.com now"), not only at the start; file names and email addresses in the text are ignored.
- Tariq: content beats the name. Attachment bytes that are an executable (MZ, ELF, Mach-O), a `#!` script or HTML/script text are high risk (`executable-content:*`) whatever the extension, so `fake.pdf` holding MZ is skipped even with `--only-ext .pdf` (or saved as `.quarantine` with `--include-risky`). A .pdf, image or Office file whose bytes do not match its type is medium (`content-does-not-match-extension`). Applies in inspect and extract.
- Real-file run: 28 public sample .msg and 10 .eml files (MSGReader, msg-extractor, ruby-msg test sets; fetched for testing, not shipped) through all three scripts with no traceback. .msg subjects and attachment names equal extract-msg 0.56.1; 21 non-empty real compressed RTF bodies byte-identical to compressed_rtf 1.0.7, 0 CRC failures, so the CRC check stays an incomplete signal (mistral). An empty RTF stream beside a plain body is now ignored. Compatibility line, formats.md, skill.json and a README Validation table updated (perplexity, mistral, mini, luna, mistral-small).
- haiku: description now "Drafts by default: sends only a draft the user approved, after reading it back"; exit 3 explains that an existing OUTDIR is a setup refusal; fallbacks.md section for a real .msg that gives `complete: false`; attached messages in extract explained; the exact domain rule with its false flags and misses; concrete "never open" examples.
- gemma: json-output.md example results for the common failure states (real output).
- chatgpt: calendar.md table for ambiguous, nonexistent and floating times, unknown zones, invalid dates, RRULE, EXDATE/RECURRENCE-ID and SEQUENCE; Graph recipe 4 says which attachment types `$value` serves; recipe 8 explains the UTC window vs the user's week.
- Tests: 48 plus 4 optional.

## 0.1.3 (2026-10-13)

- An attached Outlook message or TNEF found by its bytes is a container (risk at least medium) whatever its filename or MIME type; extract does not save the container itself, only its attachments, matching the TNEF policy (Tariq N8). Shared `kind_risk` in mailsafe.py used by inspect and extract.
- RTF: `\bin` data running past the end of the stream is reported as truncated (incomplete); `\uc` clamped to 0..8 (Tariq N9, N10).
- extract_attachments.py `--only-ext .pdf,.docx` extension allowlist; never overrides the high-risk skip (gpt-oss).
- New risk reason `content-type-mismatch`: a harmless declared type with an active extension (haiku).
- security.md: operational test for which Authentication-Results to trust, and "unknown from this file" (luna); what the reply-to check will and will not catch (haiku); extraction behaviour for existing folders and interrupted runs (luna).
- formats.md: known-risky variants table (haiku). graph.md and addins.md: "documented, not run" banner (mini).
- Hamza round 3:
  - HIGH: an unclosed `<a href>` (end of input, or a second `<a>` before `</a>`) is now recorded as a link, also in RTF-derived HTML; before, one missing tag hid the link from triage.
  - Extract commit is atomic under `--timeout`: every file write and the final rename hold the watchdog's lock, so a timeout either removes the temp folder (exit 3, nothing left) or, after the rename, is ignored and the real result is printed.
  - Truncated RTF (groups left open, `\bin` past the end) and an attached message that cannot be read (damaged Compound File, or named `.msg` / typed `vnd.ms-outlook` but not one) give `complete: false`. This makes the 0.1.2 RTF truncation line true.
  - inspect_ics.py follows the incomplete policy: bad lines, unmatched END and unclosed components are skipped and listed (exit 1, `--allow-incomplete` for 0); malformed dates such as `DTSTART:2026` get a note.
  - Error and incomplete texts scrubbed of terminal escapes and control characters. REAL_FIXTURES_DIR runs all three scripts, .ics included.
- graph.md: complete recipes with headers, bodies and statuses: message with attachments, attachment bytes, createReply and createForward drafts then approved send, inbox rules list and create with read-back, calendarView in the user's zone, batch responses (perplexity, Hamza).
- README: how to test your own Outlook files with REAL_FIXTURES_DIR, locally (gemini, mistral). Packed-artifact test also checks there are no install-time npm hooks (chatgpt).
- Tests: 47 plus 4 optional (cross-check, TNEF corpus, real files, npm packed-artifact check).

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
