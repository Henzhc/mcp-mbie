"""MCP server for the NZBN (New Zealand Business Number) API v5.

Exposes read-only tools for searching and inspecting NZ business entities
via the government NZBN register.

Supports two transports:
- **stdio**  (default) — local, single-user.
- **streamable-http** — remote, multi-user.  Set ``MCP_TRANSPORT=streamable-http``
  and optionally ``MCP_AUTH_TOKEN`` for bearer-token auth.
"""

import json
import os
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NZBN_API_BASE_URL = os.getenv(
    "NZBN_API_BASE_URL",
    "https://api.business.govt.nz/gateway/nzbn/v5",
).rstrip("/")

COMPANIES_ROLE_API_BASE_URL = os.getenv(
    "COMPANIES_ROLE_API_BASE_URL",
    "https://api.business.govt.nz/gateway/companies-office/companies-register/entity-roles/v3",
).rstrip("/")

NZBN_API_KEY = os.getenv("NZBN_API_KEY", "").strip()
COMPANIES_ROLE_API_KEY = os.getenv("COMPANIES_ROLE_API_KEY", "").strip() 

TIMEOUT = float(os.getenv("NZBN_TIMEOUT", "30"))

# Transport config — set MCP_TRANSPORT=streamable-http to expose over HTTP
MCP_TRANSPORT: Literal["stdio", "streamable-http"] = os.getenv(
    "MCP_TRANSPORT", "stdio"
)  # type: ignore[assignment]
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

# Optional bearer-token auth for HTTP transport
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "").strip()

# ---------------------------------------------------------------------------
# MCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "nzbn",
    host=MCP_HOST,
    port=MCP_PORT,
)

# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------

_NZBN_PATTERN = r"^\d{13}$"

_READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}


def _headers() -> dict[str, str]:
    return {
        "Ocp-Apim-Subscription-Key": NZBN_API_KEY,
        "Accept": "application/json",
    }


def _handle_error(e: Exception) -> str:
    """Convert exceptions into user-friendly error strings."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        body = e.response.text or ""
        messages = {
            400: f"Bad request (400). {body}",
            401: "Unauthorised (401). Check NZBN_API_KEY.",
            403: "Forbidden (403). Your subscription may lack access.",
            404: "Not found (404). Verify the NZBN is correct.",
            429: "Rate-limited (429). Wait before retrying.",
        }
        return f"Error: {messages.get(status, f'HTTP {status}. {body}')}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Try again."
    return f"Error: {type(e).__name__}: {e}"


async def _get(path: str, params: Optional[dict] = None) -> str:
    """Perform a GET request against the NZBN API and return JSON text."""
    url = f"{NZBN_API_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=_headers(), params=params)
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return _handle_error(e)


def _companies_role_headers() -> dict[str, str]:
    return {
        "Ocp-Apim-Subscription-Key": COMPANIES_ROLE_API_KEY,
        "Accept": "application/json",
    }


async def _get_companies_role(path: str, params: Optional[dict] = None) -> str:
    """Perform a GET request against the Companies Entity Role Search API."""
    url = f"{COMPANIES_ROLE_API_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers=_companies_role_headers(), params=params)
            resp.raise_for_status()
            return json.dumps(resp.json(), indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class SearchEntitiesInput(BaseModel):
    """Input for searching businesses by name."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    search_term: str = Field(
        ...,
        description="Free-text search across entity names, trading names, NZBN, and legacy numbers.",
        min_length=1,
    )
    entity_status: Optional[str] = Field(
        None,
        description=(
            "Filter by status. One or more of: Registered, VoluntaryAdministration, "
            "InReceivership, InLiquidation, InStatutoryAdministration, Inactive, RemovedClosed"
        ),
    )
    entity_type: Optional[str] = Field(
        None,
        description=(
            "Filter by entity type. E.g. NZCompany, OverseasCompany, SoleTrader, "
            "Partnership, Trust, LTD, COOP, etc."
        ),
    )
    page: int = Field(0, description="Zero-indexed page number.", ge=0)
    page_size: int = Field(25, description="Results per page (max 50).", ge=1, le=50)


class NzbnInput(BaseModel):
    """Input requiring a single NZBN."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    nzbn: str = Field(
        ...,
        description="13-digit New Zealand Business Number.",
        min_length=13,
        max_length=13,
        pattern=_NZBN_PATTERN,
    )


class GetAddressesInput(NzbnInput):
    """Input for retrieving entity addresses."""

    address_type: Optional[str] = Field(
        None,
        description="Filter by address type (e.g. 'registered', 'service').",
    )


class GetFilingsInput(NzbnInput):
    """Input for retrieving entity filings."""

    page: int = Field(0, ge=0, description="Zero-indexed page number.")
    page_size: int = Field(25, ge=1, le=50, description="Results per page.")


class SearchEntityRolesInput(BaseModel):
    """Input for searching directors/shareholders across the Companies Register."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(
        ...,
        description="Name of the person or entity to search for (min 2 characters). Case-insensitive.",
        min_length=2,
    )
    role_type: Literal["DIR", "SHR", "ALL"] = Field(
        "DIR",
        description="Role type to search: DIR (director), SHR (shareholder), or ALL (both).",
    )
    registered_only: bool = Field(
        False,
        description="If true, only return roles in currently registered companies.",
    )
    page: int = Field(0, ge=0, description="Zero-indexed page number.")
    page_size: int = Field(10, ge=1, le=50, description="Results per page (default 10).")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(name="search_entities", annotations=_READ_ONLY_ANNOTATIONS)
async def search_entities(params: SearchEntitiesInput) -> str:
    """Search the NZBN register for businesses by name, NZBN, or legacy number.

    Returns a paginated list of matching entities sorted by relevance.
    """
    query: dict[str, str | int] = {"search-term": params.search_term}
    if params.entity_status:
        query["entity-status"] = params.entity_status
    if params.entity_type:
        query["entity-type"] = params.entity_type
    query["page"] = params.page
    query["page-size"] = params.page_size
    return await _get("/entities", params=query)


@mcp.tool(name="get_entity", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity(params: NzbnInput) -> str:
    """Retrieve full details for a NZ business by its 13-digit NZBN.

    Returns legal name, trading names, entity type, status, addresses,
    directors, shareholders, and other registration details.
    """
    return await _get(f"/entities/{params.nzbn}")


@mcp.tool(name="get_entity_addresses", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_addresses(params: GetAddressesInput) -> str:
    """Get the registered and service addresses for an entity."""
    query = {}
    if params.address_type:
        query["address-type"] = params.address_type
    return await _get(f"/entities/{params.nzbn}/addresses", params=query or None)


@mcp.tool(name="get_entity_roles", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_roles(params: NzbnInput) -> str:
    """Get directors, shareholders, and other roles for an entity."""
    return await _get(f"/entities/{params.nzbn}/roles")


@mcp.tool(name="get_company_details", annotations=_READ_ONLY_ANNOTATIONS)
async def get_company_details(params: NzbnInput) -> str:
    """Get Companies Office details (annual return filing month, constitution, etc.)."""
    return await _get(f"/entities/{params.nzbn}/company-details")


@mcp.tool(name="get_entity_filings", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_filings(params: GetFilingsInput) -> str:
    """Get the filings (annual returns, etc.) associated with an entity."""
    query: dict[str, int] = {"page": params.page, "page-size": params.page_size}
    return await _get(f"/entities/{params.nzbn}/filings", params=query)


@mcp.tool(name="get_entity_phone_numbers", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_phone_numbers(params: NzbnInput) -> str:
    """Get the phone numbers for an entity."""
    return await _get(f"/entities/{params.nzbn}/phone-numbers")


@mcp.tool(name="get_entity_email_addresses", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_email_addresses(params: NzbnInput) -> str:
    """Get the email addresses for an entity."""
    return await _get(f"/entities/{params.nzbn}/email-addresses")


@mcp.tool(name="get_entity_websites", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_websites(params: NzbnInput) -> str:
    """Get the websites for an entity."""
    return await _get(f"/entities/{params.nzbn}/websites")


@mcp.tool(name="get_entity_history", annotations=_READ_ONLY_ANNOTATIONS)
async def get_entity_history(params: NzbnInput) -> str:
    """Get the full change history for an entity (name changes, status changes, etc.)."""
    return await _get(f"/entities/{params.nzbn}/history")


# ---------------------------------------------------------------------------
# Companies Entity Role Search tools
# ---------------------------------------------------------------------------


@mcp.tool(name="search_entity_roles", annotations=_READ_ONLY_ANNOTATIONS)
async def search_entity_roles(params: SearchEntityRolesInput) -> str:
    """Search the NZ Companies Register for directors and shareholders by name.

    Find which companies a person or entity holds roles in. Useful for
    discovering all directorships or shareholdings associated with a name.
    Note: for shareholders with multiple allocations in a company, only
    the first allocation is returned.
    """
    query: dict[str, str | int | bool] = {
        "name": params.name,
        "role-type": params.role_type,
    }
    if params.registered_only:
        query["registered-only"] = params.registered_only
    query["page"] = params.page
    query["page-size"] = params.page_size
    return await _get_companies_role("/search", params=query)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server using the configured transport.

    When running with streamable-http and MCP_AUTH_TOKEN is set, requests
    must include ``Authorization: Bearer <token>`` or they get a 401.
    """
    if MCP_TRANSPORT == "stdio" or not MCP_AUTH_TOKEN:
        mcp.run(transport=MCP_TRANSPORT)
        return

    # Wrap the Starlette app with bearer-token auth middleware
    import hmac

    import uvicorn
    from starlette.middleware import Middleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    class BearerAuthMiddleware:
        """Reject requests that don't carry a valid bearer token."""

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            request = Request(scope)
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
            else:
                token = ""

            if not hmac.compare_digest(token, MCP_AUTH_TOKEN):
                resp = JSONResponse(
                    {"error": "Unauthorized"}, status_code=401
                )
                await resp(scope, receive, send)
                return

            await self.app(scope, receive, send)

    starlette_app = mcp.streamable_http_app()
    starlette_app.add_middleware(BearerAuthMiddleware)

    config = uvicorn.Config(
        starlette_app,
        host=MCP_HOST,
        port=MCP_PORT,
        log_level="info",
    )
    import anyio
    anyio.run(uvicorn.Server(config).serve)
