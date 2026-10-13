# Microsoft Graph for mail

Documented from Microsoft Learn (read 2026-10-13); not run against a tenant. Base URL
`https://graph.microsoft.com/v1.0`. `/me` is the signed-in user (delegated); `/users/{id|upn}`
is another mailbox (needs `.Shared` delegated scopes or application permissions).

## Which API
- **Microsoft Graph** for Exchange Online and Outlook.com mailboxes.
- **Not EWS** for new Exchange Online work: Microsoft began phased EWS disablement in Exchange
  Online on 2026-10-01, with permanent shutdown starting 2027-04-01; from 2026-10-10, tenants that
  keep EWS on must list allowed apps in `EWSAllowedAppIDs`. Exchange Server on-premises is not
  affected. If a user's tool uses EWS, say it may already be blocked.
- **Not the Outlook REST API v2.0 or beta** (`outlook.office.com/api/v2.0`): decommissioned
  starting 2024-03-31.

## Permissions (least privileged first)
| Task | Delegated scope |
| :--- | :--- |
| List messages without bodies | `Mail.ReadBasic` |
| Read bodies, attachments, MIME | `Mail.Read` |
| Create drafts, move, flag, delete | `Mail.ReadWrite` |
| Send | `Mail.Send` |
| Read inbox rules | `MailboxSettings.Read` |
| Create or change rules, automatic replies | `MailboxSettings.ReadWrite` |
| Read calendar view | `Calendars.ReadBasic` (or `Calendars.Read`) |
| Create, accept, decline events | `Calendars.ReadWrite` |

## Reading
```http
GET /me/messages?$select=subject,from,receivedDateTime,hasAttachments&$top=25
GET /me/mailFolders/inbox/messages?$filter=receivedDateTime ge 2026-10-01T00:00:00Z&$orderby=receivedDateTime desc
GET /me/messages/{id}?$select=subject,body,internetMessageHeaders
Prefer: outlook.body-content-type="text"
GET /me/messages/{id}/$value                 # the full MIME (.eml); single message only
GET /me/messages/{id}/attachments            # fileAttachment has contentBytes (base64)
GET /me/messages/{id}/attachments/{aid}/$value
```
- Default page size is 10; `$top` takes 1 to 1000. Follow `@odata.nextLink` for more.
- `$orderby` properties must appear in `$filter`, first and in the same order, or the call fails
  with `InefficientFilter`.
- `$value` on a message returns MIME; save it as `.eml` and run `inspect_mail.py` on it to apply
  the same phishing checks to live mail.
- `body` comes back as HTML unless `Prefer: outlook.body-content-type="text"`.
- Attachment types: `fileAttachment`, `itemAttachment` (an attached message or event),
  `referenceAttachment` (a link to a cloud file: nothing to download from the mail).

## Writing: drafts first
```http
POST /me/messages                            # creates a draft (Mail.ReadWrite); returns its id
{ "subject": "...", "body": {"contentType": "Text", "content": "..."},
  "toRecipients": [{"emailAddress": {"address": "sara@contoso.example"}}] }

POST /me/messages/{id}/createReply           # a reply draft; createReplyAll, createForward too
POST /me/messages/{id}/send                  # sends the draft (Mail.Send): ONLY after approval
POST /me/sendMail                            # sends at once, no draft: avoid in agent flows
```
- Show the user the draft (recipients, subject, body, attachments) and wait for an explicit yes
  before `send`. Read the draft back with GET first so what you show is what will go.
- `sendMail` and `send` return `202 Accepted`: accepted for delivery, not delivered. `sendMail`
  saves to Sent Items unless `saveToSentItems` is false.
- `sendMail` also takes base64 MIME with `Content-Type: text/plain`.
- Attachments up to 3 MB go inline in the JSON (`contentBytes`); 3 MB to 150 MB need
  `POST /me/messages/{id}/attachments/createUploadSession` and ranged PUTs.

## Search
`$search` uses KQL property names on messages: see `search.md`.

## Throttling and errors
- `429` and `503` carry `Retry-After`: wait that long, then retry; do not loop fast.
- `ErrorAccessDenied` usually means a missing scope or a mailbox the user cannot open: report it,
  do not escalate scopes on your own.

## Sources
- Send mail: https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0
- Get message (MIME `$value`): https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
- List messages: https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
- Large attachments: https://learn.microsoft.com/en-us/graph/outlook-large-attachments
- `$search`: https://learn.microsoft.com/en-us/graph/search-query-parameter
- Permissions: https://learn.microsoft.com/en-us/graph/permissions-reference
- EWS deprecation: https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-ews-exchange-online
- Message center MC1227454 (timeline) and MC1485116 (`EWSAllowedAppIDs`), via https://mc.merill.net
- Outlook REST v2 decommissioning: https://devblogs.microsoft.com/microsoft365dev/outlook-rest-api-v2-0-and-beta-endpoints-decommissioning-update/
