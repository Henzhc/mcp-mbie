"""MCP server for MBIE business register APIs.

Exposes read-only tools for searching and inspecting NZ business entities
via the NZBN register and Companies Office entity roles API.

Supports two transports:
- **stdio**  (default) — local, single-user.
- **streamable-http** — remote, multi-user.  Set ``MCP_TRANSPORT=streamable-http``
  and optionally ``MCP_AUTH_TOKEN`` for bearer-token auth.
"""

import json
import os
from pathlib import Path
from typing import Annotated, Literal, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field

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
    "mbie",
    host=MCP_HOST,
    port=MCP_PORT,
    instructions=(
        "Read-only access to the NZ business registers (NZBN and Companies Office). "
        "Typical flows: (1) company lookup — search_entities to find the 13-digit NZBN, "
        "then get_entity for the full record; (2) person lookup — search_entity_roles to "
        "find all companies a person is a director or shareholder of, then get_entity on "
        "companies of interest. get_entity returns the complete record (roles, addresses, "
        "trading names, GST numbers, industry classifications); the narrower get_* tools "
        "return single sections when the full record is not needed."
    ),
)

# ---------------------------------------------------------------------------
# Shared HTTP helpers
# ---------------------------------------------------------------------------

Nzbn = Annotated[
    str,
    Field(
        description="13-digit New Zealand Business Number.",
        pattern=r"^\d{13}$",
    ),
]

_ENTITY_TYPE_VALUES = (
    "NZCompany, OverseasCompany, SoleTrader, Partnership, Trust, BuildingSociety, "
    "CharitableTrust, CreditUnion, FriendlySociety, IncorporatedSociety, "
    "IndustrialAndProvidentSociety, LimitedPartnershipNz, LimitedPartnershipOverseas, "
    "SpecialBody, Trading_Trust, GovtCentral, GovtEdu, GovtLocal, GovtOther"
)


def _annotations(title: str) -> dict:
    return {
        "title": title,
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }


def _strip_nulls(obj):
    """Recursively drop null values — NZBN payloads are ~50% nulls."""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(v) for v in obj]
    return obj


def _handle_error(e: Exception, key_env: str) -> str:
    """Convert exceptions into user-friendly error strings."""
    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        body = e.response.text or ""
        messages = {
            400: f"Bad request (400). {body}",
            401: f"Unauthorised (401). Check {key_env}.",
            403: f"Forbidden (403). Your {key_env} subscription may lack access to this endpoint.",
            404: "Not found (404). Verify the NZBN is correct.",
            429: "Rate-limited (429). Wait before retrying.",
        }
        return f"Error: {messages.get(status, f'HTTP {status}. {body}')}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out. Try again."
    return f"Error: {type(e).__name__}: {e}"


async def _api_get(
    base_url: str, path: str, api_key: str, key_env: str, params: Optional[dict] = None
) -> str:
    """GET against an MBIE API; return compact JSON text with nulls stripped."""
    headers = {"Ocp-Apim-Subscription-Key": api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{base_url}{path}", headers=headers, params=params)
            resp.raise_for_status()
            return json.dumps(_strip_nulls(resp.json()))
    except Exception as e:
        return _handle_error(e, key_env)


async def _get(path: str, params: Optional[dict] = None) -> str:
    return await _api_get(NZBN_API_BASE_URL, path, NZBN_API_KEY, "NZBN_API_KEY", params)


async def _get_companies_role(path: str, params: Optional[dict] = None) -> str:
    return await _api_get(
        COMPANIES_ROLE_API_BASE_URL,
        path,
        COMPANIES_ROLE_API_KEY,
        "COMPANIES_ROLE_API_KEY",
        params,
    )


def _csv_list(value: str) -> list[str]:
    """Split a comma-separated filter into values for repeated query params."""
    return [v.strip() for v in value.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# NZBN register tools
# ---------------------------------------------------------------------------


@mcp.tool(name="search_entities", annotations=_annotations("Search NZBN register"))
async def search_entities(
    search_term: Annotated[
        str,
        Field(
            description=(
                "Free-text search matching entity names, trading names, NZBN, "
                "and legacy identifiers (e.g. company number)."
            ),
            min_length=1,
        ),
    ],
    entity_status: Annotated[
        Optional[str],
        Field(
            description=(
                "Filter by status; comma-separate for multiple. Values: Registered, "
                "VoluntaryAdministration, InReceivership, InLiquidation, "
                "InStatutoryAdministration, Inactive, RemovedClosed."
            ),
        ),
    ] = None,
    entity_type: Annotated[
        Optional[str],
        Field(
            description=(
                "Filter by entity type; comma-separate for multiple. Values: "
                f"{_ENTITY_TYPE_VALUES}."
            ),
        ),
    ] = None,
    industry_code: Annotated[
        Optional[str],
        Field(
            description=(
                "Filter by industry classification (BIC) code, "
                "e.g. I490008. See classificationCode values returned by "
                "get_entity_industry_classifications."
            ),
        ),
    ] = None,
    page: Annotated[int, Field(description="Zero-indexed page number.", ge=0)] = 0,
    page_size: Annotated[
        int, Field(description="Results per page (max 50).", ge=1, le=50)
    ] = 25,
) -> str:
    """Search the NZBN register for businesses by name, NZBN, or legacy number.

    Returns a paginated list of matching entities sorted by relevance. Use the
    returned 13-digit NZBN with get_entity for the full record. To find
    companies associated with a *person*, use search_entity_roles instead.
    """
    query: dict = {"search-term": search_term, "page": page, "page-size": page_size}
    if entity_status:
        query["entity-status"] = _csv_list(entity_status)
    if entity_type:
        query["entity-type"] = _csv_list(entity_type)
    if industry_code:
        query["industry-code"] = industry_code
    return await _get("/entities", params=query)


@mcp.tool(name="get_entity", annotations=_annotations("Get entity (full record)"))
async def get_entity(nzbn: Nzbn) -> str:
    """Retrieve the complete record for a NZ business by its 13-digit NZBN.

    Returns legal name, entity type and status, trading names, addresses,
    roles (directors and shareholders), GST numbers, industry classifications,
    and other registration details in one call — usually the only call needed
    after search_entities. The narrower get_entity_* tools return single
    sections of this record with smaller responses.
    """
    return await _get(f"/entities/{nzbn}")


@mcp.tool(name="get_entity_addresses", annotations=_annotations("Get entity addresses"))
async def get_entity_addresses(
    nzbn: Nzbn,
    address_type: Annotated[
        Literal["REGISTERED", "POSTAL", "SERVICE", "OFFICE", "DELIVERY", "INVOICE"],
        Field(
            description=(
                "Address type to return (the API requires exactly one, uppercase). "
                "For all addresses at once, use get_entity instead."
            ),
        ),
    ] = "REGISTERED",
) -> str:
    """Get addresses of one type for an entity.

    The API requires a single address type per call (REGISTERED, POSTAL,
    SERVICE, OFFICE, DELIVERY, or INVOICE). get_entity returns all address
    types in one call.
    """
    return await _get(f"/entities/{nzbn}/addresses", params={"address-type": address_type})


@mcp.tool(name="get_entity_roles", annotations=_annotations("Get entity roles"))
async def get_entity_roles(nzbn: Nzbn) -> str:
    """Get directors, shareholders, and other roles for a known entity (company → people).

    To search the other direction — find which companies a person holds roles
    in by their name — use search_entity_roles instead.
    """
    return await _get(f"/entities/{nzbn}/roles")


@mcp.tool(name="get_company_details", annotations=_annotations("Get company details (NZ companies)"))
async def get_company_details(nzbn: Nzbn) -> str:
    """Get Companies Office details for an NZ company (annual return filing month,
    constitution filed, NZSX code, country of origin, etc.).

    Only valid for entities of type NZCompany — returns a 400 error for other
    entity types. For limited partnerships, charitable trusts, incorporated
    societies and other non-company types, use get_entity_non_company_details.
    """
    return await _get(f"/entities/{nzbn}/company-details")


@mcp.tool(
    name="get_entity_non_company_details",
    annotations=_annotations("Get non-company details"),
)
async def get_entity_non_company_details(nzbn: Nzbn) -> str:
    """Get register details for a non-company entity (limited partnerships,
    charitable trusts, incorporated societies, etc.) — annual return filing
    month, charities number, balance date, registered union status.

    Only valid for non-company entity types — returns a 400 error for
    NZCompany entities (use get_company_details for those).
    """
    return await _get(f"/entities/{nzbn}/non-company-details")


@mcp.tool(name="get_entity_filings", annotations=_annotations("Get entity filings"))
async def get_entity_filings(nzbn: Nzbn) -> str:
    """Get all filings for an entity (annual returns, address changes,
    director changes, etc.), including links to filed documents.

    Returns the complete filing list in one response — the API does not
    paginate this endpoint.
    """
    return await _get(f"/entities/{nzbn}/filings")


@mcp.tool(name="get_entity_phone_numbers", annotations=_annotations("Get entity phone numbers"))
async def get_entity_phone_numbers(nzbn: Nzbn) -> str:
    """Get the phone numbers for an entity."""
    return await _get(f"/entities/{nzbn}/phone-numbers")


@mcp.tool(name="get_entity_email_addresses", annotations=_annotations("Get entity email addresses"))
async def get_entity_email_addresses(nzbn: Nzbn) -> str:
    """Get the email addresses for an entity."""
    return await _get(f"/entities/{nzbn}/email-addresses")


@mcp.tool(name="get_entity_websites", annotations=_annotations("Get entity websites"))
async def get_entity_websites(nzbn: Nzbn) -> str:
    """Get the websites for an entity."""
    return await _get(f"/entities/{nzbn}/websites")


@mcp.tool(name="get_entity_gst_numbers", annotations=_annotations("Get entity GST numbers"))
async def get_entity_gst_numbers(nzbn: Nzbn) -> str:
    """Get the GST numbers registered for an entity.

    An empty list means no GST number is published on the register, not
    necessarily that the entity is unregistered for GST.
    """
    return await _get(f"/entities/{nzbn}/gst-numbers")


@mcp.tool(
    name="get_entity_industry_classifications",
    annotations=_annotations("Get entity industry classifications"),
)
async def get_entity_industry_classifications(nzbn: Nzbn) -> str:
    """Get the industry classifications (BIC codes and descriptions) for an entity.

    The returned classificationCode values can be used as the industry_code
    filter in search_entities to find similar businesses.
    """
    return await _get(f"/entities/{nzbn}/industry-classifications")


@mcp.tool(name="get_entity_trading_areas", annotations=_annotations("Get entity trading areas"))
async def get_entity_trading_areas(nzbn: Nzbn) -> str:
    """Get the geographic trading areas declared for an entity
    (e.g. 'All of New Zealand', specific regions)."""
    return await _get(f"/entities/{nzbn}/trading-areas")


@mcp.tool(name="get_entity_history", annotations=_annotations("Get entity change history"))
async def get_entity_history(nzbn: Nzbn) -> str:
    """Get the full change history for an entity (name changes, status changes,
    address changes, etc.)."""
    return await _get(f"/entities/{nzbn}/history")


# ---------------------------------------------------------------------------
# Companies Entity Role Search tools
# ---------------------------------------------------------------------------


@mcp.tool(name="search_entity_roles", annotations=_annotations("Search roles by person name"))
async def search_entity_roles(
    name: Annotated[
        str,
        Field(
            description=(
                "Name of the person or organisation to search for (min 2 characters). "
                "Case-insensitive substring match — matches the name anywhere within "
                "the registered name."
            ),
            min_length=2,
        ),
    ],
    role_type: Annotated[
        Literal["DIR", "SHR", "ALL"],
        Field(description="Role type: DIR (director), SHR (shareholder), or ALL (both)."),
    ] = "DIR",
    registered_only: Annotated[
        bool,
        Field(
            description=(
                "If true, only return people with an active role in at least one "
                "currently registered company. If false (default), results include "
                "historic roles and removed companies."
            ),
        ),
    ] = False,
    page: Annotated[int, Field(description="Zero-indexed page number.", ge=0)] = 0,
    page_size: Annotated[
        int, Field(description="Results per page (default 10, max 50).", ge=1, le=50)
    ] = 10,
) -> str:
    """Search the NZ Companies Register for directors and shareholders by name
    (person → companies).

    Finds all companies a person or entity holds roles in — the reverse
    direction of get_entity_roles. Results include historic roles and removed
    companies unless registered_only is set, so check each company's status
    before treating a role as current. Note: for shareholders with multiple
    allocations in a company, only the first allocation is returned.
    """
    query: dict = {
        "name": name,
        "role-type": role_type,
        "page": page,
        "page-size": page_size,
    }
    if registered_only:
        query["registered-only"] = registered_only
    return await _get_companies_role("/search", params=query)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the MCP server using the configured transport.

    When running with streamable-http and MCP_AUTH_TOKEN is set, requests
    must authenticate via either ``Authorization: Bearer <token>`` or a
    ``?token=<token>`` query parameter, otherwise they get a 401.
    """
    if MCP_TRANSPORT == "stdio" or not MCP_AUTH_TOKEN:
        mcp.run(transport=MCP_TRANSPORT)
        return

    # Wrap the Starlette app with bearer-token auth middleware
    import hmac

    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    class BearerAuthMiddleware:
        """Reject requests that don't carry a valid token.

        Accepts the token via ``Authorization: Bearer <token>`` header or
        ``?token=<token>`` query param — the latter lets users paste a single
        URL into Claude Desktop's custom-connector dialog without a separate
        header config step.
        """

        def __init__(self, app: ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            path = scope.get("path", "")
            if path.startswith("/.well-known/") or path == "/register":
                # OAuth discovery probes (claude.ai connectors, MCP clients)
                # must see a clean 404, not 401 — a 401 here makes clients
                # believe an OAuth sign-in service exists and attempt dynamic
                # client registration, which then fails. The inner app has no
                # such routes, so passing through yields the 404.
                await self.app(scope, receive, send)
                return

            request = Request(scope)
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
            else:
                token = request.query_params.get("token", "")

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
