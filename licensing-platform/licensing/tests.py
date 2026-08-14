from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Customer, License, Sale, Vendor

User = get_user_model()


class LicenseFlowTests(TestCase):
    """Cobre o fluxo completo: super admin cria vendedor -> vendedor cria
    cliente e emite licença -> marca a venda como paga -> Camera360 ativa e
    valida a licença pela API pública."""

    def setUp(self):
        self.superadmin = User.objects.create_superuser("admin", "admin@example.com", "adminpass123")
        self.vendor = Vendor.objects.create(name="Fotos do Fe", created_by=self.superadmin)
        self.vendor_user = User.objects.create_user("vendedor1", password="vendorpass123", vendor=self.vendor)
        self.customer = Customer.objects.create(vendor=self.vendor, name="Casamento Ana e Joao")

    def test_superadmin_dashboard_lists_vendors(self):
        self.client.login(username="admin", password="adminpass123")
        resp = self.client.get(reverse("licensing:dashboard"))
        self.assertContains(resp, "Fotos do Fe")

    def test_vendor_cannot_see_superadmin_actions(self):
        self.client.login(username="vendedor1", password="vendorpass123")
        resp = self.client.get(reverse("licensing:dashboard"))
        self.assertContains(resp, "Casamento Ana e Joao")
        self.assertNotContains(resp, "Criar vendedor")

    def test_issue_license_and_mark_paid_activates_via_api(self):
        self.client.login(username="vendedor1", password="vendorpass123")
        resp = self.client.post(
            reverse("licensing:license-create", args=[self.customer.id]),
            {"plan_type": "month", "amount": "99.90"})
        self.assertEqual(resp.status_code, 302)

        license_ = License.objects.get(customer=self.customer)
        sale = Sale.objects.get(license=license_)
        self.assertEqual(sale.status, "pending")
        self.assertFalse(license_.is_activated)

        self.client.post(reverse("licensing:sale-mark-paid", args=[sale.id]))
        sale.refresh_from_db()
        self.assertEqual(sale.status, "paid")

        # Camera360 ativa numa máquina - API pública, sem login.
        resp = self.client.post(
            reverse("licensing:api-activate"),
            {"license_key": license_.license_key, "hardware_id": "HW-TEST-1"},
            content_type="application/json")
        data = resp.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["plan_type"], "month")

        # mesma máquina de novo -> ok (idempotente)
        resp = self.client.post(
            reverse("licensing:api-activate"),
            {"license_key": license_.license_key, "hardware_id": "HW-TEST-1"},
            content_type="application/json")
        self.assertTrue(resp.json()["valid"])

        # máquina diferente -> recusa
        resp = self.client.post(
            reverse("licensing:api-activate"),
            {"license_key": license_.license_key, "hardware_id": "HW-OUTRA"},
            content_type="application/json")
        self.assertFalse(resp.json()["valid"])

        # /validate com a máquina certa -> ok
        resp = self.client.post(
            reverse("licensing:api-validate"),
            {"license_key": license_.license_key, "hardware_id": "HW-TEST-1"},
            content_type="application/json")
        self.assertTrue(resp.json()["valid"])

    def test_validate_rejects_unknown_key(self):
        resp = self.client.post(
            reverse("licensing:api-validate"),
            {"license_key": "CAM3-0000-0000-0000", "hardware_id": "HW-X"},
            content_type="application/json")
        self.assertFalse(resp.json()["valid"])

    def test_revoked_license_fails_validation(self):
        license_ = License.objects.create(vendor=self.vendor, customer=self.customer, plan_type="lifetime")
        license_.activate("HW-REVOKE-TEST")
        license_.status = "revoked"
        license_.save()

        resp = self.client.post(
            reverse("licensing:api-validate"),
            {"license_key": license_.license_key, "hardware_id": "HW-REVOKE-TEST"},
            content_type="application/json")
        self.assertFalse(resp.json()["valid"])
