# Troubleshooting

Last verified: 2026-10-13 (sources listed at the end; not re-checked since).

| Symptom | Check | Fix |
| :--- | :--- | :--- |
| Recipient sees only `winmail.dat` | `inspect_mail.py winmail.dat` shows the files | `extract_attachments.py`; sender sends HTML or plain text |
| `not an .eml, .msg or TNEF file` (exit 2) | First bytes: `D0CF11E0` is .msg, header lines are .eml | Ask for the original; a `.msg` renamed from `.oft` or a zip is not mail |
| `unsupported CFB header` or `bad directory tree` | File truncated or not Outlook's | Ask the user to save the message again from Outlook |
| Body empty, or `RTF body not decoded` under `incomplete` | RTF-only message the decoder could not read | `fallbacks.md` RTF section |
| `no-authentication-results` | Saved .msg from Outlook often lacks transport headers | Say the sender could not be verified from the file; check in Outlook (message details) |
| `no time zone database` with `--tz` (exit 2) | Windows Python ships no zone data | `python -m pip install tzdata`, or run without `--tz` (times listed as written) |
| Wrong meeting time | `tzid`, `iana`, `local_time` in `inspect_ics.py --tz` output | Windows names are mapped with CLDR; a DST gap or overlap needs the organizer's confirmation |
| Graph `401` after working earlier | token expired | Let the connector or MSAL get a new token; never paste one by hand |
| Sign-in asks for admin approval | scope needs admin consent in this tenant | Stop; tell the user which scope and why; do not try other scopes |
| Sign-in blocked by policy, or device code refused | Conditional Access | The organization's decision: report it, do not switch client or flow |
| `complete: false` / `parse-incomplete` | `incomplete` list | Say the report is partial; ask for the original file; raise a cap only with the user's OK |
| Exit 3 "time limit" or "over N attachments" | the error text | A hostile or huge file; ask before raising `--timeout` or `--max-attachments` |
| Recurring meeting shows once | `rrule` present | The script does not expand RRULE; read the rule to the user |
| Attachment missing from extraction | `skipped` in `manifest.json` | High risk, reference attachment, inline (`--skip-inline`) or over a cap |
| `OUTDIR exists` (exit 3) | | Choose a new folder; nothing is overwritten |
| Graph `InefficientFilter` | `$orderby` vs `$filter` | Put `$orderby` properties first in `$filter`, same order |
| Graph `ErrorAccessDenied` | Token scopes, mailbox access | Tell the user which scope is missing; do not widen on your own |
| Graph `429` or `503` | `Retry-After` header | Wait that long; with none, 2, 4, 8, 16 s; stop after 5 tries and tell the user |
| Graph `400` | the error `message`; JSON body and `$filter` syntax | Fix the request; do not retry unchanged |
| Graph `403` (not admin consent) | scope granted but mailbox or folder not shared | Tell the user; never widen scopes or switch mailbox |
| Graph `404` on a message id | Moved or deleted since it was listed (ids can change on move) | List again or search by subject and date; do not guess an id |
| A write timed out or gave `5xx` | Whether it happened anyway | Look first (Sent Items, calendar, rule list), then retry only if it is not there (safety rule 7) |
| Exit 3 time limit on one run, success on the next | Run time close to `--timeout` | Normal jitter: each outcome is all or nothing |
| EWS calls fail in Exchange Online since October 2026 | EWS phased disablement | Move to Graph (`graph.md`) |
| VBA macro "does nothing" | User is on new Outlook | New Outlook has no VBA; `addins.md` |
| Add-in API undefined | Requirement set | `Office.context.requirements.isSetSupported("Mailbox", "1.x")` |
| Search finds nothing | Space after the colon, wrong scope, .pst not open | `search.md` |
