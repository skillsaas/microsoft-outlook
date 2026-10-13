# microsoft-outlook

**TL;DR:** `microsoft-outlook` is a free, MIT-licensed agent skill that teaches AI agents (Claude Code, Cursor, Codex, Gemini CLI and other agents that read SKILL.md skills) to read Outlook mail files offline (`.msg`, `.eml`, `winmail.dat`, `.ics`), gather phishing evidence, save attachments without running them, and use Microsoft Graph or an Office.js add-in without sending mail on their own. Install: `npx skills add skillsaas/microsoft-outlook` or `npm install microsoft-outlook`.

An agent skill (`SKILL.md`) that teaches AI agents to work with Microsoft Outlook mail safely:
read `.msg`, `.eml`, `winmail.dat` and `.ics` files offline, spot phishing, save attachments
without running them, and drive the live mailbox through Microsoft Graph or an Office.js add-in
without ever sending mail on its own.

## Use it when
- a user hands you a `.msg`, `.eml`, `winmail.dat` or `.ics` and asks what is in it;
- someone asks "is this email a scam?" and you need evidence, not a guess;
- attachments must be saved, and some are `.exe`, `.js`, `.iso`, double-extension or
  right-to-left-override tricks;
- a recipient got `winmail.dat` instead of attachments (TNEF);
- a meeting invite's time is in a Windows time zone name, or recurs;
- you automate mail or calendar with Microsoft Graph (drafts, search, calendar view, rules) and
  must pick least-privilege scopes, now that EWS in Exchange Online is being disabled;
- you build an Outlook add-in, or a user on new Outlook asks for a VBA macro;
- you need AQS (Outlook search box) or KQL (Graph `$search`) syntax.

## Install
```bash
npx skills add skillsaas/microsoft-outlook    # skills CLI, reads SKILL.md at the repo root
npm install microsoft-outlook                 # files land in node_modules/microsoft-outlook/
# Planned, not yet published: npx @skillsaas/cli add microsoft-outlook
```
Or copy this folder into your agent's skills folder (for example `.claude/skills/` or
`.agents/skills/`). No pip install on macOS or Linux: the scripts use the Python 3.9+ standard library only. On
Windows, `inspect_ics.py --tz` needs time zone data: `python -m pip install tzdata`.

Try it: `python scripts/inspect_mail.py tests/fixtures/phish.eml`, then `python tests/smoke_test.py`.

## What it does
- `inspect_mail.py`: read-only report for `.msg`, `.eml` and `winmail.dat`: headers, SPF/DKIM/DMARC results, links, HTML tricks, attachments and risks.
- `extract_attachments.py`: saves attachments, including nested ones, into a new folder with safe names; risky types are skipped or quarantined.
- `inspect_ics.py`: meeting invites with methods, times and Windows time zones, recurrence, links and alarms.
- References for Microsoft Graph mail and calendar with least-privilege scopes, rules, signatures, AQS and KQL search, and Outlook add-ins. Drafts by default; sends only a draft the user approved.
- Python 3.9+ standard library only; smoke tests run in CI on Linux, macOS and Windows.

## FAQ
**What is the microsoft-outlook skill?**
An Agent Skills package (a `SKILL.md` plus references and Python scripts) that tells an AI agent how to handle Outlook mail files and automation safely. It is unofficial and not affiliated with Microsoft.

**How do I open a .msg file without Outlook?**
`python scripts/inspect_mail.py FILE.msg --json` shows headers, body, links and attachments; `extract_attachments.py` saves the attachments.

**What is winmail.dat and how do I get the attachments out?**
It is a TNEF file Outlook sends to some mail clients. `extract_attachments.py winmail.dat NEW_DIR` reads it and saves the files inside.

**Can it tell me if an email is phishing?**
It reports evidence (authentication results, mismatched link text, risky attachments, punycode hosts) for the agent to explain. It is triage, not a verdict or a malware scan.

**Will the agent send email on its own?**
No. The skill drafts by default and sends only a draft the user approved after it was read back.

**Does it work on Windows?**
Yes; for `inspect_ics.py --tz` on Windows run `python -m pip install tzdata`.

## Contents
| Path | What |
| :--- | :--- |
| `SKILL.md` | Router: decision guide, never-do and ask-first lists, workflow, exit codes, checklist |
| `references/` | Formats (MSG, MIME, TNEF, PST), security, Graph mail, calendar, rules and signatures, search, add-ins, recipes, fallbacks, troubleshooting |
| `scripts/inspect_mail.py` | Read-only report for .msg, .eml, winmail.dat: headers, auth, links, HTML traps, attachments, risks |
| `scripts/extract_attachments.py` | Save attachments (and nested ones) into a new folder with safe names; risky ones skipped or quarantined |
| `scripts/inspect_ics.py` | Read-only report for invites: method, times with zones, recurrence, links, alarms |
| `scripts/mailsafe.py`, `mailparse.py`, `msgcfb.py`, `tnef.py`, `rtfbody.py` | Helpers: text and link checks, the .msg (MS-CFB/MS-OXMSG), TNEF (MS-OXTNEF) and compressed RTF (MS-OXRTFCP) readers |
| `scripts/windows_zones.json`, `scripts/LICENSE-CLDR.txt` | CLDR Windows-to-IANA zone table and its Unicode License v3 |
| `tests/smoke_test.py`, `tests/make_fixtures.py` | Tests and the synthetic fixture builder |
| `SECURITY.md` | Threat model and how to report a problem |

## Test it on your own Outlook files
## Validation

| What | Result |
| :--- | :--- |
| Python, OS | 3.13.5 and 3.9.25 on Linux x86_64 by hand; CI on ubuntu, macos and windows runners with Python 3.9 and 3.13 (smoke tests only; no Outlook) |
| Synthetic fixtures | .msg (cross-read by olefile 0.47, extract-msg 0.56.1), .eml, winmail.dat, .ics |
| TNEF | tnefparse 1.4.0 sample corpus, 19 files, results equal |
| Shipped public samples | 7 MIT-licensed real files in `tests/samples/` (MSGReader, ruby-msg), checked in every default test run against expected subjects and attachment names |
| CI | `.github/workflows/test.yml` (Linux, Windows, macOS; Python 3.9 and 3.13) runs on every push from 0.1.8 (see the Actions tab) |
| Public sample files (31 more, fetched) | 28 .msg + 10 .eml from MSGReader, msg-extractor and ruby-msg test sets: no traceback; .msg subjects and attachment names equal extract-msg; 21 real compressed RTF bodies byte-identical to compressed_rtf |
| Not run | live Graph tenant, Office.js add-in, VBA, a real .pst, encrypted or IRM mail, known Outlook versions |

To repeat the full public-sample run: `python3 tests/fetch_public_samples.py DIR` downloads the 38 files
(pinned by commit and SHA-256; MIT and GPL-3.0, so they are not shipped), then
`REAL_FIXTURES_DIR=DIR python3 tests/smoke_test.py` checks subjects and attachment names against
`tests/public_samples_expected.json`. `tests/evals.json` holds the agent-level evals.

The sample files' Outlook versions are unknown. To check your own files, without uploading
anything anywhere:

```sh
mkdir ~/outlook-samples            # copy .msg, .eml, winmail.dat and .ics files here
REAL_FIXTURES_DIR=~/outlook-samples python3 tests/smoke_test.py
```

Every file goes through all three scripts (inspect, extract into a temp folder, ics). The test
fails if any script crashes or prints something other than JSON. Results stay on your machine. If
a file fails, open an issue with the script, the error line and the Outlook version, never the file
itself unless it holds nothing private.

## Status and maintenance
Version 0.1.10, published on npm and GitHub (pre-1.0). Smoke tests pass in CI on Linux, macOS and Windows (Python 3.9 and 3.13); Graph, Office.js and VBA parts
are documented from Microsoft Learn and were not run against a tenant. The `.msg` fixture is
synthetic (built from the specs and cross-read by olefile and extract-msg); no real Outlook-saved
.msg was available. Each version is reviewed by a panel of people and AI agents; CHANGELOG.md says
what changed. Until 1.0, a minor bump may change flags or JSON fields.

## Trademark
Unofficial. Not affiliated with, endorsed by or sponsored by Microsoft. Microsoft and Outlook are
trademarks of the Microsoft group of companies.

License: MIT.
