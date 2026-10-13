# Shipped public samples (MIT)

Seven real Outlook and MIME files copied unchanged from two MIT-licensed test sets, so the
default test run checks real files without a download. Their Outlook versions are unknown.

| File | From | What it covers |
| :--- | :--- | :--- |
| EmailWithMsgAttachment.msg | MSGReader | an attached .msg (nested message) |
| RtfSampleEmail.msg | MSGReader | compressed RTF body |
| HtmlSampleEmail.msg | MSGReader | HTML body |
| EmailWithISO_8859_1_From.eml | MSGReader | encoded From header |
| TestWithInlineHavingWindows1252Fields.eml | MSGReader | inline part, Windows-1252 fields |
| rb-note.msg | ruby-msg | an Outlook note, not a mail |
| rb-test_Blammo.msg | ruby-msg | plain message |

Sources, pinned: Sicos1977/MSGReader at b9b04a7a (LICENSE-MSGReader.txt) and
aquasync/ruby-msg at a31ffaff (LICENSE-ruby-msg.txt). SHA-256 and expected subject and
attachment names are in `../public_samples_expected.json`. The other 31 public samples,
including the GPL-3.0 msg-extractor files, are fetched with `../fetch_public_samples.py`.
