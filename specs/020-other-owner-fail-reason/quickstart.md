# Quickstart: Other-owner failure reason

Validation guide for [spec.md](./spec.md). Field rules are in [data-model.md](./data-model.md). Payloads are in [contracts/other-owner-failure.md](./contracts/other-owner-failure.md).

## Prerequisites

- Repository dependencies installed (`poetry install`).
- No Courier or Mailroom process is required. Tests stub `MailroomClient.msg_resend` and write `failed_reason` on the message row directly.

## Checks

From the repository root:

```bash
poetry run coverage run manage.py test \
  temba.msgs.tests.MsgCRUDLTest.test_failed \
  temba.msgs.tests.MsgTasksTest.test_fail_channel_outgoing_messages_task \
  temba.mailroom.tests.EventTest.test_from_msg \
  temba.contacts.tests.ContactTest.test_history \
  temba.channels.tests.ChannelLogTest
```

`test_history` lives on `ContactTest` in `temba/contacts/tests.py`. `ChannelLogTest` is the existing log-page class; add the reason-`H` assertion there and keep that class in this command.

Then:

```bash
./code_check.py
```

`code_check.py` includes the missing-migration check. The new migration must be present, depend on `msgs.0175_merge_20260910_2109`, alter `failed_reason` choices only, leave the column nullable, and add no check constraint.

## Expected outcomes

- An outgoing message stored as failed with reason `H` shows “Another service has the conversation” in contact history (HTML), on the failed-messages list, and on an error channel log. Under `translation.override("pt-br")` the history string is exactly “Outro atendimento está com a conversa”.
- `Event.from_msg` for that message includes `failed_reason_display` and still includes status, text, and the existing keys. Events for other reasons do not include that key.
- Resend of only reason `H` does not call `msg_resend`. A mixed selection calls it with the other ids only. An empty reason and reasons `S`, `L`, `E`, `O`, and `D` are still included. Each omitted message stays failed with reason `H`.
- `fail_channel_outgoing_messages` and `Msg.fail_old_messages` leave an existing `F` + `H` message unchanged.
- Public message reads and export tests that already expect status `failed` stay green, with the same fields and columns.
- `./code_check.py` exits clean. No new `# pragma: no cover`.

## Release note

The release note is the `feat:` bullet under heading `3.114.0` in `WENI-CHANGELOG.md`: the operator sentence, and that Resend leaves a message failed with reason `H` on the list. Do not edit `CHANGELOG.md`.
