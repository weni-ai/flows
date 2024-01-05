from unittest.mock import patch

from rest_framework import status

from django.urls import reverse
from django.utils import timezone

from temba.tests.base import TembaTest
from temba.wpp_products.models import Catalog
from temba.wpp_products.serializers import UpdateCatalogSerializer
from temba.wpp_products.views import CatalogViewSet


class CatalogViewTest(TembaTest):
    def setUp(self):
        super().setUp()

        self.new_channel = self.create_channel("WAC", "Test WAC Channel", "54764868534")

        Catalog.objects.create(
            facebook_catalog_id="123456789",
            name="Catalog1",
            org=self.org,
            channel=self.new_channel,
            created_on=timezone.now(),
            modified_on=timezone.now(),
            is_active=False,
        )

        Catalog.objects.create(
            facebook_catalog_id="987654321",
            name="Catalog2",
            org=self.org,
            channel=self.new_channel,
            created_on=timezone.now(),
            modified_on=timezone.now(),
            is_active=False,
        )

        Catalog.objects.create(
            facebook_catalog_id="112233445",
            name="Catalog3",
            org=self.org,
            channel=self.new_channel,
            created_on=timezone.now(),
            modified_on=timezone.now(),
            is_active=False,
        )

        view_class = CatalogViewSet
        view_class.permission_classes = []
        view_class.authentication_classes = []

    def test_update_active_catalog(self):
        url = reverse("catalog-update-active-catalog")
        self.client.force_login(self.user)

        data = {"facebook_catalog_id": "112233445", "channel": self.new_channel.uuid, "is_active": True}

        serializer = UpdateCatalogSerializer(data=data)
        self.assertTrue(serializer.is_valid(), "Serializer is not valid.")

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        updated_object = Catalog.objects.filter(is_active=True).first()
        self.assertEqual(updated_object.facebook_catalog_id, data["facebook_catalog_id"])

    def test_update_catalog(self):
        self.new_channel.config["wa_waba_id"] = "123"
        self.new_channel.save(update_fields=["config"])
        url = reverse("catalog-update-catalog", args=[self.new_channel.uuid])
        self.client.force_login(self.user)

        data = dict(
            data=[
                {"id": "112233445", "name": "Catalog3"},
                {"id": "222334455", "name": "catalogproducts"},
            ]
        )
        with patch("temba.utils.whatsapp.tasks.update_local_catalogs", autospec=True) as mock_update_local_catalogs:
            mock_update_local_catalogs.return_value = None
            response = self.client.post(url, data, content_type="application/json")

            self.assertEqual(response.status_code, status.HTTP_200_OK)
