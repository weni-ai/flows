from weni.internal.models import Project


def update_project_config(project_uuid: Project, description: str) -> Project:
    project = Project.objects.get(project_uuid=project_uuid)
    project.config["description"] = description
    project.save(update_fields=["config"])

    return project
