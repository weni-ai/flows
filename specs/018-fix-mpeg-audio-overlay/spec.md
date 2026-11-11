# Engineering Specification: MPEG audio opens in the on-page player

**Repository**: weni-ai/flows — backend

**Feature Branch**: `018-fix-mpeg-audio-overlay`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "In Studio, an MPEG audio attachment (audio/mpeg) from flow Preview opens in the browser's full-page player. OGG opens in an overlay with a close control. MPEG must behave like that OGG."

**Suggested cycle**: SDD Lite. The change classifies MPEG audio, and generic files whose path ends in `.mp3` or `.mpeg`, as playable audio on the attachment control Studio already renders. Related tests and a user-facing changelog bullet ship with it. No migration, no new public interface, no Courier or Mailroom coordination, and no new channel type.

## Origin Without Product Spec

- Product Spec: none
- Problem: In Studio contact history, an MPEG audio attachment sent by flow Preview (content type `audio/mpeg`) leaves the page and plays in the browser's full-page player, which has no close control. An OGG attachment sent by an attendant opens in a window over the page, with a close control. MPEG must behave like that OGG.
- Acceptance criteria:
  - AC-1: An attachment `audio/mpeg:<url>` in contact history opens in the same overlay player as `audio/ogg`, with a close control, and does not navigate the Studio page to the file URL.
  - AC-2: `audio/ogg`, `audio/mp3`, and the other types already treated as playable keep the overlay player.
  - AC-3: `application/octet-stream` whose path ends in `.mp3` or `.mpeg` (including a query string) is treated as playable audio, the same way `.ogg` and `.oga` already are.
  - AC-4: Images, video, geo, and non-audio documents are unchanged, including external links opening in a new tab.
  - AC-5: No migration, no API change, no Courier or Mailroom change, no rewrite of stored messages.
  - AC-6: A regression test renders the attachment control (and the contact history path, because neighboring tests assert the player markup that way) for `audio/mpeg` and for octet-stream `.mp3`, and asserts the overlay audio markup rather than a navigation link. Existing `audio/mp3` and `audio/ogg` cases still pass. The repository's usual test, style, and CI gates stay green. No new coverage exclusion.
  - AC-7: User-facing fix, so the product changelog gains a `fix:` bullet under the next unreleased version heading. The upstream changelog is not rewritten. No new locale strings.

## Scope in This Repository

**This repository implements**:

- Treating `audio/mpeg` as playable audio so the existing on-page player is used.
- Treating `application/octet-stream` whose path ends in `.mp3` or `.mpeg` as playable audio, including when the address has a query string, parallel to the existing `.ogg` / `.oga` rule.
- Applying that classification in the shared attachment control, so contact history and the message lists that use the same control stay consistent.
- Regression coverage for the overlay markup on `audio/mpeg` and on octet-stream `.mp3`.
- A `fix:` bullet in `WENI-CHANGELOG.md` under the next unreleased version heading.

**Out of scope here**:

- Transcoding audio.
- Changing the content type stored when Preview uploads a file, including the existing m4a-to-`audio/mp4` rewrite.
- Replacing or restyling the overlay player, including video.js and Featherlight itself.
- Any flow-editor repository.
- A special case that applies only to contact history.
- Rewriting stored messages, a data migration, a public API change, or a Courier or Mailroom release.

## Current State

- Contact history renders each attachment with `{% attachment_button %}` in `templates/contacts/contact_history.haml` (broadcast events and message events).
- The same tag is used by `templates/msgs/message_box.haml`, `templates/msgs/msg_outbox.haml`, and `templates/msgs/msg_outbox_spa.haml`.
- `attachment_button` in `temba/msgs/templatetags/sms.py` sets `is_playable` only when the content type is in `PLAYABLE_CONTENT_TYPES`. That set includes `audio/ogg` and `audio/mp3` and does not include `audio/mpeg`. It also includes the video types that already use the video overlay.
- `templates/msgs/tags/attachment.haml` opens Featherlight (overlay, `<audio>` about 360px wide, close icon) only when `category` is `audio` and `is_playable`. Otherwise an internal URL calls `goto()`, which sets `document.location.href`, and the browser shows its native full-page player. External non-playable documents open in a new tab.
- Preview upload (`FlowCRUDL.UploadMediaAction.save_media_upload` in `temba/flows/views.py`) stores the browser content type. Browsers send `audio/mpeg` for MP3. The only rewrite there is m4a to `audio/mp4`.
- `application/octet-stream` plus a `.ogg` or `.oga` path is already rewritten to `audio/ogg` in `attachment_button`, including when the address has a query string (`urlparse(url).path`). There is no equivalent for `.mp3` or `.mpeg`.
- `temba/msgs/templatetags/tests.py` asserts the `.ogg` / `.oga` rewrite and renders the tag for images and external documents. `temba/contacts/tests.py` `test_history` asserts overlay markup for `audio/mp3` and `video/mp4` (`<audio`, `<source type="audio/mp3"`, `<video`).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - MPEG audio stays on the contact page (Priority: P1)

An operator reviewing a contact in Studio sees an MPEG audio attachment that flow Preview sent. They play it, then close it and continue reading the history on the same page.

**Why this priority**: This is the defect. The full-page player hides Studio and has no close control, so the operator loses their place.

**Independent Test**: Open contact history that contains an `audio/mpeg` attachment and activate it. The audio plays over the page, a close control is available, and the contact history address stays in place.

**Acceptance Scenarios**:

1. **Given** contact history contains an attachment `audio/mpeg:<url>`, **When** the operator activates that attachment, **Then** an overlay audio player opens over the page with a close control, and the Studio page does not navigate to the file URL.
2. **Given** the overlay player is open, **When** the operator uses the close control, **Then** the player closes and the contact history is still the page on screen.
3. **Given** the same kind of attachment appears in a message list that uses the shared attachment control, **When** the operator activates it, **Then** it opens in that same overlay player.

---

### User Story 2 - Mislabeled MP3 files use the overlay (Priority: P1)

Some audio files are stored as a generic binary type even though the address ends in `.mp3` or `.mpeg`. Operators need those files to play over the page, the way generic files ending in `.ogg` or `.oga` already do.

**Why this priority**: A generic type with an MP3 path is the same full-page player today. Fixing only the `audio/mpeg` label would leave those attachments broken.

**Independent Test**: Render an `application/octet-stream` attachment whose path ends in `.mp3`, and another whose path ends in `.mpeg` and includes a query string. Both present the overlay audio player.

**Acceptance Scenarios**:

1. **Given** an attachment `application/octet-stream:<url ending in .mp3>`, **When** it is shown and activated, **Then** it opens in the same overlay audio player as OGG.
2. **Given** an attachment `application/octet-stream:<url ending in .mpeg?query>`, **When** it is shown and activated, **Then** it opens in that same overlay audio player.

---

### User Story 3 - Other attachments keep their current open behavior (Priority: P1)

Operators already rely on OGG and MP3 audio opening over the page, on video opening in its player, and on images, locations, and documents opening as they do today. This correction must leave those paths alone.

**Why this priority**: The shared control also serves images, video, locations, and documents. A classification change that is too wide would move those files into the wrong player or the wrong tab.

**Independent Test**: Render `audio/ogg`, `audio/mp3`, an image, a video, a geo attachment, and an external document. Each keeps the open behavior it has today.

**Acceptance Scenarios**:

1. **Given** an `audio/ogg` or `audio/mp3` attachment, **When** the operator activates it, **Then** it still opens in the overlay player.
2. **Given** a video attachment that already opens in the on-page video player, **When** the operator activates it, **Then** it still opens in that video player.
3. **Given** an image, a geographic location, or a non-audio document, **When** the operator activates it, **Then** it opens as it does today, and an external document still opens in a new tab.

---

### Edge Cases

- A query string on `.mp3` or `.mpeg` does not block playable treatment. The path suffix is what matters, using the same path rule as `.ogg` and `.oga`.
- An `audio/mpeg` address that itself has a query string still uses the overlay player.
- The separate download control beside a playable attachment keeps its current action. The control that must stay on the page is the preview that opens the player.
- Suffix matching stays consistent with `.ogg` and `.oga`: a lowercase path suffix. This change does not add a new case-insensitive rule.
- An attachment already stored as `audio/mp3` stays playable and is not relabeled.
- `audio/mpeg` that is already stored stays `audio/mpeg` when displayed. Display classification does not rewrite the stored message.
- Geographic attachments still open the map. They do not gain an audio player.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: An attachment whose content type is `audio/mpeg` MUST open in an overlay audio player on the current Studio page, with a close control, and MUST leave the page address unchanged.
- **FR-002**: Attachments whose content types already open in an overlay player MUST keep that player, including `audio/ogg`, `audio/mp3`, and the other types already treated as playable. Video types that already use the video player MUST keep the video player.
- **FR-003**: An attachment whose content type is `application/octet-stream` and whose address path ends in `.mp3` or `.mpeg` MUST be treated as playable audio and MUST open in the same overlay audio player as OGG, including when the address has a query string.
- **FR-004**: Images, video, geographic locations, and non-audio documents MUST keep their current open behavior. External documents MUST still open in a new tab.
- **FR-005**: Stored messages MUST keep the content type they already have. Upload-time content types MUST stay as they are. Public interfaces and Courier and Mailroom releases MUST stay unchanged. No data migration is required.
- **FR-006**: The playable-audio rule MUST apply on every Studio surface that shows the shared attachment control, including contact history and message lists. Contact history MUST stay on that shared rule.
- **FR-007**: The next unreleased version notes MUST record this fix. No new interface text is introduced for translation.

### Key Entities

- **Attachment**: A file on a message, identified by a content type and an address, shown as a control the operator can activate.
- **Contact history**: The Studio timeline for one contact, including messages sent by flow Preview and by attendants.
- **Overlay audio player**: The on-page player already used for OGG, with a close control, which leaves the Studio page in place.
- **Message list**: The other Studio surfaces that show the same attachment control as contact history.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In contact history checks, 100% of `audio/mpeg` attachments open in an overlay player with a close control, and 0% of those activations navigate the Studio page to the file URL.
- **SC-002**: 100% of attachments that already open in an overlay player, including `audio/ogg` and `audio/mp3`, still do so in the same checks.
- **SC-003**: 100% of `application/octet-stream` attachments whose path ends in `.mp3` or `.mpeg`, with or without a query string, open in the same overlay audio player as OGG.
- **SC-004**: Across the checked image, video, location, and non-audio document cases, open behavior is unchanged, including external links that open in a new tab.
- **SC-005**: The next version's release notes include this correction, and the change introduces zero new strings to translate.

## Assumptions

- Flow Preview continues to store the browser content type. Browsers send `audio/mpeg` for MP3. This fix classifies that type when the attachment is shown.
- The overlay player and its close control already exist for OGG. MPEG becomes eligible for that player. No new wording is added to the interface.
- Suffix matching follows the rule already used for `.ogg` and `.oga`: lowercase suffix on the URL path, query string ignored. Uppercase suffixes are outside this cut.
- Message lists use the same attachment control as contact history, so they follow the same classification with no contact-history-only branch.
- Video files, including any type already treated as playable video, keep the video player.
- **Peak load (Principle XII)**: unchanged. Declared peak is the current peak of contact-history page views for the busiest workspace, not an average and not a new traffic class. The change only reclassifies an attachment control on a request that already renders that page. It adds no endpoint, worker, or stored state, and it adds no extra request at that peak.

## Test Strategy

| Acceptance criterion | How this repository proves it |
|----------------------|-------------------------------|
| AC-1 `audio/mpeg` overlay, page stays put | `temba/msgs/templatetags/tests.py`: render `{% attachment_button %}` for `audio/mpeg:<external url>`. Assert Featherlight audio markup (`data-featherlight`, `<audio`, `<source type="audio/mpeg"`), preview `href="#"`, and no `goto(` on that preview. `temba/contacts/tests.py` `test_history` (or a focused sibling in that class): a contact-history response for an `audio/mpeg` attachment contains `<audio` and `<source type="audio/mpeg"`. Assert the player fragment, not that the whole page lacks `goto(`, because geo pins still use `goto(`. |
| AC-2 existing playable types | Existing `test_history` assertion for `audio/mp3` (`<audio`, `<source type="audio/mp3"`) and for `video/mp4` stays green. Existing octet-stream `.ogg` / `.oga` cases in `test_attachment_button` stay `is_playable` true with content type `audio/ogg`. |
| AC-3 octet-stream `.mp3` / `.mpeg` | Same tag tests: `application/octet-stream` with path `.mp3`, and with path `.mpeg` plus a query string. Assert content type `audio/mp3`, category audio, `is_playable` true, and rendered overlay `<audio` markup (`<source type="audio/mp3"`) rather than a `goto(` preview. Path rule matches `urlparse(url).path` used for `.ogg` / `.oga`. |
| AC-4 images, video, geo, documents | Existing tag cases for image, geo, and external PDF/image (`test_attachment_button`, `test_attachment_button_external_urls_open_in_new_tab`) stay green, including `target="_blank"` and no `goto(` for external documents. Existing `test_history` video and OpenStreetMap geo assertions stay green. |
| AC-5 no migration, no API, no stored rewrite | The `audio/mpeg` render asserts the player source type is still `audio/mpeg`. No migration file, no edit under the public API, Courier, or Mailroom, and no change to `FlowCRUDL.UploadMediaAction.save_media_upload`. |
| AC-6 regression plus existing cases | The renders above are the regression. Existing `audio/mp3` and `audio/ogg` cases still pass. Gates: `poetry run coverage run manage.py test` for the touched modules (`temba.msgs.templatetags` and `temba.contacts` if history is extended), clean `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`. |
| AC-7 changelog, no new strings | Pull request adds a `fix:` bullet under the next unreleased heading in `WENI-CHANGELOG.md`. `CHANGELOG.md` and `locale/` are untouched. |

**Flow coverage** (Principle XIV): one test loads contact history the way an operator does, with a stored `audio/mpeg` attachment, and asserts the overlay audio markup in the response. That is the complete use case. Isolated renders of `attachment_button` cover the octet-stream `.mp3` / `.mpeg` variants and the external-URL preview.

**Failure paths**: there is no new error response. The paths that must stay non-playable are the existing image, geo, and document cases above. A suffix that does not match `.mp3` or `.mpeg` stays on today's generic-file behavior.

**Gates**: `poetry run coverage run manage.py test` for the touched modules, clean `./code_check.py`, green `.github/workflows/ci.yml`. No new `# pragma: no cover`.

## Rollout and Rollback

1. Deploy Flows with the classification change. No migration and no Courier or Mailroom deploy.
2. In Studio, open a contact whose history has an `audio/mpeg` attachment from Preview. Activate it and confirm the overlay player and its close control, with the contact page still in place.
3. Confirm an OGG attachment still uses that overlay, and that an external document still opens in a new tab.
4. **Rollback:** revert the classification change. `audio/mpeg` again uses the browser's full-page player. Stored messages are untouched either way.

## Constitution Alignment

| Principle | How this spec complies | Exception + justification |
|-----------|------------------------|---------------------------|
| I. Version Control and Review | Delivered through a PR to `main` with review and green `ci.yml`. | none |
| II. Security and Secrets | No new secret, dependency, or credential. Attachment URLs stay on the existing presign path. | none |
| III. Observability | No new log line. Existing request logs for the contact-history page remain the trace. | none |
| IV. Versioned Contracts | No public API, channel config, event payload, or migration. Flows API SemVer is unaffected. | none |
| V. Specification Traceability | Opens with `## Origin Without Product Spec`. Each acceptance criterion maps to a check in Test Strategy. | none |
| VI. No Silent Divergence | Not applicable: no Product Spec. | none |
| VII. Commit Messages | Atomic Conventional Commits, ≤50 character descriptions. | none |
| VIII. Changelog Maintenance | `fix:` bullet in `WENI-CHANGELOG.md` under the next unreleased version heading. `CHANGELOG.md` is not rewritten. | none |
| IX. Never Trust the Client | No new input boundary. Classification runs on the stored attachment string, using the same path parse as the existing OGG rewrite. Upload-time content type is left as stored. | none |
| X. Fail Gracefully | No new outbound call. Timeouts and error responses are unchanged. | none |
| XI. Bounded Retry Over REST | No new REST propagation. | none |
| XII. Scalability and Peak Load | Stateless render. Declared peak is the current peak of contact-history page views for the busiest workspace. No new endpoint, worker, stored state, or extra request at that peak. | none |
| XIII. Diagnosable Errors | No new Sentry event. Identifiers on the existing page stay as they are. | Platform `send_default_pii=True` remains `TODO(SENTRY_PII)`. |
| XIV. Tests Exercise Flows | Contact-history GET asserts overlay markup for `audio/mpeg`, plus tag renders for octet-stream `.mp3` / `.mpeg`. `TembaTest`. | none |
| XV. Explicit Over Clever | `audio/mpeg` is added to the existing `PLAYABLE_CONTENT_TYPES` set. `.mp3` and `.mpeg` join the existing suffix check that rewrites `application/octet-stream`, with a comment that Preview stores the browser type `audio/mpeg` and the upload path is intentionally unchanged. | none |
| XVI. Contained Changes | Shared `attachment_button` classification, its template outcome, tests, and the changelog bullet. No contact-history-only branch. `save_media_upload` stays as it is. | none |
| XVII. Explicit, Scoped Authorization | No new or changed endpoint. Contact history keeps its current page authorization. | none |
| Backend Standards | `code_check.py`. No new user-facing locale string. | none |

## Implementation Decisions

- SDD Lite: one classification change in the shared attachment control, no migration, no Courier or Mailroom.
- `audio/mpeg` is playable audio. Stored `audio/mpeg` is shown as `audio/mpeg` and is not rewritten.
- `application/octet-stream` whose path ends in `.mp3` or `.mpeg` is rewritten to `audio/mp3` before the playable check, parallel to `.ogg` / `.oga` becoming `audio/ogg`. `audio/mp3` is the playable MP3 type this product already uses. Both suffixes share that one type.
- The upload path in `save_media_upload` is not modified. Its m4a-to-`audio/mp4` rewrite stays the only rewrite there.
- Featherlight and the audio element markup stay as they are. Eligibility is the only change, so the close control OGG already has is the close control MPEG gets.

## Open Questions

None. Display-time classification is the cut. Upload-time content type stays as the browser sent it.
