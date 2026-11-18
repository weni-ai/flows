# Research: Consume project events from AmazonMQ

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Date**: 2026-11-17

The spec has no `NEEDS CLARIFICATION` marker. The decisions below cover the points the spec leaves open: where validation lives, how the setting fails start-up, and how logs and Sentry stay free of the e-mail. They also cover facts found in the code that change the design: the logging config, the Sentry config, and how `weni-eda` signals interact with `TembaTest`.

## R1. Payload validation: explicit validators, not DRF serializers

- **Decision**: One frozen dataclass per event type (`ProjectUpdatedData`, `ProjectStatusUpdatedData`, `ProjectTypeUpdatedData`, `ProjectDeletedData`) in a new module `temba/projects/consumers/project_event_payloads.py`. Each has a `from_data(data: dict)` constructor that checks every field and raises `InvalidProjectEvent(ValueError)`. The exception message names the field and the rule, never the received value.
- **Rationale**: AC-3 requires strict types. DRF `BooleanField` accepts `"true"`, `1` and `"yes"`, and `CharField` turns numbers into strings, so a serializer would have to override both to stay strict. The legacy consumer already validates by hand (`_validate_message`), so explicit validators stay close to the code that is already there (Principle XV). Leaving values out of the message keeps the e-mail out of Sentry and logs by construction.
- **Rules** (from FR-002):
  - `data` must be a `dict`.
  - `data.uuid` must be a `str` that `uuid.UUID()` accepts. It is normalized to the canonical string.
  - `data.user_email` must be a non-empty `str` after `strip()`. Its format is not checked, which matches the legacy consumer.
  - `data.status` must be a `str` that is one of `ProjectStatus`.
  - `data.is_multi_agents` must satisfy `isinstance(value, bool)`, so `0`, `1` and `"true"` are rejected.
  - `data.timezone` may be absent or `null`. Otherwise it must be a `str` that `pytz.timezone()` accepts. This is the same call `update_project_config` makes, so the validator and the use case cannot disagree.
  - `data.name`, `data.description` and `data.language` may be absent, `null`, or a `str`. An empty string is allowed, as in the legacy path.
- **Envelope** (FR-012): `Message.event()` is `Event(**json)` and checks no types, so `event_id` could be a number, an object, or a string with spaces and line breaks. These values go into `key=value` log lines, Sentry tags and the rejection message, where `"x project_uuid=…"` would forge a field for Loki's `logfmt` parser. `ProjectEventEnvelope.from_event(event)`, in the same module, runs for every event type right after parsing and before anything is logged:
  - `event_id` and `event_type` must be a `str` that `ENVELOPE_TOKEN_PATTERN.fullmatch` accepts (`[A-Za-z0-9._:-]{1,64}`).
  - `producer` must be `None` or a `str` that the same pattern accepts.
  - `timestamp` is not used, so it is not checked. `data` is checked by the per-type dataclasses.
  - The publishers already comply: Connect builds the envelope with `Event.build`, so `event_id` is a `uuid4` string and `producer` is `settings.EDA_PRODUCER` (`weni-engine` by default). Validating `project.created` envelopes too is the one change on that path (FR-010).
- **Legacy `project_uuid`**: the legacy consumer does not validate `project_uuid`, and changing that would change its outcome for listed actions (FR-005). `canonical_uuid(value)` returns the canonical string when `value` is a `str` that `uuid.UUID()` accepts, and `None` otherwise. The legacy context stores that result, so logs, tags and the rejection message only ever carry a canonical UUID or `None`.
- **Alternatives considered**: DRF serializers with custom strict fields (more code to make them strict); pydantic (not a dependency of the Django app, and its default coercion has the same problem); reusing `_validate_message` (it covers the flat legacy body, not the envelope, and it coerces `is_multi_agents`).

## R2. Shared module for what outlives the legacy consumer

- **Decision**: New module `temba/projects/consumers/project_events.py` holding `EventAction` and `ProjectStatus`, moved from `project_event_consumer.py`, plus the shared helpers: `is_legacy_action`, `ProjectEventContext`, `ProjectEventRejected`, `report_exception`, `find_org_id`, `find_user_id`, `canonical_uuid` and `scrub_sentry_event`. `project_event_consumer.py` imports the two enums from the new module. `ProjectEventType` stays in `project_consumer.py` and gains the four new constants, together with `LEGACY_ACTION_BY_EVENT_TYPE`.
- **Rationale**: `ProjectConsumer` needs `ProjectStatus` and the legacy action names. Importing them from `project_event_consumer.py` would tie the new consumer to a module that step 5 of Rollout deletes. Only `project_event_consumer.py` imports the enums today, so the move touches one import (Principle XVI).
- **Alternatives considered**: Import from `project_event_consumer.py` (it breaks when the legacy consumer is removed). Duplicate the enums (two sources of truth).

## R3. `PROJECT_EVENTS_LEGACY_ACTIONS`: parsed in settings, validated by a system check

- **Decision**:
  - `temba/settings_common.py` reads the variable outside `if USE_EDA:`, so tests and every settings variant see it. It splits on `,`, strips each item, and drops empty items. An empty string therefore becomes `[]`, and an unset variable becomes the four actions.
  - `temba/projects/checks.py` registers a system check, `projects.E001`, that returns an `Error` for any item not in `EventAction`. It is imported from `temba/projects/__init__.py`, the same way `temba/assets/__init__.py` imports `temba/assets/checks.py`.
- **Rationale**: `settings_common.py` imports nothing from `temba`, so it cannot import `EventAction`, and duplicating the list there just to validate it would create a second source of truth. `edaconsume` is a Django `BaseCommand` that does not override `requires_system_checks`, so Django runs the checks before it consumes anything, and both `edaconsume` and `edaconsume-amq` refuse to start with an unknown value. `migrate` and `check` also fail with it, which catches a typo at deploy time. The check is a plain function that can be tested with `override_settings`, which import-time code in `settings_common.py` cannot.
- **Duplication guard**: the default literal in `settings_common.py` repeats the four values. A test asserts that the default equals `[a.value for a in EventAction]`.
- **Alternatives considered**: Raise `ImproperlyConfigured` in `settings_common.py` (cannot use `EventAction`, and it is hard to test). Validate when the consumer is constructed (the processes would start, and the failure would only show on the first message).

## R4. Reading the setting

- **Decision**: `is_legacy_action(action)` reads `django.conf.settings.PROJECT_EVENTS_LEGACY_ACTIONS` on every call.
- **Rationale**: `override_settings` works in tests without reloading modules. Production settings do not change at runtime, so the spec's restart requirement is unchanged.

## R5. Order of operations in `ProjectConsumer`

- **Decision**: For each message: parse and validate the envelope (R1), then route by `event_type`. For the four new types: validate the payload (R1), then check the legacy list (skip and ack), then look up the org (missing org: warn and ack), then look up `user_id` (R6), then call the use case, then ack. `project.created` and unknown types keep their current paths.
- **Rationale**: FR-004 requires validation before the skip check. Looking up the org after the skip check avoids a query for events that are only acknowledged.

## R6. Missing org, `org_id` and `user_id` for Sentry

- **Decision**:
  - `ProjectConsumer` calls `find_org_id(project_uuid)`, which runs `Org.objects.filter(proj_uuid=...).values_list("id", flat=True).first()`, before it calls the use case. `None` means log `project_event_org_not_found` at `warning` and ack (FR-008). The id goes into the context for the Sentry tag.
  - `ProjectEventConsumer` keeps its current missing-org behaviour (`updated` rejects, the other actions ack). It calls `find_org_id` only in its `except` block, to fill the tag. There, `context.project_uuid` is already `canonical_uuid(...)`, so it is `None` for a value that is not a UUID and `find_org_id(None)` returns `None`.
  - `find_user_id(email)` runs `User.objects.filter(email=email).values_list("id", flat=True).first()` and returns `None` for anything that is not a non-empty `str`. It is the same query the use cases' `get_or_create_user_by_email` starts with, but it never creates a user. Both consumers call it right before the use case (after the skip check and, for AmazonMQ, after the org lookup) and store the id in the context for the `user_id` tag. Principle XIII asks for a user identifier, and `User.id` is opaque.
  - There is no account identifier: the events carry none, and Flows has no local mapping from a project to its Connect account. That tag stays absent, as recorded in the spec.
- **Rationale**: This treats all four new events the same way without changing `update_project_config`, which the legacy consumer still relies on to raise `Org.DoesNotExist`. Catching `Org.DoesNotExist` around the use case would also swallow a `DoesNotExist` raised for another reason.
- **Cost**: `Org.proj_uuid` has no index (`models.UUIDField(null=True, blank=True)`), so the lookup is a sequential scan of `orgs_org`. The use cases already do the same scan. At the declared peak of 4 messages/min, a second scan per message is negligible, including a burst of `project.deleted`. Adding an index needs a migration and is out of scope (Principle XVI). It is recorded as a follow-up. `auth_user.email` has no index either; `find_user_id` adds one scan of `auth_user` per applied event, next to the one the use case already does, which is also negligible at 4 messages/min. Events that are skipped or fail validation do not run it.

## R7. Idempotent deletion

- **Decision**: In `delete_project`, after the org is loaded and before `get_or_create_user_by_email`, check `if not org.is_active:`. In that case log `project_already_released project_uuid=<uuid> org_id=<id>` at `info` and return the org.
- **Rationale**: FR-007. Checking before user resolution means a repeated deletion does not create a `User` either. This guard also changes the legacy path, which is in scope because the spec makes it so.
- **Atomic release**: `Org.release` saves `is_active=False` first and only then releases each channel. `Channel.release` can still raise: it re-raises `TwilioRestException`, and it does further database and Redis work. Without a transaction, a failure part way through leaves an org that is inactive but still has active channels. The guard would then skip the redelivered message, so those channels would never be released. `delete_project` therefore runs `org.release(user)` inside `transaction.atomic()`. If it fails, the org stays active and a replay from the dead-letter queue retries the whole release. External calls already made (a channel type's `deactivate`, `mailroom.queue_interrupt`) are not rolled back, just as with a retry today.
- **Accepted risk**: The transaction, with row locks on the org and its channels, stays open during those calls. A slow channel provider API delays the commit of that one deletion and holds those locks meanwhile. This change adds none of these calls, and their timeouts are existing behaviour in each channel type, out of scope here (Principle XVI). At the declared peak (4 messages/min, plus bursts of `project.deleted` that each lock a different org) the risk is accepted in exchange for an atomic release. Releasing channels outside the transaction was rejected because it brings back the inactive-org-with-active-channels state described above.
- **Test impact**: `test_delete_already_deleted_project` documents the old behaviour ("should still work"). It is rewritten to assert that `released_on` and `modified_by` are unchanged after the second call.

## R8. Log format and log visibility

- **Facts found**:
  - Both `settings_common.py` and `settings.py.prod` (the file production runs, linked in `docker/Dockerfile`) format records as `%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s`. Fields passed through `extra=` are never printed.
  - In both, the root logger is at `WARNING` and no `temba.projects` logger is configured, so the `info` lines of the project use cases are dropped today.
- **Decision**:
  - Structured fields go into the message as stable `key=value` pairs after a fixed event name, using `%s` arguments. Example: `project_event_consumed event_id=%s event_type=%s project_uuid=%s producer=%s`. Grafana Loki's `logfmt` parser extracts these pairs, and the bare tokens before them are ignored.
  - A `"temba.projects"` logger at `INFO`, with the `console` handler and `propagate: False`, is added to `LOGGING` in both settings files. `settings_common.py` already does this for `temba.conversion_events`.
  - Event names: `project_event_consumed`, `project_event_skipped`, `project_event_org_not_found`, `project_already_released`. Rejections are logged by `weni-eda` (R9).
  - In `delete_project`, `update_project_status` and `update_project_type`, the lines that contain `by {user_email}` are rewritten without the e-mail and without `org.name`, keeping `project_uuid` and adding `org_id`. The spec's Observability section also forbids the project name. The "not found" warnings already carry only `project_uuid`, so they stay as they are.
- **Volume**: The new logger covers about 22 messages/min at peak across both queues (18 creations and 4 changes), with a few lines each.
- **Alternatives considered**: A JSON formatter (it changes every log line in the service, which is out of scope). `extra=` only (the fields would be invisible with the current formatter).

## R9. Keeping the e-mail out of Sentry

- **Facts found**:
  - Production initializes Sentry in `settings.py.prod` with only `DjangoIntegration` and the default options. `include_local_variables` is `True` (sentry-sdk 1.45.1), so every stack frame's local variables are sent. The use case frames hold `user_email`, and the consumer frames hold the payload. The default `EventScrubber` denylist has no `email` entry.
  - `EDAConsumer.handle` logs `"[%s] Message rejected: %s"` at `ERROR` with `exc_info=True`. The default `LoggingIntegration` turns that into a second Sentry event, with the same frames, outside any scope the consumer controls.
  - `sentry_sdk.utils.walk_exception_chain` stops at an exception raised `from None`. `amqp.Message` has no custom `__repr__`, so it serializes as an opaque object reference.
- **Decision**:
  - `consume` in both consumers becomes a thin wrapper. It creates a `ProjectEventContext`, calls a private `_process(message, context)`, and in `except Exception as exception` calls `report_exception(exception, context)` and then `raise ProjectEventRejected(context, exception) from None`.
  - `report_exception` runs `capture_exception` inside `sentry_sdk.push_scope()`, the pattern already used in `temba/channels/types/email/outlook.py`. It sets the tags `project_uuid`, `event_id`, `event_type` or `action`, `org_id` and `user_id` (each only when known), and adds the event processor `scrub_sentry_event`. That processor deletes `vars` from every stack frame and replaces e-mail-shaped substrings in exception values with `[email]`. The substitution is needed because a database error such as a unique violation on `auth_user.username` can carry the address in its message.
  - The message of `ProjectEventRejected` is `project event rejected: event_id=… event_type=… project_uuid=… reason=…`. `reason` is the `InvalidProjectEvent` message for validation failures and only the exception class name for anything else.
  - The traceback of `ProjectEventRejected` contains only the `consume` frame (locals: `self`, `message`, `context`) and the `handle` frame. Python deletes `exception` when the `except` block unwinds. As a result, the `weni-eda` error log and the Sentry event made from it carry no payload, and `EDAConsumer` still rejects without requeue.
- **Spec impact**: The spec says failures are "reported to Sentry and re-raised". With this decision the reported exception is the original one, and the re-raised exception is a sanitized one that carries its identifiers and reason. The rejection behaviour is the same. This is an implementation decision, not a divergence, because there is no product spec.
- **Scope**: `send_default_pii=True` in `settings_common.py` and the global Sentry options remain the constitution's TODO(SENTRY_PII). This change touches only the project event path.
- **Alternatives considered**: `include_local_variables=False` or a global `before_send` (changes every Sentry event in the service, out of scope); `ignore_logger` for the `weni-eda` logger (hides rejections from every consumer); re-raising the original exception (leaks the e-mail through the rejection log).

## R10. Testing through `handle()` in `TembaTest`

- **Facts found**: `weni-eda` connects `close_old_connections` to `message_started` and `message_finished`. Inside a `TestCase` transaction, autocommit is off and differs from the settings value, so `close_if_unusable_or_obsolete` closes the connection and marks the test transaction for rollback. That is why the existing tests call `consume` directly. `temba/msgs/usecases/tests/test_managed_trigger_group.py` works around the same problem by patching.
- **Decision**: A test helper patches `weni.eda.django.consumers.consumer.message_started` and `weni.eda.django.consumers.consumer.message_finished`, the module globals that `handle` uses. It then calls `consumer.handle(Mock(body=..., delivery_tag=..., channel=channel))` and asserts `channel.basic_ack` or `channel.basic_reject(tag, requeue=False)`. Use cases run against the test database. `capture_exception` and `push_scope` are patched only where the test asserts on them.
- **Rationale**: This exercises the real ack and reject path (Principle XIV, RG-1) without disconnecting global signal receivers.

## R11. Contract versioning, Courier and Mailroom

- **Decision**: The consumed contract is additive. Four routing keys start being handled on a queue that already acks unknown types, and the legacy contract is unchanged apart from the documented skip. No Courier or Mailroom version is required. `WENI-CHANGELOG.md` gets the bullets under a new topmost heading for the next minor version, because the change includes a `feat:` bullet. The current top heading, `3.112.1`, has already shipped, and staging tags already reach `3.113.0-a2`, so the release owner confirms the number when the PR is opened.

## R12. Infrastructure prerequisites (outside this repository)

- **Decision**: Recorded as rollout gates, not tasks: the four bindings and a dead-letter exchange on `flows.projects.queue`. `edaconsume-amq` connects with `AMQConnectionParamsFactory`, which forces TLS, so end-to-end validation against a broker happens on staging, not against a local RabbitMQ without TLS. Tests cover the behaviour locally.

## Follow-ups (not in this change)

- Index `Org.proj_uuid` (migration).
- TODO(SENTRY_PII): global Sentry options and `send_default_pii`.
- Remove `ProjectEventConsumer`, `flows.project-events` and the setting after SC-005 holds (Rollout step 5).
