# Quickstart: validate the Mercado Livre OAuth claim in Flows

Run guide for the validation scenarios. Rules are in [data-model.md](data-model.md) and [contracts/claim-and-config.md](contracts/claim-and-config.md). This file holds no implementation code.

## Prerequisites

- The repository dependencies installed with Poetry, a reachable PostgreSQL database and Redis, as for the rest of the test suite.
- The branch `feat/meli-oauth` checked out, on top of the feature 024 code.
- No ML credentials are needed for the automated checks. ML is mocked.

## 1. Automated checks

```bash
# all tests of the ML type (feature 024 and this feature)
poetry run coverage run manage.py test temba.channels.types.mercadolivre

# the channels group, as CI runs it
poetry run coverage run manage.py test temba.channels

# formatting, imports and missing migrations (expect none)
./code_check.py
```

Expected: all green, no missing migration, no new `# pragma: no cover`.

## 2. Scenarios and expected outcomes

ML is mocked, and each scenario is one test.

| Scenario | How to run | Expected |
|---|---|---|
| Not configured | Empty settings, open the claim page and POST start | Type not listed, notice shown, no redirect |
| Start | Admin POSTs start with settings set | 302 to the ML authorize address with `response_type`, `client_id`, `redirect_uri`, `state`, `code_challenge`, `code_challenge_method=S256`, `scope`. The verifier is not in the address |
| Start by GET | GET on start | 405 |
| Permission | Editor without `channel_claim` and a signed-out client call start and callback | Denied, no attempt |
| Full flow | Start, then callback with the returned `state` and a code, ML mocked with seller `415458330` and nickname `SELLER_X` | One active `ML` channel, address `415458330`, name `SELLER_X`, redirect to the channel page, seven `ml_*` fields exist |
| Config | Read the channel config after the full flow | The seven keys of the contract, `expires_at` parseable as RFC 3339, both switches `false`, no client id or secret |
| Verifier | Inspect the token call | `code_verifier` matches the `code_challenge` of the start (S256), `redirect_uri` equals the setting |
| No nickname | Account answer without `nickname` | Name is the seller id |
| Long nickname | Nickname of 200 characters | Name is cut to 128 |
| State unknown, missing or expired | Callback with each | Message, no call to ML, no channel |
| State replay | Same return twice | First succeeds, second is rejected, one channel |
| State foreign | Return by another user, then by a user of another org | Rejected, attempt of the owner still works |
| Two returns at once | Non-atomic test, two threads on a barrier | Exactly one channel, one rejected return, one token call |
| Session ends before the return | Sign out after start, call the callback, sign in as the same user and call the same address; repeat with another user | Redirect to sign in with the callback address as `next`. The same user completes the connection, the other user is rejected as foreign |
| Cancelled | Return with `error=access_denied` | Message that it was not completed, attempt consumed, no channel |
| Collaborator | Return with `error=invalid_operator_user_id`, and the same code in the token answer | Message that asks for the administrator, no channel |
| Unknown ML error | Return with `error=server_error` | Generic message, no provider text on the page |
| Hostile error value | `error` with newlines, markup and 500 characters | Page and log carry no raw text |
| Token call fails | Mock timeout, HTTP 400, HTTP 500, non-JSON, and each missing field | Generic message, one Sentry report, no channel, no contact field |
| Seller mismatch | Account `id` differs from token `user_id` | Rejected, reported, no channel |
| Account call fails | Mock 401 and timeout on `/users/me` | Rejected, reported, no channel |
| Duplicate seller | Connect the same seller twice, then from another org | "Already connected" message, one active channel, no organization or user name in the message |
| Activation fails | Patch the contact field use case to raise during the connection | Generic message, one Sentry report, no active `ML` channel, no tokens in the released row, attempt consumed |
| Reconnect after release | Release the channel, connect again | New active channel |
| Release | Release a connected channel and read its config | No `access_token` and no `refresh_token`, no call to ML |
| Privacy of logs | Capture logs and Sentry calls during a failure and a success | Values of tokens, secret, code, verifier, nickname and seller id are absent |
| Privacy of surfaces | Request the channel read page, the channel list, the v2 API channel list (`api.v2.channels`) and the internal channel endpoint (`channels-by-project`) | None contains a token value |
| Constants | Search the module | No literal address, scope, key or error code outside the named constants |

## 3. Manual check in a real environment (after deploy)

1. Register the redirect URI `https://<public host>/channels/types/mercadolivre/callback` in the ML application, and set the three `APP_MERCADOLIVRE_*` variables in the environment.
2. With a seller administrator account, open the claim page, connect, and confirm one active `ML` channel with the seller id and nickname.
3. Check in the database that the channel config holds the contract keys, and that the logs of the connection hold no token.
4. Try again with the same seller. Expect the "already connected" message.
5. Try with a collaborator account. Expect the message that asks for the administrator.
6. To test inbound processing later, an operator sets `post_sale_enabled` to `true` in the channel config. There is no screen for it until RP-05.

## 4. Rollback

Leave the three settings empty. The type disappears from the claim page and the start endpoint does nothing. Channels already created are not affected. No migration is involved.
