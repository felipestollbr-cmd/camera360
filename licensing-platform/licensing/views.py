from functools import wraps

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.csrf import csrf_exempt

from .models import Customer, License, PLAN_CHOICES, Sale, Vendor

User = get_user_model()
stripe.api_key = settings.STRIPE_SECRET_KEY


def vendor_required(view_func):
    """Só deixa passar usuários de vendedor (request.user.vendor setado) -
    super admin usa as próprias views (é dono de tudo, mas não 'é' um
    vendedor)."""
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if request.user.vendor_id is None:
            messages.error(request, "Essa área é só para vendedores.")
            return redirect("licensing:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


def superadmin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "Essa área é só para o super admin.")
            return redirect("licensing:dashboard")
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
def dashboard(request):
    if request.user.is_superuser:
        vendors = Vendor.objects.all().order_by("-created_at")
        return render(request, "licensing/superadmin_dashboard.html", {
            "vendors": vendors,
            "total_licenses": License.objects.count(),
            "total_customers": Customer.objects.count(),
        })

    vendor = request.user.vendor
    customers = vendor.customers.all().order_by("-created_at")
    licenses = License.objects.filter(vendor=vendor).select_related("customer").order_by("-created_at")
    sales = Sale.objects.filter(vendor=vendor).select_related("customer").order_by("-created_at")[:20]
    return render(request, "licensing/vendor_dashboard.html", {
        "vendor": vendor,
        "customers": customers,
        "licenses": licenses,
        "sales": sales,
        "plan_choices": PLAN_CHOICES,
    })


# --- super admin: gestão de vendedores -----------------------------------

@superadmin_required
def vendor_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()
        primary_color = request.POST.get("primary_color", "#00e0a0").strip()
        if not (name and username and password):
            messages.error(request, "Nome, usuário e senha são obrigatórios.")
            return redirect("licensing:dashboard")

        vendor = Vendor.objects.create(name=name, primary_color=primary_color, created_by=request.user)
        if request.FILES.get("logo"):
            vendor.logo = request.FILES["logo"]
            vendor.save()
        User.objects.create_user(username=username, password=password, vendor=vendor)
        messages.success(request, f"Vendedor '{name}' criado com o login '{username}'.")
    return redirect("licensing:dashboard")


@superadmin_required
def vendor_toggle(request, vendor_id):
    vendor = get_object_or_404(Vendor, id=vendor_id)
    vendor.is_active = not vendor.is_active
    vendor.save()
    return redirect("licensing:dashboard")


# --- vendedor: clientes ----------------------------------------------------

@vendor_required
def customer_create(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Dê um nome pro cliente.")
            return redirect("licensing:dashboard")
        Customer.objects.create(
            vendor=request.user.vendor, name=name,
            email=request.POST.get("email", "").strip(),
            phone=request.POST.get("phone", "").strip(),
            notes=request.POST.get("notes", "").strip(),
        )
        messages.success(request, f"Cliente '{name}' criado.")
    return redirect("licensing:dashboard")


@vendor_required
def customer_detail(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id, vendor=request.user.vendor)
    licenses = customer.licenses.all().order_by("-created_at")
    sales = customer.sales.all().order_by("-created_at")
    return render(request, "licensing/customer_detail.html", {
        "customer": customer, "licenses": licenses, "sales": sales,
        "plan_choices": PLAN_CHOICES,
    })


# --- vendedor: licenças/vendas ----------------------------------------------

@vendor_required
def license_create(request, customer_id):
    customer = get_object_or_404(Customer, id=customer_id, vendor=request.user.vendor)
    if request.method == "POST":
        plan_type = request.POST.get("plan_type")
        amount = request.POST.get("amount") or "0"
        license_ = License.objects.create(vendor=request.user.vendor, customer=customer, plan_type=plan_type)
        Sale.objects.create(
            vendor=request.user.vendor, customer=customer, license=license_,
            plan_type=plan_type, amount=amount, method="manual", status="pending",
        )
        messages.success(request, f"Licença {license_.license_key} criada - marque a venda como paga quando receber.")
    return redirect("licensing:customer-detail", customer_id=customer.id)


@vendor_required
def license_revoke(request, license_id):
    license_ = get_object_or_404(License, id=license_id, vendor=request.user.vendor)
    license_.status = "revoked"
    license_.save()
    messages.success(request, f"Licença {license_.license_key} revogada.")
    return redirect("licensing:customer-detail", customer_id=license_.customer_id)


@vendor_required
def sale_mark_paid(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id, vendor=request.user.vendor)
    sale.mark_paid()
    messages.success(request, "Venda marcada como paga - licença ativa/renovada.")
    return redirect("licensing:customer-detail", customer_id=sale.customer_id)


# --- vendedor: marca (branding) ---------------------------------------------

@vendor_required
def branding_settings(request):
    vendor = request.user.vendor
    if request.method == "POST":
        vendor.name = request.POST.get("name", vendor.name).strip()
        vendor.primary_color = request.POST.get("primary_color", vendor.primary_color).strip()
        if request.FILES.get("logo"):
            vendor.logo = request.FILES["logo"]
        vendor.save()
        messages.success(request, "Marca atualizada.")
        return redirect("licensing:dashboard")
    return render(request, "licensing/branding_settings.html", {"vendor": vendor})


# --- Stripe: cobrança automática ---------------------------------------

@vendor_required
def stripe_checkout_create(request, customer_id):
    """Emite a licença (ainda não ativada) + uma venda pendente vinculada a
    uma Stripe Checkout Session - o link gerado pode ser enviado pro
    cliente final pagar. O webhook (stripe_webhook abaixo) confirma o
    pagamento e ativa a venda; a licença só é ativada de verdade quando o
    Camera360 chamar /api/v1/license/activate na máquina do cliente."""
    customer = get_object_or_404(Customer, id=customer_id, vendor=request.user.vendor)
    if request.method != "POST":
        return redirect("licensing:customer-detail", customer_id=customer.id)

    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Stripe não configurado nesta instalação (falta STRIPE_SECRET_KEY).")
        return redirect("licensing:customer-detail", customer_id=customer.id)

    plan_type = request.POST.get("plan_type")
    amount = request.POST.get("amount") or "0"

    license_ = License.objects.create(vendor=request.user.vendor, customer=customer, plan_type=plan_type)
    sale = Sale.objects.create(
        vendor=request.user.vendor, customer=customer, license=license_,
        plan_type=plan_type, amount=amount, method="stripe", status="pending",
    )

    detail_url = f"{settings.SITE_BASE_URL}{reverse('licensing:customer-detail', args=[customer.id])}"
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "brl",
                    "unit_amount": int(float(amount) * 100),
                    "product_data": {
                        "name": f"Camera360 - Licença {license_.get_plan_type_display()} - {customer.name}"},
                },
                "quantity": 1,
            }],
            success_url=f"{detail_url}?checkout=success",
            cancel_url=f"{detail_url}?checkout=canceled",
            metadata={"sale_id": str(sale.id)},
        )
    except Exception as e:
        license_.delete()  # sem cobrança criada, não faz sentido manter a licença pendurada
        messages.error(request, f"Falha ao criar cobrança no Stripe: {e}")
        return redirect("licensing:customer-detail", customer_id=customer.id)

    sale.stripe_checkout_session_id = session.id
    sale.save(update_fields=["stripe_checkout_session_id"])

    messages.success(request, mark_safe(
        f"Licença {license_.license_key} criada. Link de pagamento: "
        f'<a href="{session.url}" target="_blank" rel="noopener">{session.url}</a>'))
    return redirect("licensing:customer-detail", customer_id=customer.id)


@csrf_exempt
def stripe_webhook(request):
    """Endpoint público (sem login - o Stripe chama de fora) que confirma
    pagamentos de Checkout Sessions e ativa/renova a venda correspondente.
    A assinatura garante que só o Stripe consegue disparar isso de verdade."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=503)

    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        # StripeObject não tem .get() (só __getitem__/atributo, levanta
        # erro se a chave não existir) - to_dict() vira dict de verdade,
        # recursivamente, e aí .get() com default funciona normalmente.
        session = event["data"]["object"].to_dict()
        sale_id = (session.get("metadata") or {}).get("sale_id")
        if sale_id:
            try:
                Sale.objects.get(id=sale_id).mark_paid()
            except Sale.DoesNotExist:
                pass

    return HttpResponse(status=200)
