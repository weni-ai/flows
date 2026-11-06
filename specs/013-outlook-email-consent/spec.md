# Engineering Spec: Outlook consent for an email channel

**Feature Branch**: `013-outlook-email-consent`

**Created**: 2026-11-04

**Status**: Draft

**Cycle**: SDD Full

**Input**: User description: "quero criar um fluxo de consentimento oauth para criar um canal do tipo email para o outlook"

## Origin Without Product Spec

- Product Spec: none
- Problem: An org admin can add an email channel only by typing mailbox credentials and mail-server settings. There is no Microsoft consent step that creates an email channel for an Outlook mailbox.
- Acceptance criteria:
  - AC-1: An org admin confirms the primary mailbox address, completes Microsoft sign-in and consent for that same address, and gets exactly one email channel for it, without typing a password or mail-server settings.
  - AC-2: A denied, cancelled, expired, mismatched, or duplicate consent attempt creates no new channel, and the admin can start again.
  - AC-3: The permission keeps the channel usable after the short-lived grant expires, until the admin removes the channel or Microsoft withdraws the permission.
  - AC-4: The secret grant is never shown to the admin, and a consent return that was not started by that admin for that org does not create a channel.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect an Outlook mailbox (Priority: P1)

An org admin who can add channels chooses to connect Outlook and confirms the primary address of the mailbox. An alias is not accepted. The product sends them to Microsoft to sign in and approve that mailbox. They return and see a new email channel addressed to that primary mailbox. They never type the mailbox password or mail-server settings.

**Why this priority**: This is the only path that turns consent into an email channel. Without it, Outlook still requires the manual credential form.

**Independent Test**: As an org admin, confirm a primary mailbox address, approve consent for that same mailbox when it is not already connected in that org, and confirm one email channel exists for that address and the secret grant is not on screen.

**Acceptance Scenarios**:

1. **Given** an org admin who can add channels and a primary Outlook address that is not already an email channel in that org, **When** they confirm that address and finish Microsoft sign-in for the same mailbox, **Then** the org has exactly one new email channel whose address and name are that primary address.
2. **Given** the Connect Outlook path, **When** the admin goes through it, **Then** the product does not ask for a mailbox password, SMTP host, SMTP port, IMAP host, or IMAP port.
3. **Given** a finished consent, **When** the admin views the new channel, **Then** they see the mailbox address and they do not see the secret grant.
4. **Given** a Microsoft 365 work or school mailbox, or an Outlook.com, Hotmail, or Live mailbox, **When** the admin confirms that primary address and signs in with that account, **Then** an email channel is created for that address.
5. **Given** the Microsoft approval screen for Connect Outlook, **When** the admin is asked to approve, **Then** the request is only `IMAP.AccessAsUser.All`, `SMTP.Send`, and `offline_access` for the mailbox they signed in with, not for every mailbox in the organization.
6. **Given** a successful consent, **When** the org uses that email channel, **Then** the platform can send mail as that mailbox and receive mail sent to it without asking the admin to approve again for each message.

---

### User Story 2 - A failed consent creates nothing (Priority: P2)

The admin denies access, closes Microsoft before finishing, comes back too late, or Microsoft reports an error. No email channel is created. The admin sees what happened and can start Connect Outlook again. If that org already has an email channel for the same mailbox, a second one is not created.

**Why this priority**: A consent flow that creates a channel on a failed or repeated attempt leaves the org with a mailbox it did not successfully authorize.

**Independent Test**: Run each failure below as an org admin and confirm the org's email channels are unchanged, then complete a fresh consent and confirm a channel is created only then.

**Acceptance Scenarios**:

1. **Given** an admin who has started Connect Outlook, **When** they deny consent or leave Microsoft before approving, **Then** no email channel is created and they can start again.
2. **Given** Microsoft returns an error, or the admin returns after the consent attempt has expired, **When** the product receives that return, **Then** no email channel is created and the admin sees why it did not finish. A work account that still needs an administrator to allow the app is told that, and is offered the Microsoft admin-approval link. Any other Microsoft error is shown as Microsoft described it.
3. **Given** a consent return that does not match the org, the admin, or the attempt that was started, **When** the product receives it, **Then** no email channel is created and the admin is told to start the login again.
4. **Given** the org already has an email channel for that mailbox address, **When** an admin completes consent for the same address, **Then** no second channel is created and the admin is told the mailbox is already connected.
5. **Given** the admin confirmed an alias, or signs in at Microsoft with a different address from the one they confirmed, **When** the product handles that result, **Then** no email channel is created and the admin is told the Microsoft account does not match the primary address.
6. **Given** a user who cannot add channels, **When** they try to start or finish Connect Outlook, **Then** no email channel is created.

---

### User Story 3 - The permission stays usable, and removal stops it (Priority: P3)

The day after connecting, the admin does not have to consent again for the channel to keep sending and receiving, as long as Microsoft still allows it. If Microsoft withdraws the permission, the channel is shown as needing to be connected again and is not treated as authorized. When the admin removes the channel, the platform stops using that permission. Connecting the same mailbox later requires a new consent.

**Why this priority**: A channel that dies when the short-lived grant expires, or that keeps sending after removal, is not a finished connection.

**Independent Test**: Connect a mailbox, confirm it is still authorized after the short-lived grant would have expired, then withdraw or remove it and confirm it is no longer treated as authorized.

**Acceptance Scenarios**:

1. **Given** an email channel created by a successful Outlook consent, **When** the short-lived grant has expired and Microsoft still allows the permission, **Then** the channel can still send and receive as that mailbox without a new consent.
2. **Given** Microsoft has withdrawn the permission, **When** the platform next needs it, **Then** the channel is shown as needing to be connected again and mail is not sent as if it were still authorized.
3. **Given** an Outlook-connected email channel, **When** the admin removes it, **Then** the platform no longer uses that permission, and a later connect of the same mailbox requires a new consent.

---

### Edge Cases

- The admin's product login and the Microsoft account are different people. The channel address is the primary address confirmed before the redirect, and only when the Microsoft account is that same address. An address typed on the return is ignored.
- The same mailbox is already connected in another org. This org can still connect it with its own consent. Uniqueness is per org.
- Two admins of the same org start Connect Outlook at the same time for the same mailbox. Only one channel is created; the other attempt is told the mailbox is already connected.
- The admin who starts consent is no longer an admin of that org when Microsoft returns. No channel is created.
- A consent attempt that is not finished expires after 15 minutes. A later return does not create a channel.
- The existing generic email setup, where an admin types server details for a non-Outlook mailbox, is unchanged by every case above.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An org admin who can add channels MUST be able to start Connect Outlook from email channel setup.
- **FR-002**: Connect Outlook MUST ask for the primary mailbox address, then send that admin to Microsoft to sign in and approve access. This path MUST NOT ask for a mailbox password or for SMTP or IMAP host and port. A blank address, or one that is not an email address, MUST NOT start Microsoft sign-in. In this flow an alias means a confirmed address that is not the mailbox identity on the Microsoft account. That address MUST NOT be stored as the channel address. This flow does not look up aliases in a separate directory.
- **FR-003**: The approval MUST request only `offline_access`, `IMAP.AccessAsUser.All`, and `SMTP.Send`, for the mailbox the admin signed in with. It MUST NOT request any other permission, and it MUST NOT ask for access to every mailbox in the Microsoft organization.
- **FR-004**: The mailbox address on the new channel MUST be the primary address the admin confirmed before Microsoft, and it MUST be the same address the Microsoft account authorized. The product MUST NOT take that address from a value submitted on the return.
- **FR-005**: A successful consent MUST create exactly one email channel in the org that started it. The channel name and address MUST be that mailbox address.
- **FR-006**: After a successful consent, the org MUST be able to send mail as that mailbox and receive mail sent to it, without another consent for each message, for as long as Microsoft still allows the permission.
- **FR-007**: After success, the admin MUST see the connected mailbox address and MUST NOT see the secret grant.
- **FR-008**: If the admin denies consent, leaves before approving, Microsoft returns an error, the attempt is expired, the return does not match the attempt, or the Microsoft account is not the confirmed primary address, the product MUST NOT create a channel and MUST allow the admin to start again. A work account that requires an administrator to allow the app MUST be told so and MUST be offered Microsoft's admin-approval link. Any other Microsoft error MUST be shown as Microsoft described it.
- **FR-009**: A consent attempt MUST expire 15 minutes after it is started. An expired or unknown attempt MUST NOT create a channel.
- **FR-010**: If the org already has an email channel for that mailbox address, a later successful consent MUST NOT create a second channel and MUST tell the admin the mailbox is already connected.
- **FR-011**: If the Microsoft account has no mailbox address, or that address is not the confirmed primary address, the product MUST NOT create a channel and MUST tell the admin the account does not match.
- **FR-012**: The permission MUST remain usable after the short-lived grant expires, without a new consent, until the admin removes the channel or Microsoft withdraws the permission.
- **FR-013**: When Microsoft has withdrawn the permission, the channel MUST be shown as needing to be connected again, and mail MUST NOT be sent as if the channel were still authorized.
- **FR-014**: Removing the channel MUST stop the platform from using that permission. A later connection of the same mailbox MUST require a new consent.
- **FR-015**: Only an admin of the org who can add channels MUST be able to start or complete Connect Outlook. Completing consent MUST create a channel only in the org the attempt was started for.
- **FR-016**: The existing generic email setup, where an admin enters server details, MUST stay available and behave as it does today.
- **FR-017**: Outlook.com, Hotmail, and Live personal mailboxes, and Microsoft 365 work or school mailboxes, MUST be connectable through this flow.
- **FR-018**: User-facing text introduced by this flow MUST be available in the languages the product already supports.

### Key Entities

- **Consent attempt**: An in-progress Connect Outlook started by one admin for one org and one confirmed primary address. It expires after 15 minutes and can be completed only by that same admin for that same org.
- **Outlook email channel**: An email channel whose address is one Outlook mailbox and whose permission came from a completed consent, not from typed server settings.
- **Mailbox permission**: The Microsoft grant that lets the platform send and read mail for that one mailbox. It is stored for the channel and is never shown to the admin.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An admin who already has a Microsoft account can connect an Outlook mailbox and see the new email channel in under 3 minutes, without entering a password or mail-server settings.
- **SC-002**: 100% of successful consents produce exactly one email channel in the starting org, addressed to the mailbox Microsoft confirmed.
- **SC-003**: 100% of denied, cancelled, expired, mismatched, mailbox-less, or duplicate attempts leave the org with no new email channel.
- **SC-004**: A channel connected today can still send and receive as that mailbox 24 hours later without a new consent, while Microsoft still allows the permission.
- **SC-005**: In 100% of completed attempts, the admin never sees the secret grant on screen or in a confirmation message.
- **SC-006**: Admins who previously added a generic email channel by entering server details can still do so with the same outcome as before this change.

## Assumptions

- No product spec exists for this change. The problem and acceptance criteria in Origin Without Product Spec are the origin.
- The actor is an org admin who can already add channels. Agents and viewers cannot start or complete Connect Outlook.
- The admin confirms the primary mailbox address in the product before Microsoft. The Microsoft account must be that same address. An alias here is a confirmed address that differs from the mailbox identity on that account. A shared mailbox, a distribution list, or another user's mailbox is out of scope. There is no separate alias lookup.
- Consent is per mailbox. Approval for every mailbox in a Microsoft tenant is out of scope.
- Outlook.com personal accounts and Microsoft 365 work or school accounts are both in scope. Other providers, including Gmail, are out of scope. Their admins keep using the generic email setup.
- The result is an email channel of the kind the product already uses for email. This change does not add a new conversation screen, a new composer, or a new way for agents to reply.
- The only address step is the primary mailbox confirmed before Microsoft. After Microsoft returns, the channel is created when that address matches the account. There is no second confirmation step. Personal accounts approve during their own login. A work account whose organization has not allowed the app is sent to Microsoft's admin approval.
- The same mailbox may be connected in more than one org. Each org has its own consent. Inside one org, the mailbox address can belong to only one email channel.
- A consent attempt expires after 15 minutes, which matches the usual lifetime of a sign-in return that the product did not initiate itself.
- "Send and receive" means the existing email-channel behavior once the channel exists and is authorized. It does not mean a new mail product.
- Disconnecting Microsoft's app registration, tenant-wide admin consent, and moving existing manually created email channels onto this flow are out of scope.

## Peak Load

Connect Outlook is an admin onboarding action, not a per-message path. Declared peak is 50 concurrent consent attempts (start or return) across all orgs. Message traffic on the resulting email channel stays within the existing email-channel load and is not raised by this change.

## Test Strategy

Flow tests use `TembaTest`, following the existing email channel claim tests. They run in the `channels` CI group with `poetry run coverage run manage.py test`. Each acceptance criterion maps to a full path from the admin action to the resulting channel, not only to a single helper.

| Acceptance criterion | Test |
|---|---|
| AC-1 / FR-001, FR-002, FR-004, FR-005, FR-007, FR-017 / SC-001, SC-002, SC-005 | Admin starts Connect Outlook and the test returns an approved Microsoft consent for a work mailbox and for an Outlook.com mailbox. Each result is one email channel named and addressed as the confirmed mailbox. The response and the channel page do not contain the secret grant. The form path does not submit password or server fields. |
| FR-002 / FR-004 / FR-011 | The start form asks for the primary address and does not ask for a password or server fields. A blank address or one without `@` does not redirect. A token mailbox that differs from the confirmed address creates no channel. |
| FR-003 | The consent the admin is sent to approve lists only `offline_access`, `IMAP.AccessAsUser.All`, and `SMTP.Send`, in that order. |
| FR-008 | `access_denied` returns to the form. `consent_required` or `AADSTS65001` shows the admin-approval link. A mismatched attempt tells the admin to start again. Another Microsoft error is shown as Microsoft described it and is not written to the log. |
| FR-006, FR-012 / SC-004 | The Flows test asserts the new channel stores a refresh token. Sending, receiving, and renewal after the short-lived grant expires are the email-proxy contract, not a Flows test. |
| AC-2 / FR-008, FR-009, FR-011 / SC-003 | Denied, abandoned, Microsoft error, expired attempt, mismatched org or admin, and a consent with no mailbox address each leave the channel count unchanged and can be followed by a new attempt. |
| FR-010 | A second consent for an address that already has an email channel in that org does not add a channel. A concurrent pair of completions for the same new address creates one channel. |
| FR-015 | A non-admin cannot start or complete the flow. A return for org A started by an admin of org A does not create a channel in org B. An admin who lost access before the return does not create a channel. |
| AC-3 / FR-013, FR-014 | A channel with `oauth_status=needs_reconnect` shows that notice and does not show the grant. Stopping send and receive for that status is the email-proxy contract. Removing the channel clears both tokens, and a later connect requires a new consent. |
| AC-4 | Covered by the grant-not-shown assertion and the mismatched-return test above. |
| FR-016 / SC-006 | The existing generic email claim test still passes unchanged. |
| FR-018 | New user-facing strings exist in the locales the product already ships. |

Failure paths covered: deny, abandon, provider error, expiry, mismatched return, missing mailbox, duplicate address, lost admin rights, withdrawn permission, and removal. The success path is the approved consent that creates one channel.

## Constitution Alignment

- **I. Version Control and Review**: Delivered through a pull request. No branch was created by this specification step. Merge still requires review and a green `.github/workflows/ci.yml`.
- **II. Security and Secrets**: The mailbox permission is a channel credential and stays on the email channel configuration. It is not committed, not logged, and not shown to the admin. No new secret is introduced into source.
- **III. Observability**: Consent failures are visible to the admin on the claim page. Logs carry opaque org and user identifiers and Microsoft's error code only. They do not include the mailbox address, the grant, or Microsoft's error description.
- **IV. Versioned Contracts**: The generic email claim contract stays as it is. The Outlook path adds a way to create the same email channel type. Any change to the channel configuration consumed by Courier is backward compatible and will be called out in the plan, including the Courier version if one is required.
- **V. Specification Traceability**: No product spec. Origin, problem, and acceptance criteria are in Origin Without Product Spec. AC-1 through AC-4 map to the Test Strategy rows above.
- **VI. No Silent Divergence**: Not applicable. There is no product spec to diverge from.
- **VII. Commit Messages**: Conventional Commits, atomic, when implementation commits are requested.
- **VIII. Changelog Maintenance**: A user-facing `feat:` bullet in `WENI-CHANGELOG.md` under the version that ships this, before release.
- **IX. Never Trust the Client**: The primary address is stored on the server when the attempt starts. The return cannot replace it. A channel is created only when the Microsoft account matches that stored address. Authorization is checked on the server for start, return, and removal.
- **X. Fail Gracefully and Predictably**: Microsoft being unavailable, denying consent, or returning an error does not create a channel and does not show an internal error. Calls to Microsoft have an explicit timeout.
- **XI. Bounded Retry Over REST**: Renewal of the mailbox permission is retried only for a transient failure, with a maximum number of attempts and a backoff. A permanent refusal is not retried; the channel is marked as needing reconnect. The plan will name the limits.
- **XII. Scalability and Peak Load**: The consent flow keeps no durable state in the web process. Peak is declared above.
- **XIII. Diagnosable Errors**: The application log for a failed consent has the opaque org id, user id, and Microsoft's `error` code. A Sentry event for that failure also has the opaque account id and the correlation id already present on the request. Neither includes the mailbox address, the grant, or `error_description`.
- **XIV. Tests Exercise Flows**: The Test Strategy covers the consent path from the admin action to the channel that exists or does not exist, including failure paths. Tests use `TembaTest` beside the email channel tests.
- **XV. Explicit Over Clever**: The 15-minute attempt lifetime and any retry limit are named constants. The plan will name them.
- **XVI. Contained Changes**: Outlook consent and the email channel it creates. The generic email claim, other channel types, and the conversation UI stay as they are.
- **Cycle choice**: SDD Full. This change alters how an email channel is created and how its credentials are obtained, which is a channel-type change under Specification-Driven Delivery. `/speckit-plan` is the next step. This specification does not include implementation notes in place of a plan.
