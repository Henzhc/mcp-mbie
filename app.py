"""ASGI entry point for Azure App Service."""

import hmac

from src.mcp_mbie.server import MCP_AUTH_TOKEN, mcp

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""

        if not hmac.compare_digest(token, MCP_AUTH_TOKEN):
            resp = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await resp(scope, receive, send)
            return

        await self.app(scope, receive, send)


app = mcp.streamable_http_app()

if MCP_AUTH_TOKEN:
    app.add_middleware(BearerAuthMiddleware)
