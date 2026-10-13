# Troubleshooting

| Symptom | Check | Fix |
| :--- | :--- | :--- |
| Recipient sees only `winmail.dat` | `inspect_mail.py winmail.dat` shows the files | `extract_attachments.py`; sender sends HTML or plain text |
| `not an .eml, .msg or TNEF file` (exit 2) | First bytes: `D0CF11E0` is .msg, header lines are .eml | Ask for the original; a `.msg` renamed from `.oft` or a zip is not mail |
| `unsupported CFB header` or `bad directory tree` | File truncated or not Outlook's | Ask the user to save the message again from Outlook |
| Body empty, `rtf-body-not-decoded` | RTF-only message | `fallbacks.md` RTF section |
| `no-authentication-results` | Saved .msg from Outlook often lacks transport headers | Say the sender could not be verified from the file; check in Outlook (message details) |
| Wrong meeting time | `tzid` in `inspect_ics.py` output | Map Windows zone names with CLDR; give the time in the user's zone |
| Recurring meeting shows once | `rrule` present | The script does not expand RRULE; read the rule to the user |
| Attachment missing from extraction | `skipped` in `manifest.json` | High risk, reference attachment, inline (`--skip-inline`) or over a cap |
| `OUTDIR exists` (exit 3) | | Choose a new folder; nothing is overwritten |
| Graph `InefficientFilter` | `$orderby` vs `$filter` | Put `$orderby` properties first in `$filter`, same order |
| Graph `ErrorAccessDenied` | Token scopes, mailbox access | Tell the user which scope is missing; do not widen on your own |
| Graph `429` | `Retry-After` header | Wait and retry |
| EWS calls fail in Exchange Online since October 2026 | EWS phased disablement | Move to Graph (`graph.md`) |
| VBA macro "does nothing" | User is on new Outlook | New Outlook has no VBA; `addins.md` |
| Add-in API undefined | Requirement set | `Office.context.requirements.isSetSupported("Mailbox", "1.x")` |
| Search finds nothing | Space after the colon, wrong scope, .pst not open | `search.md` |
