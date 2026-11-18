# Quickstart: validate the project events migration

**Feature**: [spec.md](./spec.md) | **Contract**: [contracts/project-events.md](./contracts/project-events.md)

## Prerequisites

- The repository's local setup: Poetry environment, PostgreSQL with PostGIS, and Redis, as for any `manage.py test` run.
- No broker is needed locally. Tests call `handle()` with a mocked channel. `edaconsume-amq` forces TLS (`AMQConnectionParamsFactory`), so the end-to-end check runs on staging.

## 1. Automated checks (local and CI)

```bash
poetry run coverage run manage.py test temba.projects
poetry run coverage report -m --include="temba/projects/consumers/*,temba/projects/usecases/project_*.py,temba/projects/checks.py"
./code_check.py
```

Expected:

- All tests pass.
- The coverage report shows `ProjectConsumer.consume` and `ProjectEventConsumer.consume` as covered, and no `# pragma: no cover` remains on either method (review gate RG-1):

  ```bash
  rg -n "def consume.*pragma: no cover" temba/projects/consumers/project_consumer.py temba/projects/consumers/project_event_consumer.py
  ```

  This should print nothing.

- `./code_check.py` is clean (Black, flake8, isort, no missing migrations).

## 2. Scenarios the tests must cover

| Scenario | Where | Expected outcome |
|----------|-------|------------------|
| Each of the four events with `PROJECT_EVENTS_LEGACY_ACTIONS=[]` | `temba/projects/consumers/tests/test_project_consumer.py` | Org fields and `modified_by` updated; `basic_ack` (AC-1, US1) |
| All four actions with the default list and with `[]`, plus `["project_type_update"]`; legacy message and AmazonMQ event for the same change | `test_project_consumer.py`, `test_project_event_consumer.py` | Exactly one consumer calls the use case; the other acks and logs `project_event_skipped` (AC-2, SC-002, US2) |
| Invalid `data.uuid`, missing `user_email`, missing or unknown `status`, `is_multi_agents` of `1` or `"true"`, unknown `timezone`, envelope with a missing key | `test_project_consumer.py` | `basic_reject(tag, requeue=False)`, one `capture_exception`, org unchanged (AC-3, US3) |
| `event_id` with a space or a line break, `event_id` as a number, `producer` as an object, `event_type` over 64 characters; also on a `project.created` envelope | `test_project_consumer.py`, `test_project_event_payloads.py` | Rejected, no `project_event_consumed` line, the rejected value appears in no log record (AC-3, FR-012) |
| Legacy message whose `project_uuid` is not a UUID | `test_project_event_consumer.py` | Same outcome as today; log lines and tags carry no `project_uuid` value (FR-012) |
| `project.deleted` twice; `delete_project` twice | `test_project_consumer.py`, `temba/projects/usecases/tests/test_project_delete.py` | Second call leaves `released_on` and `modified_by` unchanged and acks (AC-4) |
| Channel release raises during `delete_project` | `test_project_delete.py` | Org still `is_active`, `released_on` still `None` |
| Valid event for each type with an unknown `uuid` | `test_project_consumer.py` | `basic_ack`, `project_event_org_not_found` warning with `project_uuid` and `event_id` (AC-5) |
| Every flow above under `assertLogs("temba.projects")` and the `weni-eda` rejection log | consumer and use case tests | No output contains the user's e-mail or the org name (AC-6) |
| Sentry scope for a rejected event | `test_project_consumer.py`, consumer helper tests | Tags `project_uuid`, `event_id`, `org_id` and `user_id` set (no `user_id`, and no user created, when the e-mail has no `User`); `scrub_sentry_event` removes frame `vars` and replaces e-mails in exception values |
| Use case raises an exception whose message contains the e-mail and the org name | `test_project_consumer.py` | Neither appears in the captured Sentry event nor in the `weni-eda` rejection log (AC-6, SC-004) |
| `project.created` existing tests; unknown `event_type` | `test_project_consumer.py` | Unchanged; unknown type acked (AC-7) |
| System check | app tests for `temba.projects.checks` | `["deleted", "bogus"]` gives `projects.E001`; the default and `[]` give no error; the default equals the `EventAction` values |

## 3. Start-up refusal with an unknown action

```bash
PROJECT_EVENTS_LEGACY_ACTIONS="deleted,bogus" poetry run python manage.py check
```

Expected: exit code 1, with an error `projects.E001` that names `bogus`. Then:

```bash
PROJECT_EVENTS_LEGACY_ACTIONS="" poetry run python manage.py check
PROJECT_EVENTS_LEGACY_ACTIONS="project_type_update" poetry run python manage.py check
```

Expected: both report no issues.

## 4. Changelog review (review gate RG-2)

`WENI-CHANGELOG.md` has, under a new topmost heading for the next version:

- a `feat:` bullet for consuming `project.updated`, `project.status.updated`, `project.type.updated` and `project.deleted` from AmazonMQ, controlled by `PROJECT_EVENTS_LEGACY_ACTIONS`;
- a bullet announcing that `flows.project-events` is deprecated.

## 5. Staging end-to-end (after the infrastructure bindings exist)

1. Confirm that `flows.projects.queue` is bound to `projects.topic` with the four new routing keys and has a dead-letter exchange.
2. Deploy with the variable unset. Publish a `project.status.updated` envelope from the contract for a staging org to `projects.topic`. Expected: `edaconsume-amq` logs `project_event_consumed` and `project_event_skipped reason=legacy_consumer_applies`; the org is unchanged; the message is acked.
3. Set `PROJECT_EVENTS_LEGACY_ACTIONS=""` on both `edaconsume` and `edaconsume-amq`, and restart both. Publish the same event with `INACTIVE`. Expected: the org is suspended, and a legacy message for the same change is acked and logged as skipped.
4. Publish an envelope with `"status": "PAUSED"`. Expected: the message is in the dead-letter queue; a Sentry event is tagged with `event_id` and `project_uuid` and has no e-mail and no frame variables; the org is unchanged.
5. Restore the variable to unset (rollback) and restart both processes.
