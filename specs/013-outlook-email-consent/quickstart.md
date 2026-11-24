# Quickstart: Outlook consent for an email channel

Validates the Flows slice. It does not open a real Microsoft session and it does not prove email-proxy send/receive. That proxy change is described in [contracts/outlook-email-channel.md](./contracts/outlook-email-channel.md).

## Prerequisites

- Repo dependencies installed (`poetry install`)
- No Azure app is required for the automated tests. They mock the token endpoint and the JWKS.
- To click through a real consent later: an Azure app whose Web redirect URI is the Flows callback, `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET` set in the environment, and the email-proxy companion already deployed. Do not set the client id in production before that proxy release.

## Automated checks

From the repo root:

```bash
poetry run coverage run manage.py test temba.channels.types.email
./code_check.py
```

`temba.channels.types.email` runs in the `channels` CI group. Expected outcomes, mapped to the spec:

| Check | Expected |
|---|---|
| Existing generic claim test | Still creates an `EM` channel from posted username, password, hosts, and tokens. No `oauth_provider`. |
| Approved consent, work mailbox | The test posts the primary address, then returns a signed Graph token and a signed Outlook token for that same mailbox. One `EM` channel. `name` and `address` are that address. `smtp_host` is `smtp.office365.com`. Config matches [data-model.md](./data-model.md), including `graph_send_access_token` and `graph_send_refresh_token`. The HTML does not contain any token. The start form does not post a password or server fields, and it targets the top window. |
| Approved consent, Outlook.com mailbox | The Graph token and the Outlook token are opaque. The mailbox comes from `id_token`. `smtp_host` is `smtp-mail.outlook.com`. One `EM` channel addressed to the confirmed mailbox. |
| Scopes on the redirect | `offline_access`, `openid`, `email`, `profile`, `Mail.Send`, `Mail.ReadWrite`, `User.Read`, `IMAP.AccessAsUser.All`, `SMTP.Send`, in that order. The code exchange requests the Graph scopes only, including `openid`, `email`, and `profile`. |
| Address mismatch, or no mailbox | A mailbox identity that differs from the confirmed address creates no channel. A return with neither a signed Graph token nor a signed id token creates no channel. |
| Deny, Microsoft `error`, expired or unknown `state`, mismatched user or org | Channel count unchanged. `access_denied` returns to the form. `AADSTS65001` shows the admin-approval link. Another error shows `error_description` and does not log it. |
| Same address already active in the org | No second row. |
| Two completions for one new address | One row. |
| Same address with `oauth_status=needs_reconnect` | Same row, both grants and `smtp_host` replaced, status `active`. |
| User without `channels.channel_claim` | No row. |
| Release | `is_active` false and `access_token`, `refresh_token`, `graph_send_access_token`, and `graph_send_refresh_token` gone. A later consent is a new approval. |
| Empty `APP_MICROSOFT_CLIENT_ID` | The primary-address form is absent and start does not redirect to Microsoft. |

The tests must not call `login.microsoftonline.com`. Token HTTP is mocked. Renewal after an hour and `invalid_grant` are proxy behavior; Flows tests assert the config the proxy reads, not a live IMAP session.

## Manual smoke (only after the proxy companion is deployed)

1. Set the client id and secret. Open the email claim page as an org admin. Enter the primary mailbox address and continue to Microsoft. The Microsoft page replaces the product page; it does not stay inside a frame. Approve once, with that same mailbox. The approval lists the Microsoft mail permissions and the mailbox-server permissions together.
2. Confirm the new channel's address is that mailbox and that the page does not show a token.
3. Send and receive one message through the existing email channel path. That step fails closed until email-proxy treats `oauth_provider=microsoft` as XOAUTH2 and refreshes at the Microsoft token endpoint.
4. Deny consent on a second attempt. Confirm no extra channel appears.
