from django.contrib import admin

from .models import Customer, License, Sale, Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "email", "phone", "created_at")
    list_filter = ("vendor",)


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ("license_key", "customer", "vendor", "plan_type", "status", "expires_at", "hardware_id")
    list_filter = ("vendor", "plan_type", "status")
    search_fields = ("license_key", "customer__name", "hardware_id")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("id", "vendor", "customer", "plan_type", "amount", "method", "status", "created_at")
    list_filter = ("vendor", "method", "status")
