def branding(request):
    """Disponibiliza a marca (nome/cor/logo) em todos os templates - o
    vendedor logado vê a própria marca; sem vendedor (super admin ou
    visitante) cai na marca padrão da plataforma."""
    vendor = getattr(getattr(request, "user", None), "vendor", None)
    if vendor:
        return {
            "brand_name": vendor.name,
            "brand_color": vendor.primary_color,
            "brand_logo": vendor.logo,
        }
    return {
        "brand_name": "Camera360",
        "brand_color": "#00e0a0",
        "brand_logo": None,
    }
