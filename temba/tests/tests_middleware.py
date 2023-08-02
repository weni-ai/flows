from unittest.mock import MagicMock, Mock

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from temba.context_processors_weni import use_weni_layout
from temba.middleware import (
    ExceptionMiddleware,
    LanguageMiddleware,
    OrgMiddleware,
    RedirectMiddleware,
    TimezoneMiddleware,
)
from temba.orgs.models import Org


class ExceptionMiddlewareTest(TestCase):
    def test_process_exception_debug_true(self):
        middleware = ExceptionMiddleware(get_response=lambda x: HttpResponse())
        request = RequestFactory().get("/")
        settings.DEBUG = True

        response = middleware(request)

        self.assertIsInstance(response, HttpResponse)

    def test_process_exception_debug_false(self):
        middleware = ExceptionMiddleware(get_response=lambda x: HttpResponse())
        request = RequestFactory().get("/")
        exception = Exception("Test exception")
        settings.DEBUG = False

        response = middleware.process_exception(request, exception)

        self.assertIsNone(response)


class OrgMiddlewareTest(TestCase):
    databases = ("default", "readonly")

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = OrgMiddleware(get_response=lambda request: HttpResponse())
        self.user = User.objects.create_user(username="super", email="super@user.com", password="super")
        self.org = Org.objects.create(
            name="X-Temba-Org",
            timezone="Africa/Kigali",
            brand=settings.DEFAULT_BRAND,
            created_by=self.user,
            modified_by=self.user,
        )

    def test_middleware_no_org(self):
        user = User.objects.create_user(username="testuser", password="testpassword")

        request = self.factory.get("/")
        request.user = user
        request.session = {}

        response = self.middleware(request)

        self.assertIsNone(request.org)
        self.assertNotIn("X-Temba-Org", response)

    def test_user_not_authenticated(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session.save()

        response = self.middleware(request)

        self.assertIsNone(request.org)
        self.assertEqual(response.status_code, 200)

    def test_user_authenticated_with_session_org_id(self):
        org = self.org
        request = self.factory.get("/")
        user = Mock()
        user.is_authenticated = True
        user.set_org = Mock()
        request.user = user

        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session["org_id"] = org.id
        request.session.save()

        response = self.middleware(request)

        self.assertEqual(request.org, org)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(user.set_org.called)
        self.assertTrue(user.set_org.count(), 1)
        self.assertEqual(user.set_org.call_args[0][0], org)

    def test_user_authenticated_get_user_orgs(self):
        org = self.org
        user = Mock()
        user.is_authenticated = True
        user_orgs = MagicMock()
        user_orgs.count.return_value = 1
        user_orgs.__len__.return_value = 1
        user_orgs.__getitem__.return_value = org
        user.get_user_orgs.return_value = user_orgs

        request = self.factory.get("/")
        request.user = user

        middleware = SessionMiddleware()
        middleware.process_request(request)
        request.session.save()

        response = self.middleware(request)

        self.assertEqual(request.org, org)
        self.assertEqual(response.status_code, 200)

        self.assertTrue(user.set_org.called)
        self.assertEqual(user.set_org.call_args[0][0], org)
        self.assertEqual(response["X-Temba-Org"], str(org.id))


class TimezoneMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_timezone_middleware_org_timezone(self):
        request = self.factory.get("/")
        request.org = Mock(timezone="UTC")

        middleware = TimezoneMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response, None)
        self.assertEqual(timezone.get_current_timezone_name(), "UTC")

    def test_timezone_middleware_default_timezone(self):
        request = self.factory.get("/")
        request.org = None

        middleware = TimezoneMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response, None)
        self.assertEqual(timezone.get_current_timezone_name(), settings.USER_TIME_ZONE)


class LanguageMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_language_middleware_authenticated_user(self):
        request = self.factory.get("/")
        user = User.objects.create_user(username="testuser", password="testpass")
        request.user = user

        middleware = LanguageMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response, None)
        self.assertEqual(translation.get_language(), user.get_settings().language)

    def test_language_middleware_unauthenticated_user(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()
        request.branding = {"language": settings.DEFAULT_LANGUAGE}

        branding_language = "en-us"
        middleware = LanguageMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response, None)
        self.assertEqual(translation.get_language(), branding_language)


class RedirectMiddlewareTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_redirect_middleware_weni_layout_enabled(self):
        settings.WENI_DOMAINS = {"weni": "example.com"}
        request = self.factory.get("/")
        request.path = "/test"
        request.META["HTTP_HOST"] = "example.com"
        result = use_weni_layout(request)

        self.assertEqual(result["use_weni_layout"], True)

        setattr(request, "use_weni_layout", {"use_weni_layout": True})

        middleware = RedirectMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertIsNone(response)
        self.assertEqual(response, None)

    def test_redirect_middleware_no_weni_layout(self):
        request = self.factory.get("/")
        request.path = "/test"
        setattr(request, "use_weni_layout", False)

        middleware = RedirectMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("weni.redirect"))

    def test_redirect_middleware_redirect_path(self):
        request = self.factory.get("/")
        request.path = "/test"
        setattr(request, "use_weni_layout", False)

        middleware = RedirectMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("weni.redirect"))

    def test_redirect_middleware_exempt_paths(self):
        request = self.factory.get("/")
        request.path = "/redirect/test"
        setattr(request, "use_weni_layout", False)

        middleware = RedirectMiddleware(get_response=lambda request: None)
        response = middleware(request)

        self.assertIsNone(response)

        request.path = "/api/test"
        response = middleware(request)

        self.assertIsNone(response)
