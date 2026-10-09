import secrets

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def generate_license_key():
    """Ex.: CAM3-A1B2-C3D4-E5F6 - fácil de digitar/ler em voz alta no
    suporte, colisão praticamente impossível pro volume desse negócio."""
    groups = ["".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(4))
              for _ in range(3)]
    return "CAM3-" + "-".join(groups)


PLAN_DURATIONS = {
    "day": relativedelta(days=1),
    "month": relativedelta(months=1),
    "year": relativedelta(years=1),
    # "lifetime" não entra aqui - de propósito, vitalícia nunca expira.
}

PLAN_CHOICES = [
    ("day", "Diária"),
    ("month", "Mensal"),
    ("year", "Anual"),
    ("lifetime", "Vitalícia"),
]

# O Camera360 é 2 em 1: a licença libera o Giro 360°, o Photobooth ou os dois.
MODULE_CHOICES = [
    ("360", "Giro 360°"),
    ("photobooth", "Photobooth"),
    ("both", "Giro 360° + Photobooth"),
]

# O que o app desktop recebe na API (ids de módulo do lado do app).
MODULE_FEATURES = {
    "360": ["video360"],
    "photobooth": ["photobooth"],
    "both": ["video360", "photobooth"],
}


class Vendor(models.Model):
    """Um revendedor com marca própria (logo/cor/nome) - vende e controla
    as licenças dos seus próprios clientes finais."""
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    logo = models.ImageField(upload_to="vendor_logos/", null=True, blank=True)
    primary_color = models.CharField(max_length=7, default="#00e0a0")
    is_active = models.BooleanField(default=True)
    # Módulos que esse vendedor comprou do super admin - e portanto os únicos
    # que ele pode licenciar pros clientes finais dele.
    sells_360 = models.BooleanField(default=True)
    sells_photobooth = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="vendors_created")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or "vendedor"
            slug = base_slug
            i = 1
            while Vendor.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                i += 1
                slug = f"{base_slug}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    def allowed_modules(self):
        """Valores de License.modules que esse vendedor pode emitir."""
        if self.sells_360 and self.sells_photobooth:
            return ["360", "photobooth", "both"]
        if self.sells_360:
            return ["360"]
        if self.sells_photobooth:
            return ["photobooth"]
        return []

    def module_choices(self):
        allowed = self.allowed_modules()
        return [(value, label) for value, label in MODULE_CHOICES if value in allowed]

    def resolve_module(self, requested):
        """Módulo a usar numa licença nova: o pedido, se permitido; sem
        pedido, 'both' (ou o único permitido). None se não pode emitir."""
        allowed = self.allowed_modules()
        if not allowed:
            return None
        if requested:
            return requested if requested in allowed else None
        return "both" if "both" in allowed else allowed[0]


class Customer(models.Model):
    """Cliente final de um vendedor - quem efetivamente roda o Camera360."""
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class License(models.Model):
    STATUS_CHOICES = [("active", "Ativa"), ("revoked", "Revogada")]

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="licenses")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="licenses")
    license_key = models.CharField(max_length=32, unique=True, default=generate_license_key)
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES)
    # default "both": licenças emitidas antes dos módulos existirem liberam tudo
    modules = models.CharField(max_length=10, choices=MODULE_CHOICES, default="both")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")

    hardware_id = models.CharField(max_length=128, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # null = ainda não ativada OU vitalícia
    last_validated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.license_key} ({self.customer.name})"

    @property
    def features(self):
        """Módulos liberados, como o app desktop os conhece."""
        return list(MODULE_FEATURES.get(self.modules, MODULE_FEATURES["both"]))

    @property
    def is_activated(self):
        return self.activated_at is not None

    @property
    def is_expired(self):
        if self.plan_type == "lifetime":
            return False
        if not self.is_activated:
            return False  # ainda não começou a contar
        return self.expires_at is not None and self.expires_at <= timezone.now()

    def is_valid(self):
        return self.status == "active" and not self.is_expired

    def activate(self, hardware_id):
        """Primeira ativação numa máquina: vincula o hardware_id e começa a
        contar o prazo do plano A PARTIR DE AGORA (não da data em que o
        vendedor emitiu a licença - assim o cliente não perde dias/meses só
        porque demorou pra instalar)."""
        now = timezone.now()
        self.hardware_id = hardware_id
        self.activated_at = now
        duration = PLAN_DURATIONS.get(self.plan_type)
        self.expires_at = (now + duration) if duration else None
        self.last_validated_at = now
        self.save()

    def renew(self, plan_type=None):
        """Estende a licença: soma a duração do plano ao prazo atual (se
        ainda não venceu) ou a partir de agora (se já tinha vencido) - assim
        uma renovação feita antes do vencimento não desperdiça o tempo que
        ainda restava."""
        plan_type = plan_type or self.plan_type
        self.plan_type = plan_type
        duration = PLAN_DURATIONS.get(plan_type)
        if duration is None:
            self.expires_at = None  # virou/é vitalícia
        else:
            now = timezone.now()
            base = self.expires_at if (self.expires_at and self.expires_at > now) else now
            self.expires_at = base + duration
        self.status = "active"
        self.save()


class Sale(models.Model):
    METHOD_CHOICES = [("manual", "Manual"), ("stripe", "Stripe")]
    STATUS_CHOICES = [("pending", "Pendente"), ("paid", "Paga"), ("canceled", "Cancelada")]

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="sales")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="sales")
    license = models.ForeignKey(License, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")

    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="BRL")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")

    stripe_checkout_session_id = models.CharField(max_length=255, blank=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Venda #{self.pk} - {self.customer.name} - {self.get_status_display()}"

    def mark_paid(self):
        """Confirma o pagamento e ativa/renova a licença vinculada -
        chamado tanto pelo fluxo manual (vendedor clica 'marcar como paga')
        quanto pelo webhook do Stripe."""
        if self.status == "paid":
            return  # já processada - webhook pode chegar duplicado
        self.status = "paid"
        self.paid_at = timezone.now()
        self.save()
        if self.license:
            if self.license.is_activated:
                self.license.renew(self.plan_type)
            else:
                self.license.plan_type = self.plan_type
                self.license.status = "active"
                self.license.save()
