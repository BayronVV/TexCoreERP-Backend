"""
Utilidades compartidas para filtros combinables, validación segura de parámetros y paginación
retrocompatible en los listados de TexCore ERP (HU 7.7 / TE-177).
"""
from datetime import date

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.users.models import CustomUser

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_LIMIT = 200

PAGINATION_PARAMS = [
    OpenApiParameter("page", int, description="Número de página (activa paginación estructurada)"),
    OpenApiParameter("page_size", int, description="Registros por página (1 a 200, por defecto 50)"),
]


def limited(queryset, request, *, default=100, maximum=MAX_LIMIT):
    """Compatibilidad con llamadas sin paginación explícita: recorta con `?limit=` (por defecto 100, máx 200)."""
    raw = request.query_params.get("limit", str(default))
    try:
        limit = min(max(int(raw), 1), maximum)
    except (TypeError, ValueError):
        limit = default
    return queryset[:limit]


def parse_date_param(params, key) -> date | None:
    """Valida una fecha ISO AAAA-MM-DD; responde 400 con mensaje claro si está mal formada."""
    raw = (params.get(key) or "").strip()
    if not raw:
        return None
    if len(raw) != 10:
        raise ValidationError({key: [f"La fecha '{key}' no es válida. Usa el formato AAAA-MM-DD."]})
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValidationError({key: [f"La fecha '{key}' no es válida. Usa el formato AAAA-MM-DD."]})


def parse_date_range(params, start_key="desde", end_key="hasta") -> tuple[date | None, date | None]:
    """Valida `desde` y `hasta` y exige que el rango no esté invertido."""
    start = parse_date_param(params, start_key)
    end = parse_date_param(params, end_key)
    if start and end and start > end:
        raise ValidationError({start_key: [f"La fecha '{start_key}' no puede ser posterior a la fecha '{end_key}'."]})
    return start, end


def parse_int_param(params, key, *, minimum=1, maximum=None) -> int | None:
    """Valida un parámetro entero positivo/en rango; responde 400 si es inválido."""
    raw = (params.get(key) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise ValidationError({key: [f"El filtro '{key}' debe ser un número entero válido."]})
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is not None:
            raise ValidationError({key: [f"El filtro '{key}' debe estar entre {minimum} y {maximum}."]})
        raise ValidationError({key: [f"El filtro '{key}' debe ser mayor o igual a {minimum}."]})
    return value


def user_search_q(prefix: str, text: str) -> Q:
    """Construye filtro de búsqueda textual sobre nombres, correo y usuario."""
    p = f"{prefix}__" if prefix else ""
    return (
        Q(**{f"{p}first_name__icontains": text})
        | Q(**{f"{p}last_name__icontains": text})
        | Q(**{f"{p}email__icontains": text})
        | Q(**{f"{p}username__icontains": text})
    )


def display_user_name(user) -> str:
    """Nombre legible de un usuario sin depender del serializer concreto."""
    if not user:
        return ""
    full = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return full or user.email or user.username or ""


def seller_options() -> list[dict]:
    """Opciones de vendedores activos (o con facturas) para filtros sin requerir `seguridad.ver`."""
    from apps.sales.models import FacturaVenta

    used_ids = list(FacturaVenta.objects.values_list("vendedor_id", flat=True).distinct())
    users = (
        CustomUser.objects.filter(
            Q(is_active=True, role_id__in=("VENDEDOR", "GERENTE", "ADMIN", "SECRETARIA"))
            | Q(id__in=used_ids)
        )
        .distinct()
        .order_by("first_name", "last_name", "email", "id")
    )
    return [
        {"id": u.id, "nombre": display_user_name(u), "email": u.email}
        for u in users
    ]


def wants_pagination(request) -> bool:
    """Indica si el cliente solicitó respuesta paginada estructurada."""
    params = request.query_params
    return (
        "page" in params
        or "page_size" in params
        or (params.get("paginado") or "").strip().lower() in ("1", "true")
    )


def paginate_or_limit(
    queryset,
    request,
    serializer_class,
    *,
    default_page_size=DEFAULT_PAGE_SIZE,
    max_page_size=MAX_PAGE_SIZE,
    serializer_context=None,
):
    """
    Si el cliente envía `?page=`, `?page_size=` o `?paginado=1`, devuelve respuesta paginada con conteo total:
    `{count, page, page_size, total_pages, next, previous, results}`.
    Si no, conserva el comportamiento histórico (`limit` sobre un arreglo JSON plano) para mantener
    retrocompatibilidad total con clientes y pruebas previas.
    """
    context = serializer_context or {}
    if not wants_pagination(request):
        items = list(limited(queryset, request))
        return Response(serializer_class(items, many=True, context=context).data)

    page = parse_int_param(request.query_params, "page", minimum=1) or 1
    page_size = (
        parse_int_param(request.query_params, "page_size", minimum=1, maximum=max_page_size)
        or default_page_size
    )
    total = queryset.count()
    total_pages = max(1, (total + page_size - 1) // page_size)
    offset = (page - 1) * page_size
    items = list(queryset[offset : offset + page_size])
    return Response({
        "count": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "next": page + 1 if page < total_pages else None,
        "previous": page - 1 if page > 1 else None,
        "results": serializer_class(items, many=True, context=context).data,
    })
