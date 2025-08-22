from datetime import timedelta
from typing import Optional, Dict, Any

from django.conf import settings

from . import s3


# Default expiration time for presigned URLs (1 hour)
DEFAULT_EXPIRES = 60 * 60


def generate_presigned_url(
    path: str,
    expires_in: int = DEFAULT_EXPIRES,  # default 1 hour
    response_headers: Optional[Dict[str, str]] = None,
    http_method: str = "GET",
) -> str:
    """
    Generate a presigned URL for accessing an S3 object.
    
    Args:
        path: The path to the object in S3 (without bucket name)
        expires_in: Number of seconds until the presigned URL expires (default: 1 hour)
        response_headers: Optional dict of response headers to enforce
        http_method: The HTTP method to allow (default: GET)
        
    Returns:
        str: The presigned URL
    """
    s3_client = s3.client()
    bucket = settings.AWS_STORAGE_BUCKET_NAME

    # Build parameters for the presigned URL
    s3_params = {
        "Bucket": bucket,
        "Key": path,
    }

    # Add any response headers if specified
    if response_headers:
        for header_name, header_value in response_headers.items():
            s3_params[f"Response{header_name}"] = header_value

    return s3_client.generate_presigned_url(
        "get_object",
        Params=s3_params,
        ExpiresIn=expires_in,
        HttpMethod=http_method,
    )


def get_download_headers(filename: str, content_type: Optional[str] = None) -> Dict[str, str]:
    """
    Get standard response headers for file downloads
    
    Args:
        filename: The filename to use for download
        content_type: Optional content type to enforce
        
    Returns:
        dict: Response headers for S3 presigned URL
    """
    headers = {
        "ContentDisposition": f"attachment; filename={filename}",
    }
    
    if content_type:
        headers["ContentType"] = content_type
        
    return headers 