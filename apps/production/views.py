from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.references import fichas

from . import catalog, services
from .serializers import SimulacionInputSerializer, SimulacionSalidaSerializer


@extend_schema(
    tags=["produccion"], summary="Simular la producción de una referencia contra el stock (HU 4.1, TE-110)",
    request=SimulacionInputSerializer, responses=SimulacionSalidaSerializer,
    description="Verifica si hay material para fabricar N prendas antes de crear una orden. Devuelve `viable`, por material lo "
                "requerido, lo disponible y lo que falta, el **máximo producible** con el stock actual y su **cuello de "
                "botella**. Si se envían `lotes`, indica hasta qué lote alcanza el stock (acumulado, porque comparten el "
                "mismo material). Es solo lectura: no reserva ni descuenta stock, y la orden vuelve a verificarlo al crearse. "
                "La referencia debe estar activa y tener ficha técnica.",
)
class SimulacionView(APIView):
    # Es un POST porque lleva una lista de lotes, pero solo calcula: no escribe nada, así que basta con poder ver.
    required_permissions = {"POST": catalog.PRODUCTION_VIEW}

    def post(self, request):
        data = SimulacionInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        garments = fichas.parse_garments(data.validated_data["cantidad"])
        reference = services.get_reference(data.validated_data["referencia"])
        result = services.simulate(reference, garments, data.validated_data.get("lotes"))
        return Response(SimulacionSalidaSerializer(result).data)
