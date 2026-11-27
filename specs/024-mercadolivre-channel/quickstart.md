# Quickstart: validate the Mercado Livre channel in Flows

Run guide for the validation scenarios. Details of rules are in [data-model.md](data-model.md) and [contracts/identifiers.md](contracts/identifiers.md). This file holds no implementation code.

## Prerequisites

- The repository dependencies installed with Poetry and a reachable PostgreSQL database, as for the rest of the test suite.
- The branch `feat/meli-channel` checked out.

## 1. Automated checks

```bash
# new channel type tests (type, fields, conflict, claim page)
poetry run coverage run manage.py test temba.channels.types.mercadolivre

# URN scheme cases
poetry run coverage run manage.py test temba.contacts.tests.URNTest

# the whole channels group, as CI runs it
poetry run coverage run manage.py test temba.channels

# formatting, imports and missing migrations
./code_check.py
```

Expected: all green, no missing migration, no new `# pragma: no cover`.

## 2. Scenarios and expected outcomes

| Scenario | How to run | Expected |
|---|---|---|
| First channel for a seller | Test creates a channel with address `415458330` | One active `ML` channel, scheme `mercadolivre` |
| Address with spaces | Create with `" 415458330 "` | Stored address is `415458330` |
| Bad address | Create with blank, `abc` and `12 34` | `ValidationError` each time, no channel |
| Duplicate, same org | Create the same seller twice | Second call raises `ChannelAddressConflict`, one active channel remains |
| Duplicate, other org | Create the same seller in a second org | `ChannelAddressConflict`, message has no org or user name |
| Reconnect | Release the channel, create it again | New active channel is created |
| Two sellers | Create two different sellers | Both succeed |
| Two at the same time | The non-atomic test starts two threads on a barrier | Exactly one channel, one success, one `ChannelAddressConflict` |
| Fields | Create a channel in an org with no fields | Seven text fields exist |
| Fields reused | Pre-create `ml_pack_id` with another label | It keeps its label, type and values, the other six are created |
| Fields not duplicated | Create a second ML channel in the same org | Still seven fields |
| Field limit | Set the org limit to its current field count, then create a channel | Channel exists, no new field, a warning was logged |
| Release | Release the channel | Fields and their values remain |
| No flow | Org with no flow, trigger or campaign | Channel and fields exist |
| Claim page and list | Open `channels.channel_claim` and the channel list | Both load, the type is not listed as a claim option |
| URN | Validate `mercadolivre:162981404`, `mercadolivre:abc`, `mercadolivre:162981404:2000000089077943` | First valid, the other two invalid |
| Identity | Compare `mercadolivre:162981404#nick1` and `mercadolivre:162981404#nick2` | Same identity |

## 3. Pre-deploy data check

Read-only. It must return no row on every environment before the migration runs:

```sql
SELECT address, count(*)
FROM channels_channel
WHERE channel_type = 'ML' AND is_active
GROUP BY address
HAVING count(*) > 1;
```

Also check that no organization has an active contact field keyed `mercadolivre` (the scheme makes that key reserved):

```sql
SELECT org_id, id
FROM contacts_contactfield
WHERE key = 'mercadolivre' AND is_active;
```

## 4. After deploy

1. Confirm the migration applied: the channels migrations list shows the new migration after `0138_auto_20260910_2044`.
2. In a staging workspace, create one `ML` channel from a Django shell with a test seller id and confirm the seven fields in the workspace contact fields list.
3. Try to create the same seller in a second workspace and confirm the conflict error.
4. Confirm the Courier handler for `ML` serves `/c/ml/receive` before connecting a real seller (Courier task CO-01).

## Rollback

Release the test channels, reverse the migration, then revert the code. Do this only before a real seller is connected: afterwards the one-channel-per-seller guarantee would be lost.
