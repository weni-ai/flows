from django.core.exceptions import ValidationError
from django.db import models

from temba.channels.models import Channel
from temba.orgs.models import Org
from temba.utils.models import TembaModel


class Catalog(TembaModel):
    catalog_id_facebook = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    org = models.ForeignKey(Org, on_delete=models.PROTECT, related_name="catalogs")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="catalogs")

    def __str__(self):
        return self.name

    def clean(self) -> None:
        super().clean()
        if self.channel.get_type().code != "WAC":
            raise ValidationError("The channel must be a 'WhatsApp Cloud' type.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class Product(TembaModel):
    product_id_facebook = models.CharField(max_length=30, unique=True)
    title = models.CharField(max_length=200)
    product_retailer_id = models.CharField(max_length=50)
    catalog = models.ForeignKey(Catalog, on_delete=models.CASCADE, related_name="products")

    def __str__(self):
        return self.title
