from django.urls import path

from . import api_views, views

app_name = "licensing"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("vendors/create/", views.vendor_create, name="vendor-create"),
    path("vendors/<int:vendor_id>/toggle/", views.vendor_toggle, name="vendor-toggle"),
    path("vendors/<int:vendor_id>/modules/", views.vendor_modules, name="vendor-modules"),

    path("customers/create/", views.customer_create, name="customer-create"),
    path("customers/<int:customer_id>/", views.customer_detail, name="customer-detail"),
    path("customers/<int:customer_id>/licenses/create/", views.license_create, name="license-create"),
    path("customers/<int:customer_id>/stripe-checkout/", views.stripe_checkout_create, name="stripe-checkout-create"),

    path("licenses/<int:license_id>/revoke/", views.license_revoke, name="license-revoke"),
    path("sales/<int:sale_id>/mark-paid/", views.sale_mark_paid, name="sale-mark-paid"),

    path("branding/", views.branding_settings, name="branding"),
]

api_urlpatterns = [
    path("license/activate", api_views.activate_license, name="api-activate"),
    path("license/validate", api_views.validate_license, name="api-validate"),
    path("stripe/webhook", views.stripe_webhook, name="stripe-webhook"),
]
