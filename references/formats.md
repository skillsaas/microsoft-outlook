# Outlook file formats

Last verified: 2026-10-13 (sources listed at the end; not re-checked since).

What each file is, what the bundled readers decode, and what they leave out. Sources are
Microsoft Open Specifications (learn.microsoft.com/openspecs) and IETF RFCs, read 2026-10-13.

## Support matrix (what this skill does with each format)
| Format | Read by the scripts | Extract attachments | Tested on | Not covered |
| :--- | :--- | :--- | :--- | :--- |
| attached `.msg` or `winmail.dat` inside any message | yes since 0.1.2: detected by bytes, whatever the name or MIME type, and parsed as a nested message | its attachments too | synthetic | |
| `.eml` (MIME) | yes, `inspect_mail.py` | yes | stdlib parser; synthetic fixtures | S/MIME decryption |
| `.msg` | yes | yes | synthetic fixture cross-checked with olefile and extract-msg; 28 public sample .msg files (see below) | controlled corpus of known Outlook versions; named properties |
| `winmail.dat` (TNEF) | yes | yes | 19 tnefparse sample files | MAPI property types outside MS-OXTNEF basics; unusual corporate TNEF may not parse (reported as incomplete, never as clean) |
| compressed RTF body (in .msg or TNEF) | yes since 0.1.1 (`body-from-rtf` flag) | n/a | spec-built streams; cross-check with compressed_rtf; 21 real bodies from public samples (not from known Outlook builds) | RTF formatting, embedded pictures and objects |
| `.ics`, `.vcs` | yes, `inspect_ics.py` | n/a | synthetic fixture | RRULE expansion, VTIMEZONE rule evaluation |
| `.pst`, `.ost` | **no: orientation only** | no | nothing; readpst was run only on a non-PST file | everything; use classic Outlook or readpst |
| `.oft` | as `.msg` | as `.msg` | not tested | |
| .eml attached as octet-stream or renamed (`invoice.pdf`) | since 0.1.7: read as a nested message by its header block (three known mail headers, two of From, Date, Message-ID, Received, MIME-Version, Subject) | its attachments | synthetic | |
| uuencoded block in text | reported (`uuencoded-content`), not decoded | no | synthetic | decoding |
| damaged Compound File (not .msg/.oft by name or type) | flagged `damaged-compound-file`, incomplete; not treated as a message | held back | synthetic | |
| encrypted, S/MIME, IRM | headers only | no | not tested | decryption |

## Known-risky variants (real-world limits)
Patterns that real Outlook files contain and how far the scripts go with them. "Synthetic" means a
spec-built fixture covers it; "public samples" means the real-file run below exercised it.

| Variant | What the scripts do | Covered by |
| :--- | :--- | :--- |
| winmail.dat inside a .msg or .eml | parsed as nested TNEF, contents listed and extracted | synthetic, tnefparse corpus |
| .msg attached inside .eml, renamed (`invoice.bin`) | found by bytes, container risk, contents extracted | synthetic |
| meeting forward (.msg with an invite) | message read; the invite is an attachment for `inspect_ics.py` | synthetic .ics only |
| RTF-only body (no plain text or HTML) | decoded; links taken from `\fromhtml1` HTML | spec-built streams |
| S/MIME signed (`multipart/signed`) | parts read; signature **not** verified | stdlib MIME parser |
| S/MIME or IRM encrypted (`smime.p7m`, `.rpmsg`) | listed as an attachment; content unreadable, say so | not tested |
| named MAPI properties, Unicode vs ANSI string props | common string props read; named props ignored | synthetic |
| RRULE with exceptions across a DST change | RRULE printed as written, not expanded; DST gaps flagged on stated times | synthetic |

## Which file is which
Detect by content, not extension; `inspect_mail.py` does this.
| File | First bytes | What it is | Spec |
| :--- | :--- | :--- | :--- |
| `.msg` | `D0 CF 11 E0 A1 B1 1A E1` | Compound File Binary holding one MAPI message | MS-CFB, MS-OXMSG |
| `.eml` | header lines (`From:`, `Received:` ...) | Internet message, MIME | RFC 5322, RFC 2045 to 2049 |
| `winmail.dat`, `application/ms-tnef` | `78 9F 3E 22` (0x223E9F78 little endian) | TNEF stream: Outlook's rich message wrapper | MS-OXTNEF |
| `.ics`, `text/calendar` | `BEGIN:VCALENDAR` | iCalendar; Outlook adds `X-MICROSOFT-*` properties | RFC 5545, RFC 5546 (iTIP), MS-OXCICAL |
| `.pst`, `.ost` | `!BDN` | Outlook data file (personal store, offline cache) | MS-PST |
| `.oft` | as `.msg` | Outlook template (a .msg with a template class) | MS-OXMSG |

## .msg (MS-OXMSG on MS-CFB)
- A Compound File is a small FAT file system: 512 or 4096 byte sectors, a FAT, a mini FAT for
  streams under 4096 bytes, and a red-black directory tree of storages and streams.
- The root storage is the message. Properties live in streams named `__substg1.0_PPPPTTTT`
  (property id, then type: `001F` UTF-16 string, `001E` 8-bit string, `0102` binary, `000D`
  object). Fixed-size properties (dates, flags, integers) are 16-byte entries in
  `__properties_version1.0`, after a 32-byte header at the top level, 24 bytes in an embedded
  message, 8 bytes in recipient and attachment storages.
- Recipients: storages `__recip_version1.0_#00000000` and up; attachments:
  `__attach_version1.0_#00000000` and up; named property map: `__nameid_version1.0`.
- Useful property ids read by `msgcfb.py`: `0x0037` subject, `0x1000` plain body, `0x1013` HTML
  body, `0x1009` compressed RTF, `0x007D` transport headers (the original Internet headers, if the
  message came from outside), `0x0C1A`/`0x0C1F`/`0x5D01` sender name, address, SMTP address,
  `0x0E04`/`0x0E03` display To/Cc, `0x001A` message class, `0x0039` submit time, `0x3FDE`
  Internet code page. Attachments: `0x3707` long file name, `0x3704` 8.3 name, `0x3701` data
  (binary, or an embedded message storage `__substg1.0_3701000D`), `0x3705` method (1 by value,
  5 embedded message, 6 OLE, 2 to 4 and 7 references), `0x370E` MIME type, `0x3712` content id,
  `0x7FFE` hidden.
- A sent-from-Outlook .msg often has no transport headers, so there are no
  `Authentication-Results` to read; say so.
- RTF hardening (0.1.2): `\uN` values outside Unicode become U+FFFD, an unknown `\ansicpg`
  falls back to cp1252 (checked with `codecs.lookup`), `\binN` data is skipped unread, a MELA
  stream with a nonzero CRC or an LZFu CRC mismatch, a missing end marker, nesting over 200
  groups or the 10 M character output cap mark the parse incomplete. Any other decoder error
  becomes "RTF body not decoded" under `incomplete`; the rest of the message is still reported.
- **Compressed RTF** (`0x1009`, MS-OXRTFCP) is decoded when it is the only body (0.1.1,
  `rtfbody.py`): LZFu decompression with the spec's CRC check, then HTML is taken back out of
  RTF that wraps HTML (`\fromhtml1`, MS-OXRTFEX) so links are checked, or plain text from other
  RTF. The report carries the `body-from-rtf` flag.
- **Not decoded here**: named properties, OLE attachment contents,
  S/MIME (`IPM.Note.SMIME*`, flagged), encrypted IRM messages, and .msg files over the size caps.
- Hardening in `msgcfb.py`: signature and header checks, every sector chain checked for loops and
  out-of-range sectors, directory walk with a visited set, stream size cap (64 MB), nesting depth
  cap (4). Malformed input gives exit 2 with a reason, tested with truncated, looping, cyclic and
  random-byte files.

## .eml and MIME
- Parsed with Python's `email` package (`policy.default`). Parts are walked without descending
  into attached messages (`message/rfc822`), which are parsed as nested messages instead.
- The first `text/plain` and `text/html` parts that are not attachments are the body; everything
  else (named parts, `Content-Disposition: attachment`, non-text types) is an attachment.
- `multipart/signed` and `application/pkcs7-mime` are flagged `signed` or `encrypted`; signatures
  are not verified and encrypted content is not decrypted.
- MIME defects reported by the parser are listed in `warnings` (first 20).
- Encoded-word subjects and file names (RFC 2047, RFC 2231) are decoded by the parser, then
  cleaned of control, bidi and zero-width characters before printing.

## TNEF (winmail.dat)
- Classic Outlook sends TNEF when a message uses Rich Text format and the recipient is not set
  to receive plain or HTML. Non-Outlook clients then show only `winmail.dat`. The fix on the
  sender side is to send in HTML or plain text; the admin side is the remote domain setting for
  TNEF in Exchange (documented in Exchange Online remote domain settings; not tested here).
- Stream: signature, a 16-bit key, then attributes: level byte (1 message, 2 attachment),
  32-bit attribute id (type in the high 16 bits), 32-bit length, data, 16-bit checksum (sum of
  data bytes modulo 65536).
- Attachments start at `attAttachRendData`; the name is in `attAttachTitle` (often 8.3), the
  long name in `attAttachment` MAPI properties (`0x3707`), the bytes in `attAttachData` or in
  `0x3701` (an object type with a 16-byte interface id first, for embedded messages and OLE).
- `tnef.py` reports a checksum mismatch as a warning and keeps going. A truncated tail or an
  unreadable MAPI property block marks the parse incomplete (0.1.1: no longer a quiet ok); a
  length that runs past the data is exit 2.

## Caps and partial parses (0.1.1)
| Cap | Default | When reached |
| :--- | :--- | :--- |
| Input size | 50 MB inspect, 150 MB extract (`--max-bytes`) | exit 3 |
| Attachments, nested included | 500 (`--max-attachments`) | exit 3, nothing written |
| MIME boundaries incl. RFC 2231 `boundary*=` forms | 2,000 | exit 3, before parsing |
| MIME nesting | 50 levels | deeper parts unread: `complete: false` |
| Nested messages (.msg in .msg, rfc822, TNEF) | 4 levels | deeper ones unread: `complete: false` |
| Wall clock | 60 s inspect, 120 s extract (`--timeout`) | exit 3 |
A partial parse is never reported as clean: inspect adds a `parse-incomplete` risk and lists
what was missed in `incomplete`; extract writes nothing unless `--allow-incomplete`.

## Reader comparison (tested on the box, 2026-10-13)
| Check | Result |
| :--- | :--- |
| `tests/fixtures/sample.msg` (written from MS-CFB and MS-OXMSG by `make_fixtures.py`) read by olefile 0.47 and extract-msg 0.56.1 | Same subject, sender, To, Cc, body, 3 attachments, embedded message and its attachment bytes. Run it with `XCHECK_PYTHON=/path/to/python tests/smoke_test.py` |
| `tnef.py` against tnefparse 1.4.0 on its 19 sample `.tnef` files | Same attachment count and names on all 19 (29 attachments). Bytes equal except where tnefparse strips trailing NUL bytes from data and keeps the 16-byte interface id in front of an OLE object; `tnef.py` keeps the data whole and drops the id, giving a valid Compound File |
| Public sample .msg and .eml files (0.1.4) | 28 public sample .msg and 10 .eml files from the test sets of MSGReader (MIT), msg-extractor (GPL-3.0) and ruby-msg (fetched for testing, not shipped: their licenses differ). All 38 went through inspect, extract and REAL_FIXTURES_DIR with no traceback. 37 complete; `TestWithAttachmentsAndInlines.eml` is correctly incomplete (two message/rfc822 parts hold plain text, not messages). All 28 .msg subjects and top-level attachment names equal extract-msg 0.56.1, including an attached .msg, an inner mail with attachments, RTF, HTML and plain bodies, French and Russian text, contacts and notes. 24 compressed RTF streams: 21 non-empty, all byte-identical to compressed_rtf 1.0.7, 0 CRC failures (since 0.1.5 a CRC mismatch alone is a warning); 3 were empty beside a plain body and are now ignored. Outlook versions of the samples are unknown |
| Python `email` on `.eml` | Standard library behavior; fixtures cover nested `message/rfc822`, TNEF inside MIME, RFC 2231 names |

## .pst and .ost (orientation only)
This section is orientation, not a tested procedure: nothing here was run on a real .pst.
- MS-PST describes the format (NDB layer, LTP heap and tables, messaging layer). No reader is
  bundled: a .pst can hold years of mail and is better opened by a tool built for it.
- Options, in order: classic Outlook (File > Open & Export > Open Outlook Data File, or Import/
  Export); new Outlook (.pst support is partial and rolling out, per Microsoft's feature
  comparison page, 2026); `readpst` from libpst in a sandbox (`fallbacks.md`).
- An `.ost` is a cache of a server mailbox; prefer reading the mailbox through Graph.

## Sources
- MS-CFB: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-cfb/
- MS-OXMSG: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxmsg/
- MS-OXTNEF: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxtnef/
- MS-OXRTFCP: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfcp/
- MS-PST: https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-pst/
- MS-OXCICAL: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxcical/
- RFC 5322, RFC 2045, RFC 2231, RFC 5545, RFC 5546: https://www.rfc-editor.org/
