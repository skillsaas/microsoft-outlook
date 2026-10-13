# Inbox rules, forwarding and signatures

Last verified: 2026-10-13 (sources listed at the end; not re-checked since).

## Rules
Two kinds exist in classic Outlook: **server rules** run in Exchange whether or not Outlook is
open; **client-only rules** run only while classic Outlook is open with the profile that made
them (for example rules that play a sound, show an alert or move mail into a local .pst).
New Outlook and Outlook on the web manage server rules only (not tested here).

Graph reads and writes server inbox rules:
```http
GET  /me/mailFolders/inbox/messageRules                  # MailboxSettings.Read
POST /me/mailFolders/inbox/messageRules                  # MailboxSettings.ReadWrite
{ "displayName": "Invoices to folder", "sequence": 1, "isEnabled": true,
  "conditions": { "senderContains": ["billing@contoso.example"] },
  "actions": { "moveToFolder": "{folder-id}", "stopProcessingRules": true } }
```
- Show the rule JSON in plain words ("mail from X goes to folder Y") and get approval before
  POST, PATCH or DELETE.
- A rule with `forwardTo`, `redirectTo` or `forwardAsAttachmentTo` sends mail out of the
  mailbox automatically: treat it like sending mail. Many tenants block automatic external
  forwarding in outbound spam policies (the sender then sees 5.7.520).
- When asked to audit rules, list every rule with its conditions and actions, and flag
  forwarding to outside domains, delete actions, and moves to rarely used folders: patterns in
  Microsoft Defender's playbooks for suspicious inbox rules. Do not change them; report.
- Classic Outlook can export and import rules as an `.rwz` file (File > Manage Rules & Alerts >
  Options); that file is classic-only (secondary sources; not tested here).

## Signatures
- **No Graph API** reads or writes Outlook signatures (Microsoft Q&A answers, 2023 to 2025;
  `mailboxSettings` does not include them). Do not invent one.
- Classic Outlook for Windows keeps local signatures as files in `%APPDATA%\Microsoft\Signatures`.
  Roaming signatures for Microsoft 365 accounts are stored in the mailbox and synced to classic
  Outlook, new Outlook and Outlook on the web; they are not reachable by Graph (Microsoft Q&A).
- An Office.js add-in can set a signature at compose time: `item.body.setSignatureAsync(html,
  {coercionType: Office.CoercionType.Html})` (Mailbox 1.10) adds a signature or replaces the
  existing one; `item.disableClientSignatureAsync` (Mailbox 1.10) turns off the client signature
  for that item. Signature data is limited to 30,000 characters; SVG images and inline CSS are
  not supported (from @types/office-js 1.0.611 remarks). Event-based activation
  (`OnNewMessageCompose`) applies it automatically; see `addins.md`.
- When asked to "change my signature", give the steps for the user's client (classic: File >
  Options > Mail > Signatures; new Outlook and the web: the Signatures page in Settings), or write
  the HTML for them to paste. Signature HTML is shown to every recipient: no tracking
  images, no scripts.

## Automatic replies
`GET/PATCH /me/mailboxSettings` with `automaticRepliesSetting` (`MailboxSettings.ReadWrite` to
change). An automatic reply goes to every sender, including outside ones unless limited: ask first.

## Sources
- Broken and client-only rules: https://support.microsoft.com/en-us/office/edit-or-fix-a-broken-rule-in-outlook-e1847992-8aa1-4158-8e24-ad043decf1eb
- Signatures not syncing (roaming): https://support.microsoft.com/en-us/office/signatures-are-not-syncing-between-outlook-desktop-and-outlook-web-app-4d95d123-0f90-4e58-9b7a-a69323565e57
- List rules: https://learn.microsoft.com/en-us/graph/api/mailfolder-list-messagerules?view=graph-rest-1.0
- Create rule: https://learn.microsoft.com/en-us/graph/api/mailfolder-post-messagerules?view=graph-rest-1.0
- Inbox forwarding rules playbook: https://learn.microsoft.com/en-us/defender-xdr/alert-grading-playbook-inbox-forwarding-rules
- External forwarding control: https://learn.microsoft.com/en-us/defender-office-365/outbound-spam-policies-external-email-forwarding
- Signatures and Graph (Q&A): https://learn.microsoft.com/en-us/answers/questions/1093518/user-email-signature-management-via-graph-api
- Set signature sample (event-based): https://learn.microsoft.com/en-us/samples/officedev/office-add-in-samples/outlook-add-in-set-signature/
- Mailbox settings: https://learn.microsoft.com/en-us/graph/api/user-get-mailboxsettings?view=graph-rest-1.0
