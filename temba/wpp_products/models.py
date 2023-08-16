from uuid import uuid4
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from temba.channels.models import Channel
from temba.orgs.models import Org


class Catalog(models.Model):
    uuid = models.UUIDField(default=uuid4())
    facebook_catalog_id = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="catalogs")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="catalogs")
    created_on = models.DateTimeField(default=timezone.now)
    modified_on = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.channel.get_type().code != "WAC":
            raise ValidationError("The channel must be a 'WhatsApp Cloud' type.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Product(models.Model):
    uuid = models.UUIDField(default=uuid4())
    facebook_product_id = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)
    product_retailer_id = models.CharField(max_length=50)
    catalog = models.ForeignKey(Catalog, on_delete=models.CASCADE, related_name="products")
    created_on = models.DateTimeField(default=timezone.now)
    modified_on = models.DateTimeField(default=timezone.now)

    @classmethod
    def trim(cls, catalog, existing):
        """
        Trims what channel templates exist for this channel based on the set of templates passed in
        """
        ids = [tc.id for tc in existing]

        # mark any that weren't included as inactive
        Product.objects.filter(catalog=catalog).exclude(id__in=ids).update(is_active=False)

        # Make sure the seen one are active
        Product.objects.filter(catalog=catalog, id__in=ids, is_active=False).update(is_active=True)

    @classmethod
    def get_or_create(cls, facebook_product_id, title, product_retailer_id, catalog, channel, name, facebook_catalog_id):
        existing = Product.objects.filter(catalog=catalog).first()

        if not existing:
            new_catalog = Catalog.objects.filter(org=channel.org, name=name).first()
            if not new_catalog:
                new_catalog = Catalog.objects.create(
                    org=channel.org, name=name, channel=channel, created_on=timezone.now(), modified_on=timezone.now()
                )
            else:
                new_catalog.modified_on = timezone.now()
                new_catalog.save(update_fields=["modified_on"])

            existing = Product.objects.create(
                facebook_product_id=facebook_product_id,
                title=title,
                product_retailer_id=product_retailer_id,
                catalog=catalog,
            )

        else:
            if (
                existing.title != title
                or existing.product_retailer_id != product_retailer_id
            ):
                existing.title = title
                existing.product_retailer_id = product_retailer_id

                existing.save(
                    update_fields=[
                        "title",
                        "product_retailer_id",
                    ]
                )

                existing.template.modified_on = timezone.now()
                existing.template.save(update_fields=["modified_on"])

        return existing

    def __str__(self):
        return self.title
