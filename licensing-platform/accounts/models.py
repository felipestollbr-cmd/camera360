from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    vendor=None + is_superuser=True -> você (super admin, gerencia todos os
    vendedores). vendor setado -> login do vendedor, só vê o que é dele
    (aplicado nas views/querysets, não aqui no model).
    """
    vendor = models.ForeignKey(
        'licensing.Vendor', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='team_members')

    @property
    def is_vendor_user(self):
        return self.vendor_id is not None
