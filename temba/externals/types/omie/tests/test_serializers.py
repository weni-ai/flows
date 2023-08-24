from django.contrib.auth.models import User
from django.test import TestCase

from temba.externals.models import ExternalService
from temba.externals.types.omie.serializers import OmieSerializer
from temba.externals.types.omie.type import OmieType
from temba.orgs.models import Org


class OmieSerializerTestCase(TestCase):
    def test_create(self):
        user = User.objects.create_user(username="super", email="super@user.com", password="super")
        org = Org.objects.create(
            name="X-Temba-Org",
            timezone="Africa/Kigali",
            created_by=user,
            modified_by=user,
        )

        type_ = OmieType
        data = {
            "name": "Omie",
            "app_key": "your-app-key",
            "app_secret": "your-app-secret",
        }

        serializer = OmieSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(type=type_, created_by=user, modified_by=user, org=org)

        self.assertIsInstance(instance, ExternalService)
        self.assertEqual(instance.name, "Omie")
        self.assertEqual(instance.external_service_type, type_.slug)
        self.assertEqual(instance.config[type_.CONFIG_APP_KEY], "your-app-key")
        self.assertEqual(instance.config[type_.CONFIG_APP_SECRET], "your-app-secret")
