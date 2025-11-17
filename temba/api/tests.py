from datetime import timedelta
from unittest.mock import patch

import jwt as _pyjwt
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from django.conf import settings as _dj_settings
from django.contrib.auth.models import Group
from django.test import override_settings
from django.utils import timezone

from temba.api.auth.jwt import (
    JWTAuthMixinOptional,
    JWTAuthMixinRequired,
    OptionalJWTAuthentication,
    RequiredJWTAuthentication,
)
from temba.api.models import APIToken, Resthook, WebHookEvent
from temba.api.tasks import trim_webhook_event_task
from temba.tests import TembaTest


class APITokenTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.admins_group = Group.objects.get(name="Administrators")
        self.editors_group = Group.objects.get(name="Editors")
        self.surveyors_group = Group.objects.get(name="Surveyors")

        self.org2.surveyors.add(self.admin)  # our admin can act as surveyor for other org

    def test_get_or_create(self):
        token1 = APIToken.get_or_create(self.org, self.admin)
        self.assertEqual(token1.org, self.org)
        self.assertEqual(token1.user, self.admin)
        self.assertEqual(token1.role, self.admins_group)
        self.assertTrue(token1.key)
        self.assertEqual(str(token1), token1.key)

        # tokens for different roles with same user should differ
        token2 = APIToken.get_or_create(self.org, self.admin, self.admins_group)
        token3 = APIToken.get_or_create(self.org, self.admin, self.editors_group)
        token4 = APIToken.get_or_create(self.org, self.admin, self.surveyors_group)

        self.assertEqual(token1, token2)
        self.assertNotEqual(token1, token3)
        self.assertNotEqual(token1, token4)
        self.assertNotEqual(token1.key, token3.key)

        # tokens with same role for different users should differ
        token5 = APIToken.get_or_create(self.org, self.editor)

        self.assertNotEqual(token3, token5)

        APIToken.get_or_create(self.org, self.surveyor)

        # can't create token for viewer users or other users using viewers role
        self.assertRaises(ValueError, APIToken.get_or_create, self.org, self.admin, Group.objects.get(name="Viewers"))
        self.assertRaises(ValueError, APIToken.get_or_create, self.org, self.user)

    def test_get_orgs_for_role(self):
        self.assertEqual(set(APIToken.get_orgs_for_role(self.admin, self.admins_group)), {self.org})
        self.assertEqual(set(APIToken.get_orgs_for_role(self.admin, self.surveyors_group)), {self.org, self.org2})

    def test_get_allowed_roles(self):
        self.assertEqual(
            set(APIToken.get_allowed_roles(self.org, self.admin)),
            {Group.objects.get(name="Prometheus"), self.admins_group, self.editors_group, self.surveyors_group},
        )
        self.assertEqual(
            set(APIToken.get_allowed_roles(self.org, self.editor)), {self.editors_group, self.surveyors_group}
        )
        self.assertEqual(set(APIToken.get_allowed_roles(self.org, self.surveyor)), {self.surveyors_group})
        self.assertEqual(set(APIToken.get_allowed_roles(self.org, self.user)), set())

        # user from another org has no API roles
        self.assertEqual(set(APIToken.get_allowed_roles(self.org, self.admin2)), set())

    def test_get_default_role(self):
        self.assertEqual(APIToken.get_default_role(self.org, self.admin), self.admins_group)
        self.assertEqual(APIToken.get_default_role(self.org, self.editor), self.editors_group)
        self.assertEqual(APIToken.get_default_role(self.org, self.surveyor), self.surveyors_group)
        self.assertIsNone(APIToken.get_default_role(self.org, self.user))

        # user from another org has no API roles
        self.assertIsNone(APIToken.get_default_role(self.org, self.admin2))


class WebHookTest(TembaTest):
    def test_trim_events_and_results(self):
        five_hours_ago = timezone.now() - timedelta(hours=5)

        # create some events
        resthook = Resthook.get_or_create(org=self.org, slug="registration", user=self.admin)
        WebHookEvent.objects.create(org=self.org, resthook=resthook, data={}, created_on=five_hours_ago)

        with override_settings(RETENTION_PERIODS={"webhookevent": None}):
            trim_webhook_event_task()
            self.assertTrue(WebHookEvent.objects.all())

        with override_settings(RETENTION_PERIODS={"webhookevent": timedelta(hours=12)}):  # older than our event
            trim_webhook_event_task()
            self.assertTrue(WebHookEvent.objects.all())

        with override_settings(RETENTION_PERIODS={"webhookevent": timedelta(hours=2)}):
            trim_webhook_event_task()
            self.assertFalse(WebHookEvent.objects.all())


class JWTAuthCoverageTests(TembaTest):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def test_optional_invalid_header_and_missing_key_paths(self):
        auth = OptionalJWTAuthentication()
        # invalid header type
        req = self.factory.get("/")
        req.headers = {"Authorization": 123}
        self.assertIsNone(auth.authenticate(req))
        # invalid prefix
        req = self.factory.get("/")
        req.headers = {"Authorization": "Token abc"}
        self.assertIsNone(auth.authenticate(req))
        # missing key with Bearer
        with self.settings(JWT_PUBLIC_KEY=None):
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer token"}
            self.assertIsNone(auth.authenticate(req))

    def test_optional_decode_errors_return_none(self):
        auth = OptionalJWTAuthentication()
        with self.settings(JWT_PUBLIC_KEY="dummy"):
            # invalid token
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer bad"}
            with patch("temba.api.auth.jwt.jwt.decode", side_effect=_pyjwt.InvalidTokenError("bad")):
                self.assertIsNone(auth.authenticate(req))
            # expired token
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer expired"}
            with patch("temba.api.auth.jwt.jwt.decode", side_effect=_pyjwt.ExpiredSignatureError("expired")):
                self.assertIsNone(auth.authenticate(req))

    def test_required_missing_key_and_header_and_prefix(self):
        auth = RequiredJWTAuthentication()
        # missing key
        with self.settings(JWT_PUBLIC_KEY=None):
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer any"}
            with self.assertRaises(AuthenticationFailed):
                auth.authenticate(req)
        # missing header
        with self.settings(JWT_PUBLIC_KEY="dummy"):
            req = self.factory.get("/")
            with self.assertRaises(AuthenticationFailed):
                auth.authenticate(req)
            # invalid prefix
            req = self.factory.get("/")
            req.headers = {"Authorization": "Token abc"}
            with self.assertRaises(AuthenticationFailed):
                auth.authenticate(req)

    def test_required_decode_errors_and_success(self):
        auth = RequiredJWTAuthentication()
        with self.settings(JWT_PUBLIC_KEY="dummy"):
            # expired
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer expired"}
            with patch("temba.api.auth.jwt.jwt.decode", side_effect=_pyjwt.ExpiredSignatureError("expired")):
                with self.assertRaises(AuthenticationFailed):
                    auth.authenticate(req)
            # invalid
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer bad"}
            with patch("temba.api.auth.jwt.jwt.decode", side_effect=_pyjwt.InvalidTokenError("bad")):
                with self.assertRaises(AuthenticationFailed):
                    auth.authenticate(req)
            # missing project_uuid
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer ok"}
            with patch("temba.api.auth.jwt.jwt.decode", return_value={"x": 1}):
                with self.assertRaises(AuthenticationFailed):
                    auth.authenticate(req)
            # success
            req = self.factory.get("/")
            req.headers = {"Authorization": "Bearer ok"}
            payload = {"project_uuid": "proj-xyz", "k": "v"}
            with patch("temba.api.auth.jwt.jwt.decode", return_value=payload):
                user, _ = auth.authenticate(req)
            from django.contrib.auth.models import AnonymousUser

            self.assertIsInstance(user, AnonymousUser)
            self.assertEqual(getattr(req, "project_uuid", None), "proj-xyz")
            self.assertEqual(getattr(req, "jwt_payload", None), payload)

    def test_getters_and_mixins(self):
        # Optional get_settings/get_jwt
        opt = OptionalJWTAuthentication()
        self.assertIs(opt.get_settings(), _dj_settings)
        self.assertIs(opt.get_jwt(), _pyjwt)
        # Required get_settings/get_jwt
        req_auth = RequiredJWTAuthentication()
        self.assertIs(req_auth.get_settings(), _dj_settings)
        self.assertIs(req_auth.get_jwt(), _pyjwt)
        # Mixins properties

        class D1(JWTAuthMixinRequired):
            request = None

        class D2(JWTAuthMixinOptional):
            request = None

        r = self.factory.get("/")
        r.project_uuid = "p1"
        r.jwt_payload = {"a": 1}
        d1 = D1()
        d1.request = r
        d2 = D2()
        d2.request = r
        self.assertEqual(d1.project_uuid, "p1")
        self.assertEqual(d1.jwt_payload, {"a": 1})
        self.assertEqual(d2.project_uuid, "p1")
        self.assertEqual(d2.jwt_payload, {"a": 1})
