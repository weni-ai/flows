from django.core.management.base import BaseCommand, CommandError

from temba import mailroom
from temba.flows.models import Flow
from temba.mailroom.client import FlowValidationException
from temba.orgs.models import Org


def resolve_org(org_identifier):
    """
    Resolve an org by numeric id, org uuid, or project uuid (proj_uuid).
    """
    try:
        return Org.objects.get(id=int(org_identifier))
    except (ValueError, Org.DoesNotExist):
        pass

    try:
        return Org.objects.get(proj_uuid=org_identifier)
    except (ValueError, Org.DoesNotExist):
        pass

    try:
        return Org.objects.get(uuid=org_identifier)
    except (ValueError, Org.DoesNotExist):
        pass

    raise CommandError(f"No such org matching '{org_identifier}'")


def get_flow_queryset(*, org=None, flow_uuid=None):
    if flow_uuid:
        return Flow.objects.filter(uuid=flow_uuid).order_by("id")

    flows = Flow.objects.filter(is_active=True)
    if org:
        flows = flows.filter(org=org)

    return flows.order_by("id")


def _inspect_flow(client, flow):
    return client.flow_inspect(flow.org_id, flow.get_definition())


def _report_inspection_error(flow, stdout, exc):
    if not stdout:
        return

    if isinstance(exc, FlowValidationException):
        stdout.write(f" Invalid: {flow.uuid} {flow.name}")
        return

    stdout.write(f" Unreadable: {flow.uuid} {flow.name} ({type(exc).__name__}: {exc})")


def _sync_has_issues(flow, flow_info, dry_run, stdout):
    has_issues = len(flow_info["issues"]) > 0
    if has_issues == flow.has_issues:
        return False

    if stdout:
        action = "Would update" if dry_run else "Updated"
        stdout.write(f" {action}: {flow.uuid} {flow.name} (has_issues {flow.has_issues} -> {has_issues})")

    if not dry_run:
        flow.has_issues = has_issues
        flow.save(update_fields=("has_issues",))

    return True


def _write_progress(stdout, num_inspected, num_updated, num_failed):
    if num_inspected % 100 == 0:  # pragma: no cover
        stdout.write(f" > Flows inspected: {num_inspected}, updated: {num_updated}, failed: {num_failed}")


def _write_summary(stdout, num_inspected, num_updated, num_failed):
    summary = f"Total flows inspected: {num_inspected}, updated: {num_updated}, failed: {num_failed}"
    if stdout:
        stdout.write(summary)
    else:
        print(summary)


def inspect_flows(*, org=None, flow_uuid=None, dry_run=False, stdout=None):
    if org and flow_uuid:
        raise CommandError("Specify only one of --org or --flow")

    client = mailroom.get_client()
    num_inspected = 0
    num_updated = 0
    num_failed = 0

    for flow in get_flow_queryset(org=org, flow_uuid=flow_uuid):
        num_inspected += 1

        try:
            flow_info = _inspect_flow(client, flow)
        except Exception as exc:
            num_failed += 1
            _report_inspection_error(flow, stdout, exc)
            continue

        if _sync_has_issues(flow, flow_info, dry_run, stdout):
            num_updated += 1

        if stdout:
            _write_progress(stdout, num_inspected, num_updated, num_failed)

    _write_summary(stdout, num_inspected, num_updated, num_failed)
    return num_inspected, num_updated, num_failed


class Command(BaseCommand):
    help = "Inspects flows and fixes has_issues where needed"

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            dest="org",
            help="Org id, org uuid, or project uuid to limit inspection to a single workspace",
        )
        parser.add_argument(
            "--flow",
            dest="flow_uuid",
            help="Flow UUID to inspect a single flow",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Report changes without saving has_issues",
        )

    def handle(self, *args, **options):
        org = None
        if options["org"]:
            org = resolve_org(options["org"])

        inspect_flows(
            org=org,
            flow_uuid=options["flow_uuid"],
            dry_run=options["dry_run"],
            stdout=self.stdout,
        )
