from django.db.models import Count

from temba.contacts.models import ContactGroup


def count_unique_contacts_in_groups(group_ids: list[int]) -> int:
    """
    Returns the number of unique contacts that are members of any of the given groups.
    Uses a direct query on the M2M through table for performance.
    """
    if not group_ids:
        return 0

    through = ContactGroup.contacts.through

    # Count DISTINCT contact_ids across the selected groups using the readonly replica when available
    return through.objects.filter(contactgroup_id__in=group_ids).values("contact_id").distinct().count()


def count_duplicate_contacts_across_groups(group_ids: list[int]) -> int:
    """
    Returns the number of contacts that appear in 2 or more of the given groups.
    Optimized using group-by with HAVING on the M2M through table.
    """
    if not group_ids:
        return 0

    through = ContactGroup.contacts.through

    return (
        through.objects.filter(contactgroup_id__in=group_ids)
        .values("contact_id")
        .annotate(n=Count("contactgroup_id", distinct=True))
        .filter(n__gte=2)
        .count()
    )
