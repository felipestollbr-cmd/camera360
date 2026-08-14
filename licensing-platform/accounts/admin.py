from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "email", "vendor", "is_superuser", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("Vendedor", {"fields": ("vendor",)}),
    )
