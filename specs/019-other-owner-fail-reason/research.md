# Research: Other-owner failure reason

All spec decisions are confirmed against the code. Nothing is left as NEEDS CLARIFICATION.

## Decision: Keep the letter `H`

- **Rationale**: `Msg.FAILED_CHOICES` is `S`, `L`, `E`, `O`, `D`. `H` is unused on `failed_reason`. Status `H` means handled on a different column. A blocked send is stored as status `F` and reason `H`, so the two letters do not share a field. `C` is the classic RapidPro contact reason and stays unused.
- **Alternatives considered**: `N` (“not owner”) if the letter had to be absent from every message column. Rejected. Courier already chose `H`, and this column can store it.

## Decision: Choices-only migration, no CHECK

- **Rationale**: `failed_reason` is already `varchar(1)` and nullable (`0160`, last choice change `0162`). The only check on `msgs_msg` is `no_sent_status_without_sent_on`. PostgreSQL already accepts `H`. Django choices are enforced on `full_clean`, and no caller full-cleans `Msg`. A new check would be the first rule that could make Courier’s `UPDATE` fail.
- **Alternatives considered**: Add a CHECK that lists `S`, `L`, `E`, `O`, `D`, `H`. Rejected. It would reject any other single character Courier or older rows might already store, and the column is optional today.

## Decision: Migration depends on `0175_merge_20260910_2109`

- **Rationale**: That merge is the current leaf of `temba/msgs/migrations` (`0174_auto_20260910_2044` and `0174_managedtriggergroup`). `makemigrations` must emit `AlterField` for `failed_reason` only: `null=True`, `max_length=1`, choices extended with `H`. No `AddConstraint`.
- **Alternatives considered**: Hand-written SQL. Rejected. `./code_check.py` expects a Django migration that matches the model.

## Decision: Show the sentence only for reason `H`

- **Rationale**: History, the failed list, and the channel log do not print failure reasons today. `get_failed_reason_display()` for `E` is “Error Limit”. Rendering every reason would change AC-F3. The choice label for `H` is the sentence. The history event gains `failed_reason_display` only when the code is `H`, so existing `Event.from_msg` equality tests stay green.
- **Alternatives considered**: Always send `get_failed_reason_display()`. Rejected. It would surface “Suspended”, “Looping”, “Error Limit”, “Too Old”, and “No Destination” on screens that omit them today.

## Decision: English msgid plus es, pt_BR, and ro

- **Rationale**: Constitution requires EN source, ES, PT, and RO. The binding Portuguese sentence is “Outro atendimento está com a conversa”. Spanish: “Otro servicio tiene la conversación”. Romanian: “Alt serviciu are conversația”. Other catalogs fall back to the English msgid. Add the three `msgstr` entries by hand. Do not run a full `makemessages` that rewrites unrelated catalogs.
- **Alternatives considered**: Portuguese as the msgid. Rejected. This tree’s gettext source is English.

## Decision: Filter Resend in Python or with an explicit NULL clause

- **Rationale**: `BulkActionMixin.post` passes a queryset (`Msg.objects.filter(org=org, id__in=ids)`) into `Msg.apply_action_resend`. `None != "H"` is true, so an empty reason must still be sent. SQL `exclude(failed_reason="H")` becomes `NOT (failed_reason = 'H')`, which drops NULL rows. Keep ids where the reason is NULL or any letter other than `H`. Call `msg_resend` only when at least one id remains. Use that message’s `org_id`. Do not change the client payload (`org_id`, `msg_ids`).
- **Alternatives considered**: Look up Redis `wac:thread_owner` at Resend time and allow `H` once the thread returns. Rejected. Thread ownership stays in Courier. This filter is permanent for that stored row. A new send uses another path and Courier decides again.

## Decision: No Mailroom code in this change

- **Rationale**: Index `msgs_next_attempt_out_errored` is outgoing + status `E` + `next_attempt` set. `fail_old_messages` and `fail_channel_outgoing_messages` select queued, pending, and errored only. The send-claim loop is not in this repository. `MailroomClient` does not read `failed_reason`.
- **Alternatives considered**: A Flows test that pretends to be the Mailroom worker. Rejected. Extend the channel-release task test and add a `Msg.fail_old_messages` case that an existing `F`+`H` row stays `F`+`H`. The worker test belongs in Mailroom.

## Decision: Screens

- **Rationale**: `ContactCRUDL.History` renders `templates/contacts/contact_history.haml` from `Event.from_msg` and returns the same events from `as_json`. The sentence goes on the broadcast row and on the `msg_created` / `ivr_created` / `product_sent` row. `MsgCRUDL.Failed` uses `msg_failed.haml`, which extends `message_box.haml`. The channel log status block in `channellog_read.haml` shows “Error” when `is_error` is set and never reads `failed_reason`; add the sentence there when the linked message reason is `H`, including error logs. Guard a missing `object.msg`.
- **Alternatives considered**: Add `failed_reason` to `MsgReadSerializer` and the spreadsheet. Rejected by AC-F4. Those feeds keep the status word `failed` and their current fields and columns.
