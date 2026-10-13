# Fallbacks

## No Python 3.9+
The scripts need Python 3.9 or later (zoneinfo, standard library only). Without it: ask the
user to open the message in Outlook and use View message source / message details, or save the
MIME from Graph (`/$value`) for later. Do not install system packages without asking.

## .pst and .ost files
No bundled reader. In order of preference:
1. **Classic Outlook**: File > Open & Export > Open Outlook Data File, then search or export.
2. **New Outlook**: .pst support is partial and rolling out (Microsoft feature comparison page).
3. **readpst** (libpst, GPL, not a Microsoft tool), in a sandbox with no network and only the
   input and an output folder visible. Tested on the box: libpst 0.6.76 runs under the command
   below and fails cleanly on a non-PST file; not tested on a real .pst.
```bash
mkdir -p ./pst-out
bwrap --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
      --ro-bind "$PWD/archive.pst" /in/archive.pst --bind "$PWD/pst-out" /out \
      --dev /dev --proc /proc --tmpfs /tmp --unshare-all --die-with-parent --new-session \
      readpst -e -8 -o /out /in/archive.pst
```
   `-e` writes one file per message with extensions (from `readpst -h`, 0.6.76), `-8` prefers
   UTF-8 bodies, `-D` includes deleted items, `-o` sets the output folder. Then run
   `inspect_mail.py` on the resulting files, never open their attachments. On macOS or Windows
   there is no bwrap: use classic Outlook, or a disposable VM.
4. For an .ost: read the server mailbox through Graph instead; an .ost belongs to a profile.

## RTF-only bodies (`rtf-body-not-decoded`)
Some .msg and TNEF messages carry only compressed RTF (MS-OXRTFCP). The inspector does not
decode it. Ask the user to save the message as HTML or forward it as an attachment from new
Outlook or Outlook on the web, or fetch the MIME through Graph `/$value` (Exchange builds the
MIME; whether it carries an HTML body for an RTF-only item was not tested here).

## Encrypted or signed mail
S/MIME (`smime`, `encrypted`) and Microsoft Purview message encryption cannot be read from the
file. Ask the user to open it in Outlook, which holds the keys. Do not ask for private keys.

## No Graph access
Without a registered app and consent, use files: ask the user to save the messages from Outlook
(classic Outlook saves .msg by drag and drop or Save As), or export a .pst from classic.

## The user is on new Outlook and wants a macro
New Outlook does not run VBA. Offer: a Power Automate flow, a Graph script the user runs, an
Office.js add-in, or classic Outlook if they still have it.

## Tool and reader comparison
| Need | Bundled | Alternative | Notes |
| :--- | :--- | :--- | :--- |
| .msg fields and attachments | `inspect_mail.py`, `extract_attachments.py` | extract-msg (GPL), olefile (BSD) | Both agreed with the fixture; extract-msg documents RTF body support (not tested here) |
| winmail.dat | same | tnefparse (LGPL) | Same names on its 19 samples; see `formats.md` |
| .eml | same (Python `email`) | | Standard library |
| .ics | `inspect_ics.py` | icalendar (BSD), for writing or expanding RRULE | `inspect_ics.py` never writes |
| .pst | none | classic Outlook, readpst | Sandbox readpst |
