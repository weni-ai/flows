# Research: Outlook consent for an email channel

## Decision: Keep channel type `EM` and add a consent path beside the generic form

- **Decision**: The result is still an email channel (`channel_type=EM`, scheme `mailto`). Connect Outlook is a second entry on the existing email claim page. The generic form (username, password, SMTP, IMAP, pasted tokens) stays and keeps today's behavior.
- **Rationale**: The spec says the result is the email channel the product already uses, and that the generic setup must not change. Courier already treats `EM` as "sender address is `config.username`, transport is the email proxy."
- **Alternatives considered**: A new channel type code for Outlook — rejected. Courier and email-proxy both select on `EM`. A second type would need a Courier handler and a proxy watcher for no user-facing difference.

## Decision: Authorize IMAP and SMTP for the signed-in mailbox, not Microsoft Graph

- **Decision**: The consent requests exactly three delegated scopes on the `common` tenant, in this order: `offline_access`, `https://outlook.office.com/IMAP.AccessAsUser.All`, `https://outlook.office.com/SMTP.Send`. No `openid`, no `email`, no Graph scope. The access token's audience is `https://outlook.office.com`. The mailbox address is read from that access token, in order: `upn`, then `preferred_username`, then `unique_name`, and only when the value contains `@`.
- **Rationale**: The consent is limited to the three scopes named for this feature. `offline_access` is first because, without it, Microsoft does not return a refresh token. email-proxy sends with SMTP and reads with IMAP using XOAUTH2, so the token audience has to be the Outlook resource. `IMAP.AccessAsUser.All` and `SMTP.Send` are delegated to the signed-in user. `common` plus `prompt=select_account` accepts Outlook.com, Hotmail, Live, and Microsoft 365 work or school accounts. Without `openid` there is no ID token; the Outlook access token still carries the signed-in account.
- **Alternatives considered**: Adding `openid` and `email` to read an ID token — rejected because the consent list is closed at these three scopes. Graph `Mail.Send`, `Mail.Read`, or `User.Read` — rejected because Microsoft refuses an authorization that names two resources, and a Graph token does not authenticate IMAP. Application permissions such as `IMAP.AccessAsApp` — rejected because they are tenant-wide.

## Decision: Fixed Outlook hosts, empty password, provider flag

- **Decision**: On success, Flows writes the existing email config keys plus `oauth_provider=microsoft` and `oauth_status=active`:

  | Key | Value |
  |---|---|
  | `username` | primary address the admin confirmed, lowercased, equal to the access-token mailbox |
  | `password` | empty |
  | `smtp_host` | `smtp.office365.com` |
  | `smtp_port` | `587` |
  | `imap_host` | `outlook.office365.com` |
  | `imap_port` | `993` |
  | `access_token` | token from the code exchange |
  | `refresh_token` | refresh token from the code exchange |
  | `oauth_provider` | `microsoft` |
  | `oauth_status` | `active` |
  | `callback_domain` | `settings.HOSTNAME`, same as the generic claim |

  The admin confirms only the primary address. Hosts, ports, and tokens are written by the server. Name and address of the channel are that primary address.

- **Rationale**: email-proxy already reads `imap_host`, `imap_port`, `smtp_host`, `smtp_port`, `username`, `password`, `access_token`, and `refresh_token` from `channels_channel.config`. Courier's send path uses `username` as the From address and does not read the tokens. An empty password is what makes the proxy's SMTP path use the bearer token instead of a password login.
- **Alternatives considered**: Storing only the refresh token and letting Flows refresh — rejected. Microsoft rotates refresh tokens; two writers would invalidate each other. The proxy is already the Gmail refresher.

## Decision: email-proxy must learn Microsoft before send and receive work

- **Decision**: This Flows change does not send or poll mail. Courier is unchanged. Mailroom is unchanged. Send and receive keep going Courier → email-proxy, and the proxy reads the channel row. A companion change in `weni-ai/email-proxy` is required before an Outlook channel can pass SC-004. Until that proxy release, Connect Outlook must stay hidden unless `APP_MICROSOFT_CLIENT_ID` is set, and operators must not set it in production before the proxy change.
- **Rationale**: In the proxy today, IMAP uses XOAUTH2 only when `imap_host` contains `gmail` (`internal/mailer/reader.go`). Any other host, including `outlook.office365.com`, uses password login. Token refresh in both the reader and `server/handlers/send.go` posts to `https://accounts.google.com/o/oauth2/token` with the Google client. An Outlook refresh token sent there fails, and a failed IMAP auth disables that watcher. Shipping the button before the proxy change would create channels that cannot read mail and whose tokens the proxy would try to refresh at Google.
- **Alternatives considered**: Implementing IMAP/SMTP inside Flows — rejected. It would duplicate the proxy and bypass Courier. Refreshing the Microsoft token from a Flows Celery task — rejected because of refresh-token rotation and because IMAP still would not use XOAUTH2 for a non-Gmail host.

## Decision: The proxy is the only component that refreshes, and it records withdrawal

- **Decision**: Flows writes the initial token pair and replaces it only when an admin completes consent again for a channel already marked `oauth_status=needs_reconnect`. email-proxy, in the companion change, refreshes at `https://login.microsoftonline.com/common/oauth2/v2.0/token` when `oauth_provider=microsoft`, using the same client id and secret from its environment. On `invalid_grant` it sets `oauth_status=needs_reconnect`, stops polling that channel, and does not send. Flows only displays that status. Flows does not add a refresh task.
- **Rationale**: Spec FR-012 and FR-013. One writer avoids rotation races. The channel page already shows name and address and does not render `config`, so the banner is the only new surface. Permanent refusal is not retried.
- **Alternatives considered**: Flows polls Graph or the token endpoint on a schedule — rejected, same rotation problem. Deleting the channel on withdrawal — rejected. The spec says show that it needs to be connected again.

## Decision: Flows owns the screen, as a confidential server flow

- **Decision**: There is no separate frontend and no JSON handoff of the authorization code. The email claim page asks for the primary mailbox address and then redirects the whole browser to Microsoft. Microsoft returns to the Flows callback. The client id and secret are `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET`. The secret never reaches the browser. The authorize URL is the one in the contract: `prompt=select_account`, the three scopes in the order above, and PKCE S256. The Redis attempt stores `org_id`, `user_id`, the confirmed address, and the PKCE verifier for 900 seconds. The callback deletes it before any channel write. The code exchange sends `client_secret` and `code_verifier`, times out at 10 seconds, and is not retried. The access token is verified with PyJWT (`aud` is `https://outlook.office.com`, v2 issuer, `exp`). The channel is created only when the token mailbox equals the address stored on the attempt. `redirect_uri` is the absolute URL of the Flows callback and is the same value on the authorize request and the token request.
- **Rationale**: `microsoft-oauth-frontend.md` describes a separate screen that confirms the primary address, opens Microsoft, and gives the code to the service that writes the channel. In this repository that screen is Flows. A public client such as MSAL in the browser would mint a refresh token the email-proxy does not renew, so the code is exchanged on the server. PKCE stays because Flows builds the redirect and the exchange; it does not turn the browser into the client that holds the secret. Redis holds the attempt because the workers are stateless and a single session key would collapse two overlapping attempts. The confirmed address is stored before the redirect so the return query cannot substitute an alias or another mailbox.
- **Alternatives considered**: A frontend that posts `{code, redirect_uri, state, username}` — rejected. This repo renders the admin screen, and accepting the address again on the return would trust the client. Dropping PKCE — rejected. The document avoids PKCE only to avoid a public-client refresh token, which this flow does not create. State only in the Django session — rejected for overlapping attempts.

## Decision: Microsoft errors are shown on the claim page and not logged in full

- **Decision**: `access_denied`, or the admin leaving Microsoft before approving, returns to the form and creates nothing. `consent_required` or `AADSTS65001` tells the admin that a Microsoft 365 administrator must allow the app and links to `https://login.microsoftonline.com/common/adminconsent?client_id={APP_MICROSOFT_CLIENT_ID}`. A state that does not match the attempt tells the admin to start again. Any other Microsoft `error` is shown with Microsoft's `error_description` and creates nothing. Logs record the `error` code only.
- **Rationale**: The admin is the person who just saw Microsoft's page, so the description is the message that lets them recover. The same description can echo the mailbox, so it stays off the log and off Sentry. Personal accounts approve during their own login. The admin-approval link is only the recovery for a work tenant that has not allowed the app.
- **Alternatives considered**: Hiding every Microsoft description behind one generic sentence — rejected. The admin cannot tell a tenant block from a cancelled login. Logging `error_description` — rejected because it can contain the mailbox.

## Decision: One active email channel per org and mailbox, without a migration

- **Decision**: Inside `transaction.atomic`, take a Postgres transaction advisory lock on `(org_id, lowercased address)`, then look up an active `EM` channel in that org with that address. If none, create. If one exists and it is a Microsoft channel with `oauth_status=needs_reconnect`, replace its tokens and set `oauth_status=active`. Any other existing channel (generic password channel, or a Microsoft channel that is still `active`) does not get a second row; the admin is told the mailbox is already connected. No unique index and no migration.
- **Rationale**: FR-010 forbids a second channel. A unique index on `(org, channel_type, address)` could fail the deploy if production already has duplicate active email rows, and it would change the generic claim. The advisory lock serializes the two concurrent consents the spec calls out. Replacing tokens on `needs_reconnect` is what lets the admin connect again without a second channel; refusing that case would leave FR-013 with no recovery other than delete-and-recreate, which the spec reserves for removal.
- **Alternatives considered**: A partial unique index — rejected for this change because existing rows are unknown and the generic claim must stay. Always rejecting when any row exists — rejected because a withdrawn Outlook channel could never be restored in place.

## Decision: Release clears the tokens; Flows does not revoke the Microsoft app

- **Decision**: `EmailType.deactivate` removes `access_token` and `refresh_token` from the config before `Channel.release` saves `is_active=False`. There is no call to Microsoft's revoke endpoint.
- **Rationale**: email-proxy only loads `is_active=true` channels, so release already stops use. Clearing the tokens means a later reactivation cannot keep sending with the old grant. The spec puts disconnecting the Microsoft app registration out of scope. A later connect of the same mailbox has no stored grant, so it needs a new consent.
- **Alternatives considered**: Leaving the tokens on the inactive row — weaker than the spec's "stops using that permission." Calling Microsoft revoke — out of scope, and it would revoke every mailbox consented for that app client, not one channel.

## Decision: Logs and the page never carry the grant or the mailbox address

- **Decision**: Consent failures log the opaque org id, user id, and Microsoft's `error` code only. They do not log `error_description`, the authorization code, either token, or the mailbox address. The claim page may show Microsoft's `error_description` to the admin who just returned from Microsoft. The claim response, the channel page, and the success message show the mailbox address and never the tokens. Sentry context for a failed consent uses those same opaque ids.
- **Rationale**: Principle II, III, and XIII. The description helps the admin recover and can echo the mailbox, so it stays on the page and out of the log. The channel address is already the product's display of the mailbox; the secret is the grant.
