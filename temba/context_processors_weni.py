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


def weni_announcement(request):
    return {
        "announcement_left": settings.ANNOUNCEMENT_LEFT,
        "announcement_right": settings.ANNOUNCEMENT_RIGHT,
        "announcement_link": settings.ANNOUNCEMENT_LINK,
        "announcement_button": settings.ANNOUNCEMENT_BUTTON,
    }


def logrocket(request):
    domain = ".".join(request.get_host().split(":")[0].split(".")[-2:])
    return {
        "parent_iframe_domain": settings.PARENT_IFRAME_DOMAIN,
        "logrocket_id": settings.LOGROCKET_IDS.get(domain, ""),
    }


def old_design_excluded_channels_codes(request):
    return {"old_design_excluded_channels_codes": settings.OLD_DESIGN_EXCLUDED_CHANNELS_CODES}


def show_onboard_modal(request):
    if not request.user or request.user.is_anonymous:
        return {"show_trigger_onboard_modal": False}

    user_org = request.user.get_org()
    if not user_org:
        return {"show_trigger_onboard_modal": False}

    triggers = user_org.triggers.all()

    show_trigger_onboard_modal = not triggers.exists()

    return {"show_trigger_onboard_modal": show_trigger_onboard_modal}


def firebase_credentials(request):
    return {
        "firebase_api_key": settings.FIREBASE_API_KEY,
        "firebase_auth_domain": settings.FIREBASE_AUTH_DOMAIN,
        "firebase_project_id": settings.FIREBASE_PROJECT_ID,
        "firebase_storage_bucket": settings.FIREBASE_STORAGE_BUCKET,
        "firebase_messaging_sender_id": settings.FIREBASE_MESSAGING_SENDER_ID,
        "firebase_app_id": settings.FIREBASE_APP_ID,
        "firebase_measurement_id": settings.FIREBASE_MEASUREMENT_ID,
    }
