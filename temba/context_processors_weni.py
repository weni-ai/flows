from django.conf import settings


def use_weni_layout(request):
    host = request.get_host().split(":")[0]

    return {"use_weni_layout": host.endswith(settings.WENI_DOMAINS["weni"])}


def show_sidemenu(request):
    if request.path == "/":
        return {"show_sidemenu": False}

    for path in settings.SIDEBAR_EXCLUDE_PATHS:
        if request.path not in settings.SIDEBAR_ALLOWLIST:
            if path in request.path:
                return {"show_sidemenu": False}

    return {"show_sidemenu": True}


def hotjar(request):
    return {
        "hotjar_id": settings.HOTJAR_ID,
    }


def old_design_excluded_channels_codes(request):
    return {"old_design_excluded_channels_codes": settings.OLD_DESIGN_EXCLUDED_CHANNELS_CODES}
