# Calendar: invites, .ics, time zones, Graph

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
  `Pakistan Standard Time`, with a VTIMEZONE block giving the offsets. These are not IANA names,
  so `--tz` leaves them unconverted and lists them in `non-iana-tzid`. Map them with the Unicode
  CLDR `windowsZones.xml` table, or read the VTIMEZONE offsets, and say which you used.
- UTC (`...Z`) and IANA TZIDs (`Europe/London`) are converted with Python `zoneinfo`, including
  daylight saving (tested: 14:00 Europe/London on 2026-10-16 is 18:00 Asia/Karachi).
- Always report times in the user's zone with the zone named, and say when a meeting recurs.

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
- Updating or deleting a meeting the user organizes notifies attendees. Ask first.

## Sources
- calendarView: https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0
- Create event (invitations are sent): https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0
- Decline (sendResponse default): https://learn.microsoft.com/en-us/graph/api/event-decline?view=graph-rest-1.0
- Event resource: https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0
- MS-OXCICAL (Outlook's iCalendar mapping): https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxcical/
- RFC 5545 and RFC 5546: https://www.rfc-editor.org/rfc/rfc5545, https://www.rfc-editor.org/rfc/rfc5546
- CLDR Windows zone mapping: https://github.com/unicode-org/cldr/blob/main/common/supplemental/windowsZones.xml
