from django.core.exceptions import ValidationError

from temba.tests.base import TembaTest
from temba.wpp_products.models import Catalog, Product


class CatalogModelTestCase(TembaTest):
    def test_clean_method_valid_channel(self):
        catalog = Catalog(
            catalog_id_facebook="12345",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
            created_by=self.user,
            modified_by=self.user,
        )

        catalog.channel.get_type().code = "WAC"
        catalog.save()

        try:
            catalog.clean()
        except ValidationError:
            self.fail("clean() raised ValidationError unexpectedly!")

    def test_clean_method_invalid_channel(self):
        catalog = Catalog(
            catalog_id_facebook="12345",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
        )

        with self.assertRaises(ValidationError) as context:
            catalog.clean()

        self.assertEqual(str(context.exception.messages[0]), "The channel must be a 'WhatsApp Cloud' type.")

    def test_str_method(self):
        catalog = Catalog(
            catalog_id_facebook="12345",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
            created_by=self.user,
            modified_by=self.user,
        )
        catalog.channel.get_type().code = "WAC"
        catalog.save()

        self.assertEqual(str(catalog), catalog.name)


class ProductModelTestCase(TembaTest):
    def test_str_method(self):
        catalog = Catalog(
            catalog_id_facebook="12345",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
            created_by=self.user,
            modified_by=self.user,
        )
        catalog.channel.get_type().code = "WAC"
        catalog.save()

        product = Product(
            product_id_facebook="40028922",
            title="Apple",
            product_retailer_id="usajbsjbfpohw",
            catalog=catalog,
        )

        self.assertEqual(str(product), product.title)
