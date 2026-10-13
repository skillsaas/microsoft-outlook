# Calendar: invites, .ics, time zones, Graph

Last verified: 2026-10-13 (sources listed at the end; not re-checked since).

## Reading an invite
`inspect_ics.py invite.ics --json --tz <user zone>`. For a meeting request inside an email,
`inspect_mail.py` lists the `text/calendar` part (kind `calendar`); save it with
`extract_attachments.py` and inspect the `.ics`.

Fields that matter:
| Field | Meaning |
| :--- | :--- |
| `METHOD` | `REQUEST` new or updated meeting, `CANCEL`, `REPLY` (an attendee's answer), `PUBLISH` (no reply expected) (RFC 5546) |
| `UID` + `SEQUENCE` + `RECURRENCE-ID` | Identity of the meeting; a higher SEQUENCE is an update; RECURRENCE-ID marks one changed occurrence |
| `DTSTART;TZID=...` | Local time in that zone. A trailing `Z` is UTC. No TZID and no Z is "floating" time |
| `RRULE`, `EXDATE`, `RDATE` | Recurrence as written; the script does not expand it |
| `ORGANIZER`, `ATTENDEE` | `mailto:` addresses; `CN` is a display name the sender chose |
| `X-MICROSOFT-CDO-BUSYSTATUS` | Outlook free/busy hint (`FREE`, `TENTATIVE`, `BUSY`, `OOF`) |
| `X-MICROSOFT-SKYPETEAMSMEETINGURL` | Teams join link, when Exchange adds it |

## Time zones
- Outlook and Exchange often write **Windows zone names** as TZID, such as
  `Pakistan Standard Time`, with a VTIMEZONE block giving the offsets. Since 0.1.1 `--tz` maps
  them with the shipped CLDR `windowsZones.xml` table (`scripts/windows_zones.json`, 142 zones,
  territory 001 defaults) and converts, adding `iana` and a note. The VTIMEZONE rules in the
  file are not evaluated: if the file's offsets disagree with the mapped zone (an old or custom
  definition), trust the organizer's confirmation over either.
- Local times in a daylight saving gap (`local_time: nonexistent`, for example 02:30 on the
  spring-forward night in New York) or overlap (`ambiguous`) are flagged as medium risks. Ask
  the organizer rather than guessing.
- UTC (`...Z`) and IANA TZIDs (`Europe/London`) are converted with Python `zoneinfo`, including
  daylight saving (tested: 14:00 Europe/London on 2026-10-16 is 18:00 Asia/Karachi).
- Always report times in the user's zone with the zone named, and say when a meeting recurs.

## What inspect_ics.py does with hard cases
| Case | Output | Agent should |
| :--- | :--- | :--- |
| Ambiguous local time (DST overlap) | `local_time: ambiguous`, medium risk; converted with the earlier instant (fold 0) | say it happens twice; confirm with the organizer |
| Nonexistent local time (DST gap) | `local_time: nonexistent`, medium risk; converted as written | say the time does not exist there; confirm |
| Floating time (no Z, no TZID) | `value` kept, not converted, note "floating time" | never assume UTC or the machine's zone |
| Unknown TZID | `value` and `tzid` kept, `converted: null`, note | report the stated time and zone as written |
| Invalid date (`DTSTART:2026`, month 00) | `value` kept, note "not a valid ..." | say the start time could not be read |
| RRULE | `rrule` as written plus an info risk "RRULE not expanded" | do not list occurrences; say "repeats" with the rule |
| EXDATE, RECURRENCE-ID | counts and the RECURRENCE-ID value only; exceptions are not applied | say some occurrences are changed or cancelled; check the calendar |
| SEQUENCE | reported as written | a higher number is usually newer, but it does not prove which invite is authoritative |

## Calendar threats
- Invites can arrive without the user accepting anything, and land on the calendar. Treat links
  in the description and location as untrusted (`link` risks).
- `ATTACH` with `file:` or other risky schemes, inline binary attachments, and alarms with
  actions other than `DISPLAY`, `AUDIO` or `EMAIL` (for example the old `PROCEDURE`) are flagged.
- An invite's ORGANIZER is self-declared. A "meeting from your CEO" may come from anyone.

## Graph calendar
```http
GET /me/calendarView?startDateTime=2026-10-13T00:00:00+05:00&endDateTime=2026-10-20T00:00:00+05:00
Prefer: outlook.timezone="Pakistan Standard Time"
GET /me/events/{id}
POST /me/events                         # Calendars.ReadWrite
POST /me/events/{id}/accept             # also tentativelyAccept, decline
{ "comment": "...", "sendResponse": true }
POST /me/calendar/getSchedule           # free/busy for several people
```
- `calendarView` needs both `startDateTime` and `endDateTime`, returns occurrences and exceptions
  of recurring series, and reads offsets in the values (no offset means UTC); the
  `Prefer: outlook.timezone` header sets the zone of times in the response, not of the query.
- **Creating an event with attendees sends invitations immediately, and this cannot be turned
  off.** Show the user the event JSON and attendee list first. An event without attendees is a
  private appointment.
- `accept`, `tentativelyAccept` and `decline` send a response to the organizer unless
  `sendResponse` is false (default true). Ask which the user wants.
- Approval is for one exact action: accept, tentative, decline, propose a new time, or cancel,
  with its comment. If the user changes any part, show it again and ask again.
- Exchange and Outlook can add an incoming invite to the calendar as tentative on their own
  (calendar auto-processing). An invite being on the calendar is not the user's answer.
- Updating or deleting a meeting the user organizes notifies attendees. Ask first.

## Sources
- calendarView: https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0
- Create event (invitations are sent): https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0
- Decline (sendResponse default): https://learn.microsoft.com/en-us/graph/api/event-decline?view=graph-rest-1.0
- Event resource: https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0
- MS-OXCICAL (Outlook's iCalendar mapping): https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxcical/
- RFC 5545 and RFC 5546: https://www.rfc-editor.org/rfc/rfc5545, https://www.rfc-editor.org/rfc/rfc5546
- Calendar processing (AutoUpdate marks requests tentative): https://learn.microsoft.com/en-us/powershell/module/exchange/set-calendarprocessing
- CLDR Windows zone mapping: https://github.com/unicode-org/cldr/blob/main/common/supplemental/windowsZones.xml
