"""
API pública consumida pelo Camera360 desktop (license_client.py) pra
ativar/validar a licença. Autenticada pela própria license_key - não exige
login (o cliente final nunca acessa esse painel web).
"""
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import License


def _license_payload(license_, message, valid=None):
    """valid=None deriva de license_.is_valid() (estado geral da licença) -
    mas quando o motivo da recusa é específico do request (ex.: hardware_id
    não bate com o vinculado), o valor tem que vir explícito: is_valid()
    sozinho não sabe nada sobre qual máquina está perguntando."""
    return {
        "valid": license_.is_valid() if valid is None else valid,
        "plan_type": license_.plan_type,
        "module": license_.modules,
        "modules": license_.features,
        "status": license_.status,
        "activated": license_.is_activated,
        "expires_at": license_.expires_at.isoformat() if license_.expires_at else None,
        "message": message,
    }


@api_view(["POST"])
def activate_license(request):
    license_key = (request.data.get("license_key") or "").strip().upper()
    hardware_id = (request.data.get("hardware_id") or "").strip()
    if not license_key or not hardware_id:
        return Response({"valid": False, "message": "license_key e hardware_id são obrigatórios"}, status=400)

    try:
        license_ = License.objects.select_related("vendor").get(license_key=license_key)
    except License.DoesNotExist:
        return Response({"valid": False, "message": "Licença não encontrada"}, status=404)

    if license_.status != "active":
        return Response(_license_payload(license_, "Licença revogada", valid=False), status=403)

    if license_.is_activated:
        if license_.hardware_id != hardware_id:
            return Response(
                _license_payload(license_, "Licença já ativada em outra máquina", valid=False), status=403)
        # Reativação na mesma máquina (reinstalou o app etc.) - idempotente.
        return Response(_license_payload(license_, "Licença já estava ativa nesta máquina", valid=True))

    license_.activate(hardware_id)
    return Response(_license_payload(license_, "Licença ativada com sucesso"))


@api_view(["POST"])
def validate_license(request):
    license_key = (request.data.get("license_key") or "").strip().upper()
    hardware_id = (request.data.get("hardware_id") or "").strip()
    if not license_key or not hardware_id:
        return Response({"valid": False, "message": "license_key e hardware_id são obrigatórios"}, status=400)

    try:
        license_ = License.objects.select_related("vendor").get(license_key=license_key)
    except License.DoesNotExist:
        return Response({"valid": False, "message": "Licença não encontrada"}, status=404)

    if not license_.is_activated:
        return Response(_license_payload(license_, "Licença ainda não ativada", valid=False), status=403)

    if license_.hardware_id != hardware_id:
        return Response(_license_payload(license_, "Licença vinculada a outra máquina", valid=False), status=403)

    if not license_.is_valid():
        reason = "Licença revogada" if license_.status != "active" else "Licença expirada"
        return Response(_license_payload(license_, reason, valid=False), status=403)

    license_.last_validated_at = timezone.now()
    license_.save(update_fields=["last_validated_at"])
    return Response(_license_payload(license_, "Licença válida", valid=True))
