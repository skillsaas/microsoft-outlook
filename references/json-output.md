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
- `risk` on one item: `high` = a strong signal on its own (blocked type, mismatched link text,
  DMARC fail, form); `medium` = worth naming, weak alone; `info` = context, never raises
  `overall_risk`; `low` = nothing found by that check.
- `overall_risk` = the highest item level (`info` counts as `low`). It is a triage signal, not
  a verdict or a probability, and it covers only the checks that ran (see `not_checked`).

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
| exit 1 `incomplete` | say the report is partial and what was missed; ask before `--allow-incomplete` |
| exit 1 `risky-skipped` (extract) | name the skipped files; `--include-risky` only on approval |
| exit 2 | ask for the original file |
| exit 3 | name the limit; raise it only with the user's OK |
