# Search syntax: Outlook client (AQS) and Graph (KQL)

Two different languages that look alike. Say which one you are giving.

## In Outlook (search box)
Outlook on the web documents Advanced Query Search (AQS) keywords; new Outlook for Windows
shares the web codebase (expected to behave the same; not tested here):
| Keyword | Example |
| :--- | :--- |
| `from:` `to:` `cc:` `bcc:` `participants:` | `from:JerriFrye` |
| `subject:` | `subject:report`, `subject:(product plan)` both words, `subject:"product plan"` phrase |
| `body:` (or `content:`) | `body:invoice` |
| `sent:` `received:` | `received:01/01/2026`, a range with `..`, or `today`, `yesterday`, `this week`, `last week`, `past month`. Dates are MM/DD/YYYY |
| `category:` | `category:reports` |
| `hasattachment:yes` / `no` | `report hasattachment:yes` |
| `isflagged:yes` / `no` | |
Rules from the same page: keywords are not case sensitive; no space after the colon (with a
space the value is searched as plain text); a space between terms means AND; `AND` and `OR`
combine terms.

Classic Outlook Instant Search: quotes find an exact phrase; `AND`, `OR`, `NOT` must be upper
case; matches are whole words or word beginnings, not the middle of a word. Classic also has
a Search ribbon with refiners (From, Subject, Has Attachments, This Week, ...). Exact keyword
spellings can differ between classic and new Outlook: when a keyword returns nothing, try the
ribbon or filters before concluding there is no mail.

Search scope matters: current folder, all folders, or all mailboxes. Mail in a .pst is searched
only when that file is open in classic Outlook.

## In Microsoft Graph (`$search` on messages)
Graph uses Keyword Query Language property names. Put the whole expression in double quotes.
```http
GET /me/messages?$search="from:sara@contoso.example AND subject:invoice"&$select=subject,from,receivedDateTime
GET /me/messages?$search="hasAttachments:true"
GET /me/messages?$search="received:10/01/2026..10/13/2026"   # range form from the KQL reference
GET /me/messages?$search="participants:sara"
```
Documented properties: `attachment` (file names), `bcc`, `body`, `cc`, `from`,
`hasAttachments`, `importance` (`low`, `medium`, `high`), `kind` (`email`, `meetings`, ...),
`participants`, `received`, `recipients`, `sent`, `size` (`size:1..500000`), `subject`, `to`.
With no property, Graph searches `from`, `subject` and `body`.
- Results are sorted by sent date and capped at 1,000.
- For exact structured filtering use `$filter` instead, for example
  `$filter=receivedDateTime ge 2026-10-01T00:00:00Z and hasAttachments eq true`. When you add
  `$orderby`, its properties must also appear first in `$filter`, in the same order, or you get
  `InefficientFilter`.
- Graph `$search` is not the same as the Microsoft Search API (`/search/query`), which searches
  across Microsoft 365; not covered here.

## Quick translation
| User says | Outlook box | Graph |
| :--- | :--- | :--- |
| mail from Sara with attachments | `from:sara hasattachment:yes` | `$search="from:sara AND hasAttachments:true"` |
| subject has "Q3 budget" exactly | `subject:"Q3 budget"` | `$search="subject:\"Q3 budget\""` (escape inner quotes; URL-encode) |
| received last week | `received:"last week"` | `$filter=receivedDateTime ge {start} and receivedDateTime lt {end}` |

## Sources
- Outlook on the web AQS: https://support.microsoft.com/en-us/outlook/search-mail-and-people-in-outlook-on-the-web
- Classic Instant Search: https://support.microsoft.com/en-us/office/find-a-message-or-item-with-instant-search-69748862-5976-47b9-98e8-ed179f1b9e4d
- Graph `$search`: https://learn.microsoft.com/en-us/graph/search-query-parameter
- List messages (`$filter` with `$orderby`): https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
- KQL reference: https://learn.microsoft.com/en-us/sharepoint/dev/general-development/keyword-query-language-kql-syntax-reference
- New Outlook shares the web codebase: https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/one-outlook
