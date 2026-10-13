# Outlook add-ins (Office.js), new vs classic, VBA

Last verified: 2026-10-13 (sources listed at the end; not re-checked since).

API names and requirement sets below were checked against `@types/office-js` 1.0.611
(2026-10-13). No add-in was built or run here.

## Which client runs what
| | New Outlook for Windows, Outlook on the web | Classic Outlook for Windows | Outlook for Mac |
| :--- | :--- | :--- | :--- |
| Web add-ins (Office.js) | yes | yes | yes |
| COM and VSTO add-ins | no | yes | no |
| VBA macros, Outlook object model, MAPI | no | yes | no (AppleScript instead; not covered) |
| Graph from outside the client | yes | yes | yes |
Microsoft's guidance for VBA users moving to new Outlook: Power Automate for flows between apps,
Microsoft Graph for advanced automation, Office.js for in-client integration. If a COM or VBA
solution has no replacement, classic Outlook still runs it.

## Add-in basics
- An add-in is a web app plus a manifest (add-in only XML manifest, or the unified manifest for
  Microsoft 365). It runs in a sandboxed web view and needs network access.
- Check a feature before use: `Office.context.requirements.isSetSupported("Mailbox", "1.10")`.
- Read mode: `Office.context.mailbox.item` has `subject`, `from`, `to`, `body.getAsync(...)`
  (Mailbox 1.3), `getAllInternetHeadersAsync` (1.8), `getAttachmentContentAsync` (1.8).
- Compose mode: `item.body.setSelectedDataAsync`, `item.addFileAttachmentFromBase64Async` (1.8),
  `item.saveAsync` (1.3, saves a draft), `item.body.setSignatureAsync` (1.10).
- Opening forms for the user to finish (the user presses Send): `displayReplyFormAsync`,
  `displayReplyAllFormAsync`, `Office.context.mailbox.displayNewMessageFormAsync` (1.9).
  Prefer these: the user sees and sends the message themselves.
- `item.sendAsync` (Mailbox 1.15) sends the item being composed, from task pane or function
  commands only, not from event-based handlers. Code after the call is not guaranteed to run,
  and a Smart Alerts add-in may still block the send. Use it only when the user asked the
  add-in to send.
- Multiple selected messages: `Office.context.mailbox.getSelectedItemsAsync` (1.13),
  `loadItemByIdAsync` (1.15).

## Event-based activation and Smart Alerts
- Handlers run without the task pane on events such as `OnNewMessageCompose` (set signatures,
  templates) and `OnMessageSend` (check before sending: missing attachment, external recipients,
  classification). Smart Alerts (`OnMessageSend`) is Mailbox 1.12.
- `sendModeOverride` is not a manifest setting: it is an option of `event.completed(...)`
  (`SmartAlertsEventCompletedOptions`, Mailbox 1.14), and the only value today is
  `Office.MailboxEnums.SendModeOverride.PromptUser` ("promptUser"), which offers **Send Anyway**.
  The manifest's `SendMode` (prompt user, soft block, block) sets the default.
- Use `OnMessageSend` to warn, not to silently rewrite the message.

Typed handler (type-checked with TypeScript 5.9 `--strict` against @types/office-js 1.0.611; not
run in Outlook). Register the function name in the manifest's event mapping:
```ts
function onMessageSendHandler(event: Office.MailboxEvent): void {
  const item = Office.context.mailbox.item as Office.MessageCompose;
  item.to.getAsync({ asyncContext: event }, (result: Office.AsyncResult<Office.EmailAddressDetails[]>) => {
    const ev = result.asyncContext as Office.MailboxEvent;
    if (result.status !== Office.AsyncResultStatus.Succeeded) {
      ev.completed({ allowEvent: true }); // never block mail because the check itself failed
      return;
    }
    const external = result.value.filter(r => !r.emailAddress.toLowerCase().endsWith("@contoso.com"));
    if (external.length === 0) {
      ev.completed({ allowEvent: true });
      return;
    }
    ev.completed({
      allowEvent: false,
      errorMessage: "This message goes to " + external.length + " external recipient(s). Check before sending.",
      sendModeOverride: Office.MailboxEnums.SendModeOverride.PromptUser,
    });
  });
}
Office.actions.associate("onMessageSendHandler", onMessageSendHandler);
```
- Type definitions prove a name exists, not that a client supports it: check the requirement
  set with `Office.context.requirements.isSetSupported("Mailbox", "1.14")` at run time.

## Authentication
- Recommended for delegated Graph access from an add-in: MSAL with nested app authentication
  (NAA) (types remarks).
- Legacy Exchange user identity tokens and callback tokens are turned off in all Microsoft 365
  tenants; they still exist for Exchange on-premises. So `makeEwsRequestAsync` and
  `getCallbackTokenAsync` are not a path for Exchange Online; use Graph.

## VBA and the Outlook object model (classic Outlook for Windows only)
- `MailItem.Display` shows a message for the user to send; `MailItem.Send` sends at once. In
  agent-written macros, use `Display`, never `Send`, unless the user asked for automatic sending.
- The object model guard may show security prompts when code reads addresses or sends mail, depending
  on antivirus status and policy. Do not tell users to disable it.
- Macros in Outlook (`VbaProject.OTM`) run with the user's rights. Never install a macro from
  a received email.

## Sources
- OnMessageSend and Smart Alerts: https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/onmessagesend-onappointmentsend-events
- New Outlook add-in support: https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/one-outlook
- Overview of new Outlook (COM not supported): https://learn.microsoft.com/en-us/microsoft-365-apps/outlook/overview-new-outlook-windows
- VBA alternatives: https://learn.microsoft.com/en-us/microsoft-365-apps/outlook/get-started/vba-alternatives
- Feature comparison: https://support.microsoft.com/en-us/Outlook/getstarted/feature-comparison-between-new-outlook-and-classic-outlook
- Smart Alerts: https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/onmessagesend-onappointmentsend-events
- Event-based activation: https://learn.microsoft.com/en-us/office/dev/add-ins/develop/event-based-activation
- Outlook add-in authentication: https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/authentication
- Object model security: https://learn.microsoft.com/en-us/office/vba/outlook/how-to/security/security-behavior-of-the-outlook-object-model
- Office.js typings: https://www.npmjs.com/package/@types/office-js (1.0.611)
