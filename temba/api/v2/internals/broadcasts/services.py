from django.conf import settings

from temba.orgs.models import Org
from temba.utils.s3 import public_file_storage
from temba.utils.uuid import uuid4


def upload_broadcast_media(org: Org, file) -> dict:
    """
    Saves the given file to storage under a predictable attachments path and returns metadata.
    - Path: attachments/<org_id>/broadcasts/<random_uuid>/<original_filename>
    - Returns: {"type": <mime>, "url": <public_url>}
    """
    random_uuid_folder_name = str(uuid4())
    extension = file.name.split(".")[-1].lower() if "." in file.name else ""

    # Normalize certain extensions to correct MIME types
    if extension == "m4a":
        file.content_type = "audio/mp4"

    path = f"attachments/{org.pk}/broadcasts/{random_uuid_folder_name}/{file.name}"
    saved_path = public_file_storage.save(path, file)
    return {"type": file.content_type, "url": f"{settings.STORAGE_URL}/{saved_path}"}
