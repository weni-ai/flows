from django.test import RequestFactory, TestCase, override_settings

from temba.context_processors_weni import (
    logrocket,
    old_design_excluded_channels_codes,
    show_sidemenu,
    use_weni_layout,
    weni_announcement,
)


class MockUser:
    def __init__(self, is_anonymous=False, org=None):
        self.is_anonymous = is_anonymous
        self.org = org

    def get_org(self):
        return self.org


class MockTriggersQuerySet:
    def __init__(self, triggers=None):
        self.triggers = triggers or []

    def all(self):
        return self

    def exists(self):
        return bool(self.triggers)


class MockOrg:
    def __init__(self, triggers=None):
        self.triggers = MockTriggersQuerySet(triggers)


class MockTrigger:
    def exists(self):
        return True


class ContextProcessorsWeniTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(WENI_DOMAINS={"weni": "example.com"})
    def test_use_weni_layout(self):
        request = self.factory.get("/")
        request.META["HTTP_HOST"] = "example.com"

        result = use_weni_layout(request)
        self.assertEqual(result["use_weni_layout"], True)

    @override_settings(SIDEBAR_EXCLUDE_PATHS=["/admin/"], SIDEBAR_ALLOWLIST=[])
    def test_show_sidemenu(self):
        request = self.factory.get("/")

        result = show_sidemenu(request)
        self.assertEqual(result["show_sidemenu"], False)

        request.path = "/other/path/"
        result = show_sidemenu(request)
        self.assertEqual(result["show_sidemenu"], True)

        result = show_sidemenu(request)
        self.assertEqual(result["show_sidemenu"], True)

        request.path = "/admin/"
        result = show_sidemenu(request)
        self.assertEqual(result["show_sidemenu"], False)

    @override_settings(
        ANNOUNCEMENT_LEFT="Left announcement",
        ANNOUNCEMENT_RIGHT="Right announcement",
        ANNOUNCEMENT_LINK="https://example.com",
        ANNOUNCEMENT_BUTTON="Click me",
    )
    def test_weni_announcement(self):
        request = self.factory.get("/")

        result = weni_announcement(request)
        self.assertEqual(result["announcement_left"], "Left announcement")
        self.assertEqual(result["announcement_right"], "Right announcement")
        self.assertEqual(result["announcement_link"], "https://example.com")
        self.assertEqual(result["announcement_button"], "Click me")

    @override_settings(PARENT_IFRAME_DOMAIN="example.com", LOGROCKET_IDS={"example.com": "logrocket_id"})
    def test_logrocket(self):
        request = self.factory.get("/")
        request.META["HTTP_HOST"] = "example.com"

        result = logrocket(request)
        self.assertEqual(result["parent_iframe_domain"], "example.com")
        self.assertEqual(result["logrocket_id"], "logrocket_id")

    @override_settings(OLD_DESIGN_EXCLUDED_CHANNELS_CODES=["code1", "code2"])
    def test_old_design_excluded_channels_codes(self):
        request = self.factory.get("/")
        result = old_design_excluded_channels_codes(request)
        self.assertEqual(result["old_design_excluded_channels_codes"], ["code1", "code2"])

