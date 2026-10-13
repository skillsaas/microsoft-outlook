# Microsoft Graph for mail

Last verified against Microsoft Learn: 2026-10-13. Not run against a tenant.

> **Documented, not run.** Every request and code sample here is a recipe from Microsoft Learn
> (shapes checked, behaviour not observed). Read back the result of every write; do not treat a
> recipe as tested. Base URL
`https://graph.microsoft.com/v1.0`. `/me` is the signed-in user (delegated); `/users/{id|upn}`
is another mailbox (needs `.Shared` delegated scopes or application permissions).

## Auth: use what the user already has
- **First choice: an existing Microsoft 365 or Graph connector** in the agent host (an MCP
  server, a connected Outlook account). It already holds consent and refresh. Do not build an
  OAuth flow or ask the user for a password or a token to paste.
- **If you must sign in yourself**: MSAL (Microsoft's library) with an app registration the
  user's organization controls. On a machine without a browser, the **device code flow**: the
  user opens the verification URL on another device and types the code; it expires after 15
  minutes by default (`expires_in`). MSAL caches tokens and refreshes them; never write a
  token to a log, a file in the repo, or the chat.
- **Consent**: delegated scopes are granted by the user or, for some scopes and in many
  organizations, only by an admin. If sign-in asks for admin approval, stop and tell the user;
  do not try another scope set to get around it.
- **Conditional Access** can require MFA or a compliant device, or block the device code flow.
  A sign-in blocked by policy is the organization's decision: report it, do not retry with a
  different client or flow.

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

## Limits (Microsoft Learn, read 2026-10-13; Microsoft says they can change)
| Limit | Value | Source |
| :--- | :--- | :--- |
| Requests per app per mailbox | 10,000 per 10 minutes | Throttling limits, Outlook service |
| Concurrent requests per app per mailbox | 4 | same |
| Upload per app per mailbox (PATCH, POST, PUT) | 150 MB per 5 minutes | same |
| Requests in one JSON `$batch` | 20 | JSON batching |
| Write request body | 4 MB (HTTP 413 above it) | Use the API |
| Attachment by single POST or inline in `sendMail` | under 3 MB | Add attachment |
| Attachment by upload session | 3 MB to 150 MB, PUT ranges of at most 4 MB, in order | Large attachments |
| Default mailbox message size (admin-configurable) | 35 MB | createUploadSession |

So a mail with a file over 3 MB cannot go through `sendMail`: make a draft, attach with an
upload session, show the draft, then `send` on approval.

## Recipes (shapes checked against the Microsoft Learn examples on 2026-10-13; not run)
Every request goes to `https://graph.microsoft.com/v1.0` with `Authorization: Bearer {token}` (from
the host's connector or MSAL), except the upload-session `uploadUrl`. Status codes are the ones
Learn documents; anything else is a failure to report, and a write with no clear answer is read
back, never retried blindly.
```http
# 1. Page through a folder: follow @odata.nextLink exactly as returned until it is absent
GET /me/mailFolders/inbox/messages?$select=id,subject,from,receivedDateTime&$top=100
GET {@odata.nextLink}

# 2. Large attachment on a draft (file over 3 MB). Learn: attachment-createuploadsession,
#    outlook-large-attachments.
POST /me/messages                              # 201 Created, a draft; keep its id
Content-Type: application/json
{ "subject": "Q3 report", "toRecipients": [{"emailAddress": {"address": "sara@contoso.example"}}] }

POST /me/messages/{draft-id}/attachments/createUploadSession   # 201 Created, uploadSession
Content-Type: application/json
{ "AttachmentItem": { "attachmentType": "file", "name": "q3.pdf", "size": 9437184 } }

PUT {uploadUrl}                                # no Authorization header: the URL carries it
Content-Type: application/octet-stream
Content-Length: 4194304
Content-Range: bytes 0-4194303/9437184
                                               # 200 OK with nextExpectedRanges, e.g. ["4194304"]
...repeat with the next range, in order, at most 4 MB each...
                                               # last PUT: 201 Created, Location header = attachment URL
GET /me/messages/{draft-id}/attachments?$select=name,size     # read back
POST /me/messages/{draft-id}/send             # 202 Accepted; only after the user approves this draft

# 3. Batch of reads (up to 20; Graph runs at most 4 at a time against one mailbox). Learn: json-batching.
POST /$batch
Content-Type: application/json
{ "requests": [
  { "id": "1", "method": "GET", "url": "/me/messages/{id1}?$select=subject" },
  { "id": "2", "method": "GET", "url": "/me/messages/{id2}?$select=subject" } ] }
                                               # 200 OK: { "responses": [ { "id": "1", "status": 200, "body": {...} },
                                               #   { "id": "2", "status": 429, "headers": {"Retry-After": "10"} } ] }

# 4. One message with its attachment list, then one file's bytes. Learn: message-get, attachment-get.
GET /me/messages/{id}?$select=subject,from,receivedDateTime,hasAttachments&$expand=attachments
                                               # 200 OK; attachments[] carry contentBytes for small files;
                                               # @odata.type tells file, item or reference
GET /me/messages/{id}/attachments/{attachment-id}/$value
                                               # 200 OK, raw bytes of a fileAttachment: save, then run
                                               # extract/inspect rules on them; never open

# 5. Reply as a draft (nothing is sent). Learn: message-createreply, message-update, message-send.
POST /me/messages/{id}/createReply             # 201 Created, the draft message; keep its id
Content-Type: application/json
{ "comment": "Thanks, I will check and come back to you." }
PATCH /me/messages/{draft-id}                  # optional edit; 200 OK
Content-Type: application/json
{ "body": { "contentType": "text", "content": "Thanks, I will check and come back to you." } }
GET /me/messages/{draft-id}?$select=toRecipients,ccRecipients,subject,body   # read back, show the user
POST /me/messages/{draft-id}/send             # 202 Accepted, only after approval of this exact draft
                                               # (no body). /reply and /replyAll send at once: not used.

# 6. Forward as a draft. Learn: message-createforward.
POST /me/messages/{id}/createForward           # 201 Created, the draft; send as in 5 after approval
Content-Type: application/json
{ "toRecipients": [ { "emailAddress": { "address": "it-security@contoso.example" } } ],
  "comment": "Forwarding a suspected phish for review." }

# 7. Inbox rules: list, then create one (MailboxSettings.ReadWrite). Learn: mailfolder-list-messagerules,
#    mailfolder-post-messagerules.
GET /me/mailFolders/inbox/messageRules         # 200 OK, { "value": [ rules ] }; check forwardTo,
                                               # redirectTo, forwardAsAttachmentTo for outside addresses
POST /me/mailFolders/inbox/messageRules        # 201 Created, the rule with its id
Content-Type: application/json
{ "displayName": "Newsletters to Reading", "sequence": 2, "isEnabled": true,
  "conditions": { "senderContains": [ "newsletter@" ] },
  "actions": { "moveToFolder": "{folder-id}", "stopProcessingRules": true } }
GET /me/mailFolders/inbox/messageRules/{rule-id}   # read back before saying it is done

# 8. A week of calendar, in the user's zone. Learn: user-list-calendarview.
GET /me/calendarView?startDateTime=2026-10-19T00:00:00Z&endDateTime=2026-10-26T00:00:00Z&$select=subject,start,end,organizer,isOnlineMeeting&$orderby=start/dateTime&$top=50
Prefer: outlook.timezone="Pakistan Standard Time"
                                               # 200 OK; recurring meetings come back as single
                                               # occurrences; follow @odata.nextLink as in 1
```
Each batch item has its own status: check every one; a 200 for the batch is not success for all.

## Throttling and errors
- `429` and `503` carry `Retry-After`: wait that long, then retry; do not loop fast.
- SKILL.md safety rule 7 applies (no blind retries): after a timeout on `send`, `sendMail`, an event create or a rule
  create, look first (Sent Items, the calendar, the rule list) or the user may get duplicates.
- `ErrorAccessDenied` usually means a missing scope or a mailbox the user cannot open: report it,
  do not escalate scopes on your own.

## Sources
- Throttling limits (Outlook service): https://learn.microsoft.com/en-us/graph/throttling-limits
- JSON batching: https://learn.microsoft.com/en-us/graph/json-batching
- Write size limit: https://learn.microsoft.com/en-us/graph/use-the-api
- Add attachment: https://learn.microsoft.com/en-us/graph/api/message-post-attachments?view=graph-rest-1.0
- Upload session: https://learn.microsoft.com/en-us/graph/api/attachment-createuploadsession?view=graph-rest-1.0
- Device code flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- Send mail: https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0
- Get message (MIME `$value`): https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
- List messages: https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
- Large attachments: https://learn.microsoft.com/en-us/graph/outlook-large-attachments
- `$search`: https://learn.microsoft.com/en-us/graph/search-query-parameter
- Permissions: https://learn.microsoft.com/en-us/graph/permissions-reference
- EWS deprecation: https://learn.microsoft.com/en-us/exchange/clients-and-mobile-in-exchange-online/deprecation-of-ews-exchange-online
- Message center MC1227454 (timeline) and MC1485116 (`EWSAllowedAppIDs`), via https://mc.merill.net
- Outlook REST v2 decommissioning: https://devblogs.microsoft.com/microsoft365dev/outlook-rest-api-v2-0-and-beta-endpoints-decommissioning-update/
