"""Servidor MCP por HTTP (Streamable HTTP) con token secreto en la ruta: https://host/<token>/mcp"""
from __future__ import annotations

import hmac

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import Empresa


def construir_mcp(emp: Empresa) -> FastMCP:
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*"]
    if emp.public_host:
        hosts += [emp.public_host, f"{emp.public_host}:*"]
        origins += [f"https://{emp.public_host}"]
    mcp = FastMCP(
        f"microsip-{emp.id}",
        instructions=(
            f"Analitica de {emp.nombre} sobre Microsip (solo lectura, copia nocturna). "
            "Llama primero a `diccionario` para conocer reglas y esquema; usa `sql` solo si ninguna otra herramienta alcanza."
        ),
        host=emp.host,
        port=emp.port,
        stateless_http=True,       # sin sesiones en memoria: el servidor puede reiniciarse sin romper al cliente
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
        ),
    )
    if emp.perfil == "ruta":
        from . import tools_ruta
        tools_ruta.registrar(mcp, emp)
    else:
        raise ValueError(f"Perfil no soportado todavia: {emp.perfil!r} (dtodo llega con el codigo original)")
    return mcp


class TokenEnRuta:
    """Middleware ASGI: solo atiende /<token>/... y le quita el prefijo. /health responde sin token."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    async def _responder(self, send, status: int, cuerpo: bytes = b""):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body", "body": cuerpo})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] != "http":
            return
        path: str = scope["path"]
        if path == "/health":
            return await self._responder(send, 200, b"ok")
        partes = path.split("/", 2)                      # ['', '<token>', 'mcp...']
        if len(partes) >= 2 and hmac.compare_digest(partes[1].encode(), self.token):
            resto = "/" + (partes[2] if len(partes) > 2 else "")
            nuevo = dict(scope, path=resto, raw_path=resto.encode())
            return await self.app(nuevo, receive, send)
        return await self._responder(send, 404, b"not found")


def construir_app(emp: Empresa):
    return TokenEnRuta(construir_mcp(emp).streamable_http_app(), emp.token)
