from django.core.exceptions import ValidationError
from django.utils import timezone

from temba.tests.base import TembaTest
from temba.wpp_products.models import Catalog, Product


class CatalogModelTestCase(TembaTest):
    def setUp(self):
        super().setUp()
        self.existing_catalog = Catalog(
            facebook_catalog_id="12345",
            name="Existing Catalog",
            channel=self.channel,
            org=self.org,
            created_on=timezone.now(),
            modified_on=timezone.now(),
        )
        self.existing_catalog.channel.get_type().code = "WAC"
        self.existing_catalog.save()

    def test_clean_method_valid_channel(self):
        catalog = self.existing_catalog

        catalog.channel.get_type().code = "WAC"
        catalog.save()

        try:
            catalog.clean()
        except ValidationError:
            self.fail("clean() raised ValidationError unexpectedly!")

    def test_clean_method_invalid_channel(self):
        catalog = Catalog(
            facebook_catalog_id="123456",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
        )

        catalog.channel.get_type().code = "TG"
        with self.assertRaises(ValidationError) as context:
            catalog.clean()

        self.assertEqual(str(context.exception.messages[0]), "The channel must be a 'WhatsApp Cloud' type.")

    def test_str_method(self):
        catalog = self.existing_catalog

        self.assertEqual(str(catalog), catalog.name)

    def test_trim(self):
        catalog1 = Catalog.objects.create(
            facebook_catalog_id="111",
            name="Catalog 1",
            channel=self.channel,
            org=self.org,
            created_on=timezone.now(),
            modified_on=timezone.now(),
        )

        Catalog.trim(self.channel, [self.existing_catalog, catalog1])

        remaining_catalogs = Catalog.objects.filter(channel=self.channel)
        self.assertEqual(len(remaining_catalogs), 2)
        self.assertIn(self.existing_catalog, remaining_catalogs)
        self.assertIn(catalog1, remaining_catalogs)

    def test_get_or_create_existing(self):
        existing_catalog = Catalog.get_or_create(
            name="Existing Catalog",
            channel=self.channel,
            facebook_catalog_id="12345",
            is_active=True,
        )

        self.assertEqual(existing_catalog, self.existing_catalog)
        self.assertEqual(Catalog.objects.count(), 1)

    def test_get_or_create_new(self):
        new_catalog = Catalog.get_or_create(
            name="New Catalog",
            channel=self.channel,
            facebook_catalog_id="67890",
            is_active=True,
        )

        self.assertIsNotNone(new_catalog)
        self.assertEqual(new_catalog.name, "New Catalog")
        self.assertEqual(new_catalog.facebook_catalog_id, "67890")
        self.assertEqual(new_catalog.channel, self.channel)
        self.assertEqual(new_catalog.org, self.org)
        self.assertEqual(Catalog.objects.count(), 2)

    def test_get_or_create_update_name(self):
        updated_catalog = Catalog.get_or_create(
            name="Updated Catalog",
            channel=self.channel,
            facebook_catalog_id="12345",
            is_active=True,
        )

        self.assertEqual(updated_catalog, self.existing_catalog)
        self.assertEqual(updated_catalog.name, "Updated Catalog")

        self.assertNotEqual(self.existing_catalog.modified_on, updated_catalog.modified_on)

    def test_get_or_create_update_existing(self):
        existing_catalog = Catalog.get_or_create(
            name="Existing Catalog",
            channel=self.channel,
            facebook_catalog_id="12345",
            is_active=True,
        )

        self.assertEqual(existing_catalog, self.existing_catalog)
        self.assertEqual(existing_catalog.name, "Existing Catalog")
        self.assertEqual(self.existing_catalog.modified_on, existing_catalog.modified_on)


class ProductModelTestCase(TembaTest):
    def setUp(self):
        super().setUp()
        self.catalog = Catalog.objects.create(
            facebook_catalog_id="123",
            name="Test Catalog",
            org=self.org,
            channel=self.channel,
        )

        self.catalog.channel.get_type().code = "WAC"
        self.catalog.save()

        self.existing_product = Product.objects.create(
            facebook_product_id="456",
            title="Existing Product",
            product_retailer_id="789",
            catalog=self.catalog,
        )

    def test_str_method(self):
        product = Product(
            facebook_product_id="40028922",
            title="Apple",
            product_retailer_id="usajbsjbfpohw",
            catalog=self.catalog,
        )

        self.assertEqual(str(product), product.title)

    def test_trim(self):
        product1 = Product.objects.create(
            facebook_product_id="111",
            title="Product 1",
            product_retailer_id="222",
            catalog=self.catalog,
        )

        Product.trim(self.catalog, [self.existing_product, product1])

        remaining_products = Product.objects.filter(catalog=self.catalog)
        self.assertEqual(len(remaining_products), 2)
        self.assertIn(self.existing_product, remaining_products)
        self.assertIn(product1, remaining_products)

    def test_get_or_create_existing(self):
        existing_product = Product.get_or_create(
            facebook_product_id="456",
            title="Existing Product",
            product_retailer_id="789",
            catalog=self.catalog,
            name="Test Catalog",
            channel=self.channel,
            facebook_catalog_id="123",
        )

        self.assertEqual(existing_product, self.existing_product)
        self.assertEqual(Product.objects.count(), 1)

    def test_get_or_create_new_catalog(self):
        new_product = Product.get_or_create(
            facebook_product_id="999",
            title="New Product",
            product_retailer_id="888",
            catalog=self.catalog,
            name="New Catalog",
            channel=self.channel,
            facebook_catalog_id="555",
        )

        self.assertIsNotNone(new_product)
        self.assertEqual(new_product.title, "New Product")
        self.assertEqual(new_product.product_retailer_id, "888")
        self.assertEqual(new_product.catalog.name, "Test Catalog")

        new_catalog = Catalog.objects.get(name="New Catalog")
        self.assertNotEqual(new_catalog.modified_on, self.catalog.modified_on)

        original_modified_on = new_catalog.modified_on
        Product.get_or_create(
            facebook_product_id="777",
            title="Another Product",
            product_retailer_id="999",
            catalog=new_catalog,
            name="New Catalog",
            channel=self.channel,
            facebook_catalog_id="555",
        )
        new_catalog.refresh_from_db()
        self.assertGreater(new_catalog.modified_on, original_modified_on)

    def test_get_or_create_update_existing_product(self):
        updated_product = Product.get_or_create(
            facebook_product_id="456",
            title="Updated Product",
            product_retailer_id="789",
            catalog=self.catalog,
            name="Test Catalog",
            channel=self.channel,
            facebook_catalog_id="123",
        )

        self.assertEqual(updated_product, self.existing_product)
        self.assertEqual(updated_product.title, "Updated Product")

    def test_get_or_create_update_existing_catalog(self):
        updated_product = Product.get_or_create(
            facebook_product_id="456",
            title="Existing Product",
            product_retailer_id="789",
            catalog=self.catalog,
            name="Test Catalog",
            channel=self.channel,
            facebook_catalog_id="123",
        )

        self.assertEqual(updated_product.catalog.name, "Test Catalog")
