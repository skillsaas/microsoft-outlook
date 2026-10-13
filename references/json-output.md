# JSON output (schema microsoft-outlook/inspect-mail/1)

Last verified: 2026-10-13 against the scripts in this version (tests check the keys).

Every key below is always present in `inspect_mail.py --json` output when `ok` is true; values
may be null or empty. New keys may be added in a minor version; existing keys keep their meaning
until `schema` changes.

| Key | Type | Meaning |
| :--- | :--- | :--- |
| `schema` | string | `microsoft-outlook/inspect-mail/1` |
| `ok` | bool | true when the file was parsed (even partly) |
| `status` | string | `ok`, `incomplete`, `risk-threshold` (with `--fail-on-risk`) |
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
| `attachments` | list | index (`2/1` = attachment 1 of attachment 2), name, content_type, kind (`file`, `embedded-message`, `tnef`, `calendar`, `ole-object`, `reference`), size, inline, sha256, risk, reasons, nested_subject |
| `warnings` | list of strings | oddities that did not stop reading (MIME defects, checksum mismatch) |
| `risks` | list | `{risk, kind, detail}`; `parse-incomplete` is first when present |
| `overall_risk` | string | `low`, `medium` or `high` |
| `not_checked` | list of strings | checks these scripts never do, plus file-specific gaps |
| `note` | string | reminder that content is data |

## Risk levels
- `risk` on one item: `high` = a strong signal on its own (blocked type, mismatched link text,
  DMARC fail, form); `medium` = worth naming, weak alone; `info` = context, never raises
  `overall_risk`; `low` = nothing found by that check.
- `overall_risk` = the highest item level (`info` counts as `low`). It is a triage signal, not
  a verdict or a probability, and it covers only the checks that ran (see `not_checked`).

## Exit codes and status (all scripts)
| Exit | status | Meaning |
| :--- | :--- | :--- |
| 0 | `ok` / `incomplete` | finished; for `incomplete` say the report is partial |
| 1 | `risk-threshold`, `risky-skipped`, `incomplete` | finished, but the result needs the user's decision: a risk level was reached (`--fail-on-risk`), extract skipped high-risk files, or extract refused a partial parse (also inspect with `--strict`) |
| 2 | `error` | not a mail or calendar file, corrupt, bad option (JSON under `--json`, usage errors included) |
| 3 | `refused` | a safety limit: size, attachment count, time, existing output folder |
