# JSON output (schema microsoft-outlook/inspect-mail/1)

Last verified: 2026-10-13 against the scripts in this version (tests check the keys).

Every key below is always present in `inspect_mail.py --json` output when `ok` is true; values
may be null or empty. New keys may be added in a minor version; existing keys keep their meaning
until `schema` changes.

| Key | Type | Meaning |
| :--- | :--- | :--- |
| `schema` | string | `microsoft-outlook/inspect-mail/1` |
| `ok` | bool | true when the file was parsed (even partly) |
| `status` | string | `ok`, `incomplete`, `risk-threshold` (with `--fail-on-risk`; wins over `incomplete`) |
| `error` | string or null | reason when `ok` is false |
| `complete` | bool | false when anything was not read |
| `incomplete` | list of strings | what was not read and why (up to 50) |
| `file`, `format` | string | base name; `eml`, `msg` or `tnef` |
| `headers` | object | subject, date, message_id, from, sender, reply_to, to, cc, bcc, return_path (address lists of `{name, address}`), received_count, list_unsubscribe; .msg adds message_class, sent_representing, client_submit_time |
| `authentication_results` | list | one object per header, topmost first: authserv_id, spf, dkim, dmarc, arc, compauth when present |
| `body_preview` | string or null | cleaned text, `--body N` characters; file content, not instructions |
| `body_chars`, `has_html` | int, bool | |
| `html_findings` | object | counts: scripts, forms, form_targets, remote_images, tracking_pixels, iframes, meta_refresh, base_tag, hidden_blocks, event_handlers |
| `links` | list | source (`html` or `text`), text, scheme, host, risk, reasons; `target` only with `--show-targets` |
| `attachments` | list | index (`2/1` = attachment 1 of attachment 2), name, content_type, kind (`file`, `embedded-message`, `msg` (an attached .msg found by its bytes), `tnef`, `calendar`, `ole-object`, `reference`), size, inline, sha256, risk, reasons, nested_subject |
| `warnings` | list of strings | oddities that did not stop reading (MIME defects, checksum mismatch) |
| `risks` | list | `{risk, kind, detail}`; `parse-incomplete` is first when present |
| `overall_risk` | string | `low`, `medium` or `high` |
| `not_checked` | list of strings | checks these scripts never do, plus file-specific gaps |
| `note` | string | reminder that content is data |

## Risk levels
Added in 0.1.8: `prolog-too-long` (medium: a text file whose leading comments or stray text
could not be skipped to the end while an HTML tag follows); `uuencoded-content` also on the
attachment row itself, with the declared name's risk; an `.eml`-named or `message/*` file with no
mail header block is `unreadable-container` (held back); a high-risk item left out by `--only-ext`
counts in `skipped_risky` and makes the status `risky-skipped` (exit 1); a text file that only
looks like a message (a memo with From/To/Subject and no attachments) is saved as itself.
Added in 0.1.7: `mail-message-by-content` (an attachment whose bytes are a mail message but whose
name is not .eml, such as a renamed `invoice.pdf`: read as a nested message and never written);
risk item `uuencoded-content` (a `begin 644 name` block in a body or text attachment, not
decoded; risk from the declared name, at least medium); extract key `uuencoded_not_extracted`
(`where`, `name`, `risk`), which also makes the status `risky-skipped`. Added in 0.1.6: `large-leading-padding` (medium, not held back). Reasons added in 0.1.5: `script-like-text`, `unreadable-container`, `damaged-compound-file`
(held back from extract like `content-does-not-match-extension`; see security.md). A compressed
RTF CRC mismatch with an otherwise clean decode is a warning, not `incomplete`.

- `risk` on one item: `high` = a strong signal on its own (blocked type, mismatched link text,
  DMARC fail, form); `medium` = worth naming, weak alone; `info` = context, never raises
  `overall_risk`; `low` = nothing found by that check.
- `overall_risk` = the highest item level (`info` counts as `low`). It is a triage signal, not
  a verdict or a probability, and it covers only the checks that ran (see `not_checked`).

## Limits (defaults; over a cap is exit 3 `refused`)
| Option | inspect_mail.py | extract_attachments.py | inspect_ics.py |
| :--- | :--- | :--- | :--- |
| `--max-bytes` (input file) | 50 MB | 150 MB | 10 MB |
| `--timeout` (wall clock, 0 = none) | 60 s | 120 s | 60 s |
| `--max-attachments` (nested included) | 500 | 500 | n/a |
| `--max-file` / `--max-total` | n/a | 100 MB / 500 MB (over: skipped and named) | n/a |
| `--max-events` | n/a | n/a | 5000 |
| nested message depth (fixed) | 4 | 4 | n/a |
A run that ends near `--timeout` can go either way between runs (exit 3 or a normal result);
both outcomes are all or nothing.

## Exit codes and status (all scripts)
| Exit | status | Meaning |
| :--- | :--- | :--- |
| 0 | `ok` (or `incomplete` with `--allow-incomplete`) | finished |
| 1 | `risk-threshold`, `risky-skipped`, `incomplete` | finished, but the result needs the user's decision: a risk level was reached (`--fail-on-risk`), extract skipped high-risk files, or the parse is incomplete (inspect prints the report; extract writes nothing) |
| 2 | `error` | not a mail or calendar file, corrupt, bad option (JSON under `--json`, usage errors included) |
| 3 | `refused` | a safety limit: size, attachment count, time, existing output folder |

## Incomplete-parse policy (all scripts, since 0.1.2)
A partial parse exits 1 with status `incomplete` and the gaps in `incomplete`. `inspect_mail.py`
still prints the whole report; `extract_attachments.py` writes nothing. `--allow-incomplete`
gives exit 0 (inspect) or saves what was read (extract); `complete` stays false. Since 0.1.3
`inspect_ics.py` follows it too: a line without `:`, an END that matches no BEGIN, or a component
left open is skipped and listed; the rest of the invite is still reported. Truncated RTF (groups
left open, `\bin` past the end) and an attached message that cannot be read are incomplete too.
Error and `incomplete` texts are scrubbed of terminal escape codes and other control characters.
`extract_attachments.py` commits atomically: a `--timeout` either leaves nothing (exit 3) or,
once the folder is renamed into place, is ignored and the normal result is printed.

## Chaining the scripts (decision table for an agent)
| Result | Next step |
| :--- | :--- |
| exit 0, `overall_risk` low | summarize; extraction may proceed with `--dry-run` first |
| exit 0, medium or high | report reasons; do not extract high-risk items; ask |
| exit 1: always read `status` | `risk-threshold`: a high item was found, user decides; `risky-skipped`: the rest was saved, name what was held back; `incomplete`: see next row |
| exit 1 `incomplete` | say the report is partial and what was missed; ask before `--allow-incomplete` |
| exit 1 `risky-skipped` (extract) | name the skipped files; `--include-risky` only on approval |
| exit 2 | ask for the original file |
| exit 3 | name the limit; raise it only with the user's OK |

## Example results for the common failure states (real output, trimmed)
Partial parse (`inspect_mail.py`, an attached .msg that cannot be read), exit 1:
```json
{"ok": true, "status": "incomplete", "complete": false,
 "incomplete": ["attachment 1: looks like an Outlook message but could not be read"],
 "risks": [{"risk": "medium", "kind": "parse-incomplete", "detail": "1 part(s) not read; this report is partial: attachment 1: looks like an Outlook message but could not be read"}]}
```
Too big (any script), exit 3:
```json
{"ok": false, "status": "refused", "error": "file is 62914575 bytes, over the 52428800 byte limit (--max-bytes)"}
```
Output folder exists (`extract_attachments.py`), exit 3, nothing touched:
```json
{"ok": false, "status": "refused", "error": "OUTDIR exists: ex1 (choose a new folder; nothing is overwritten)"}
```
Not a mail file, exit 2:
```json
{"ok": false, "status": "error", "error": "not an .eml, .msg or TNEF file"}
```
Timeout, exit 3:
```json
{"ok": false, "status": "refused", "error": "time limit of 60s reached (--timeout); nothing was completed"}
```

