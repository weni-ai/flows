# Research: Outlook consent for an email channel

## Decision: Keep channel type `EM` and add a consent path beside the generic form

- **Decision**: The result is still an email channel (`channel_type=EM`, scheme `mailto`). Connect Outlook is a second entry on the existing email claim page. The generic form (username, password, SMTP, IMAP, pasted tokens) stays and keeps today's behavior.
- **Rationale**: The spec says the result is the email channel the product already uses, and that the generic setup must not change. Courier already treats `EM` as "sender address is `config.username`, transport is the email proxy."
- **Alternatives considered**: A new channel type code for Outlook — rejected. Courier and email-proxy both select on `EM`. A second type would need a Courier handler and a proxy watcher for no user-facing difference.

## Decision: One sign-in approves Graph and Outlook; the two grants are redeemed separately

- **Decision**: The authorize request on the `common` tenant lists `CONSENT_SCOPES` in this order: `offline_access`, `openid`, `email`, `profile`, `https://graph.microsoft.com/Mail.Send`, `https://graph.microsoft.com/Mail.ReadWrite`, `https://graph.microsoft.com/User.Read`, `https://outlook.office.com/IMAP.AccessAsUser.All`, `https://outlook.office.com/SMTP.Send`. `prompt=select_account`. The code exchange sends only `GRAPH_SCOPES` (that list without the two Outlook scopes) and requires a refresh token. A second token call, `grant_type=refresh_token` with `OUTLOOK_SCOPES` (`offline_access` plus the two Outlook scopes), redeems the IMAP/SMTP access token. That second call is not a retry and is not itself retried. Microsoft rotates the refresh token on the second call. The refresh token stored on the channel is the one the Outlook grant returns, or the Graph refresh token when the Outlook grant does not return one. The same value is written to `refresh_token` and `graph_send_refresh_token`. `graph_send_access_token` is the Graph access token. `access_token` is the Outlook access token.
- **Rationale**: The admin approves once. The channel needs a Graph grant (`Mail.Send`, `Mail.ReadWrite`, `User.Read`) and an Outlook grant (`IMAP.AccessAsUser.All`, `SMTP.Send`). `offline_access` is what makes Microsoft return a refresh token. `openid`, `email`, and `profile` make Microsoft return an `id_token`. Putting Graph and Outlook scopes on one token request fails with `AADSTS28000`, because one token response cannot mix those two resources. Consent can list both resources; each token request names one. `common` plus `prompt=select_account` accepts Outlook.com, Hotmail, Live, and Microsoft 365 work or school accounts.
- **Alternatives considered**: Three Outlook scopes only, with no Graph grant — rejected. The channel has to store a Graph send grant as well as the IMAP/SMTP grant. Two browser logins, Graph then Outlook — rejected. The admin approves once. Asking the code exchange for every consented scope — rejected, because that is the request Microsoft answers with `AADSTS28000`. Application permissions such as `IMAP.AccessAsApp` — rejected because they are tenant-wide.

## Decision: Read the mailbox from the Graph token, and from the id token when that token is opaque

- **Decision**: If the Graph access token is a JWT, verify it (RS256, Microsoft JWKS, `aud` is `https://graph.microsoft.com` or the Graph app id `00000003-0000-0000-c000-000000000000`, v2 issuer, `exp`) and read the mailbox from `preferred_username`, then `upn`, then `email`, then `unique_name`, the first value that contains `@`. If the Graph access token is not a JWT, or that claim is missing, verify `id_token` with `aud` equal to `APP_MICROSOFT_CLIENT_ID` and read the same claims. If neither yields a mailbox, fail with logged code `token_mailbox` and create no channel. The channel is written only when that mailbox equals the address stored on the attempt. When the Outlook access token is a JWT, verify `aud` `https://outlook.office.com` before storing it. When it is opaque, store it without that check.
- **Rationale**: Work and school Graph tokens are JWTs and carry the mailbox. Personal Microsoft accounts return opaque Graph tokens (`EwB…`) and opaque Outlook tokens (`M.C…`). Those opaque tokens have no verifiable mailbox claim. The `id_token` from `openid`/`email`/`profile` is a JWT whose audience is the app, and it carries the signed-in address. Trusting the address the admin typed, without a Microsoft claim, would let a return create a channel for an account the admin did not sign in as.
- **Alternatives considered**: Rejecting every non-JWT Graph token (`graph_token`) — rejected. That blocks every personal mailbox. Reading the mailbox only from the Outlook access token — rejected for the same reason: the personal Outlook token is opaque. Skipping verification of a JWT — rejected. A JWT with the wrong audience or issuer creates no channel.

## Decision: Account-specific send host, fixed receive host, empty password, provider flag

- **Decision**: On success, Flows writes the existing email config keys plus `oauth_provider=microsoft` and `oauth_status=active`:

  | Key | Value |
  |---|---|
  | `username` | primary address the admin confirmed, lowercased, equal to the mailbox read above |
  | `password` | empty |
  | `smtp_host` | `smtp.office365.com` when the Outlook access token is a JWT; `smtp-mail.outlook.com` when it is opaque |
  | `smtp_port` | `587` |
  | `imap_host` | `outlook.office365.com` |
  | `imap_port` | `993` |
  | `access_token` | Outlook access token from the refresh-token grant |
  | `refresh_token` | refresh token from that grant, or the Graph refresh token when Microsoft does not rotate it |
  | `graph_send_access_token` | Graph access token from the code exchange |
  | `graph_send_refresh_token` | the same refresh token as `refresh_token` |
  | `oauth_provider` | `microsoft` |
  | `oauth_status` | `active` |
  | `callback_domain` | `settings.HOSTNAME`, same as the generic claim |

  The admin confirms only the primary address. Hosts, ports, and tokens are written by the server. Name and address of the channel are that primary address.

- **Rationale**: email-proxy already reads `imap_host`, `imap_port`, `smtp_host`, `smtp_port`, `username`, `password`, `access_token`, and `refresh_token` from `channels_channel.config`. `graph_send_access_token` and `graph_send_refresh_token` are additive. Courier's send path uses `username` as the From address and does not read the tokens. An empty password is what makes the proxy's SMTP path use the bearer token instead of a password login. Personal Outlook SMTP is `smtp-mail.outlook.com`; work and school SMTP is `smtp.office365.com`. The shape of the Outlook access token is what distinguishes them: a JWT is a work or school token, and an opaque token is a personal one. IMAP stays on `outlook.office365.com` for both.
- **Alternatives considered**: Storing only the refresh token and letting Flows refresh — rejected. Microsoft rotates refresh tokens; two writers would invalidate each other. The proxy is already the Gmail refresher.

## Decision: email-proxy must learn Microsoft before send and receive work

- **Decision**: This Flows change does not send or poll mail. Courier is unchanged. Mailroom is unchanged. Send and receive keep going Courier → email-proxy, and the proxy reads the channel row. A companion change in `weni-ai/email-proxy` is required before an Outlook channel can pass SC-004. Until that proxy release, Connect Outlook must stay hidden unless `APP_MICROSOFT_CLIENT_ID` is set, and operators must not set it in production before the proxy change.
- **Rationale**: In the proxy today, IMAP uses XOAUTH2 only when `imap_host` contains `gmail` (`internal/mailer/reader.go`). Any other host, including `outlook.office365.com`, uses password login. Token refresh in both the reader and `server/handlers/send.go` posts to `https://accounts.google.com/o/oauth2/token` with the Google client. An Outlook refresh token sent there fails, and a failed IMAP auth disables that watcher. Shipping the button before the proxy change would create channels that cannot read mail and whose tokens the proxy would try to refresh at Google.
- **Alternatives considered**: Implementing IMAP/SMTP inside Flows — rejected. It would duplicate the proxy and bypass Courier. Refreshing the Microsoft token from a Flows Celery task — rejected because of refresh-token rotation and because IMAP still would not use XOAUTH2 for a non-Gmail host.

## Decision: The proxy is the only component that refreshes, and it records withdrawal

- **Decision**: Flows writes both grants and replaces them only when an admin completes consent again for a channel already marked `oauth_status=needs_reconnect`. That replacement also writes the send host for the new Outlook token. email-proxy, in the companion change, refreshes at `https://login.microsoftonline.com/common/oauth2/v2.0/token` when `oauth_provider=microsoft`, using the same client id and secret from its environment. `refresh_token` and `graph_send_refresh_token` hold the same refresh token. A refresh rotates it, so the proxy writes the newest refresh token to both keys in the same update before it redeems the other resource. On `invalid_grant` it sets `oauth_status=needs_reconnect`, stops polling that channel, and does not send. Flows only displays that status. Flows does not add a refresh task.
- **Rationale**: Spec FR-012 and FR-013. One writer avoids rotation races. Leaving the old refresh token on the other key makes the next redemption fail, because Microsoft invalidates the token it just rotated. The channel page already shows name and address and does not render `config`, so the banner is the only new surface. Permanent refusal is not retried.
- **Alternatives considered**: Flows polls Graph or the token endpoint on a schedule — rejected, same rotation problem. Deleting the channel on withdrawal — rejected. The spec says show that it needs to be connected again.

## Decision: Flows owns the screen, as a confidential server flow

- **Decision**: There is no separate frontend and no JSON handoff of the authorization code. The email claim page asks for the primary mailbox address. Its form posts with `target="_top"`, because Microsoft sets `X-Frame-Options: deny` and will not render inside the product frame. Microsoft returns to the Flows callback. The client id and secret are `APP_MICROSOFT_CLIENT_ID` and `APP_MICROSOFT_CLIENT_SECRET`. The secret never reaches the browser. The authorize URL is the one in the contract: `prompt=select_account`, `CONSENT_SCOPES` in the order above, and PKCE S256. The Redis attempt stores `org_id`, `user_id`, the confirmed address, and the PKCE verifier for 900 seconds. The callback deletes it before any channel write. Both token calls send `client_secret`, time out at 10 seconds, and are not retried. The code exchange also sends `code_verifier`. The channel is created only when the mailbox from the Graph token or the id token equals the address stored on the attempt. `redirect_uri` is the absolute URL of the Flows callback and is the same value on the authorize request and the code exchange. The refresh-token grant does not send `redirect_uri`.
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

- **Decision**: `EmailType.deactivate` removes `access_token`, `refresh_token`, `graph_send_access_token`, and `graph_send_refresh_token` from the config before `Channel.release` saves `is_active=False`. There is no call to Microsoft's revoke endpoint.
- **Rationale**: email-proxy only loads `is_active=true` channels, so release already stops use. Clearing both grants means a later reactivation cannot keep sending with the old grant. The spec puts disconnecting the Microsoft app registration out of scope. A later connect of the same mailbox has no stored grant, so it needs a new consent.
- **Alternatives considered**: Leaving the tokens on the inactive row — weaker than the spec's "stops using that permission." Calling Microsoft revoke — out of scope, and it would revoke every mailbox consented for that app client, not one channel.

## Decision: Logs and the page never carry the grant or the mailbox address

- **Decision**: Consent failures log the opaque org id, user id, and Microsoft's `error` code only. They do not log `error_description`, the authorization code, either token, or the mailbox address. The claim page may show Microsoft's `error_description` to the admin who just returned from Microsoft. The claim response, the channel page, and the success message show the mailbox address and never the tokens. Sentry context for a failed consent uses those same opaque ids.
- **Rationale**: Principle II, III, and XIII. The description helps the admin recover and can echo the mailbox, so it stays on the page and out of the log. The channel address is already the product's display of the mailbox; the secret is the grant.
