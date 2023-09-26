from weni.internal.models import Project

from django.contrib.auth.models import User

from temba.globals.models import Global


def create_globals(extra_fields: dict, project: Project, user: User) -> Global:
    globals_list = []

    for name, value in extra_fields.items():
        new_global = Global.get_or_create(
            project.org,
            user,
            key=Global.make_key(name=name),
            name=name,
            value=value,
        )
        globals_list.append(new_global)

    return globals_list
