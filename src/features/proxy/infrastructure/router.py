"""Router catch-all: captura CUALQUIER método/path (menos /health, que es del
gateway mismo) y lo reenvía vía ReenviarRequest.
"""
from fastapi import APIRouter, Depends, Request, Response

from src.features.proxy.application.reenviar_request import ReenviarRequest
from src.features.proxy.domain.entities import RequestProxeada
from src.features.proxy.infrastructure.dependencies import get_reenviar_request

router = APIRouter()

_METODOS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


@router.api_route("/{full_path:path}", methods=_METODOS)
async def proxy_catch_all(
    full_path: str,
    request: Request,
    use_case: ReenviarRequest = Depends(get_reenviar_request),
) -> Response:
    body = await request.body()
    proxeada = RequestProxeada(
        method=request.method,
        path=f"/{full_path}",
        headers=dict(request.headers),
        query_string=request.url.query,
        body=body,
    )
    resultado = await use_case.execute(proxeada)
    return Response(
        content=resultado.body,
        status_code=resultado.status_code,
        headers=resultado.headers,
    )
