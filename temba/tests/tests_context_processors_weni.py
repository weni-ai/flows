from django.test import RequestFactory, TestCase, override_settings

from temba.context_processors_weni import (
    old_design_excluded_channels_codes,
    show_sidemenu,
    use_weni_layout,
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

    @override_settings(OLD_DESIGN_EXCLUDED_CHANNELS_CODES=["code1", "code2"])
    def test_old_design_excluded_channels_codes(self):
        request = self.factory.get("/")
        result = old_design_excluded_channels_codes(request)
        self.assertEqual(result["old_design_excluded_channels_codes"], ["code1", "code2"])

