# mcp-mbie

MCP server that connects AI assistants to the MBIE business register APIs — the [NZBN (New Zealand Business Number) API](https://portal.api.business.govt.nz/api/nzbn) and the [Companies Entity Role Search API](https://portal.api.business.govt.nz/api/companies-entity-role-search). Search the NZ business register, look up company details, directors, shareholders, filings, and more — all through the Model Context Protocol.

## Prerequisites

- Python 3.10+
- An NZBN API subscription key — [register here](https://portal.api.business.govt.nz/)
- A Companies Entity Role Search API subscription key (for `search_entity_roles`)

## Install

```bash
git clone https://github.com/Henzhc/mcp-mbie.git
cd mcp-mbie
pip install -e .
```

## Configuration

All configuration is via environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NZBN_API_KEY` | Yes | — | Your NZBN API subscription key |
| `COMPANIES_ROLE_API_KEY` | Yes | — | Your Companies Entity Role Search API subscription key |
| `NZBN_API_BASE_URL` | No | `https://api.business.govt.nz/gateway/nzbn/v5` | NZBN API base URL |
| `COMPANIES_ROLE_API_BASE_URL` | No | `https://api.business.govt.nz/gateway/companies-office/companies-register/entity-roles/v3` | Entity roles API base URL |
| `NZBN_TIMEOUT` | No | `30` | HTTP request timeout (seconds) |
| `MCP_TRANSPORT` | No | `stdio` | Transport: `stdio` or `streamable-http` |
| `MCP_HOST` | No | `0.0.0.0` | Bind address (HTTP mode) |
| `MCP_PORT` | No | `8000` | Listen port (HTTP mode) |
| `MCP_AUTH_TOKEN` | No | — | Bearer token for HTTP auth (optional) |

## Usage

### Local (stdio)

Best for single-user setups. Claude spawns the server process directly.

```bash
export NZBN_API_KEY="your-key"
export COMPANIES_ROLE_API_KEY="your-key"
mcp-mbie
```

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mbie": {
      "command": "mcp-mbie",
      "env": {
        "NZBN_API_KEY": "your-key",
        "COMPANIES_ROLE_API_KEY": "your-key"
      }
    }
  }
}
```

### Remote (Streamable HTTP)

Run as a shared HTTP server for your team. Teammates connect their Claude clients to the URL.

```bash
export NZBN_API_KEY="your-key"
export COMPANIES_ROLE_API_KEY="your-key"
export MCP_TRANSPORT=streamable-http
export MCP_AUTH_TOKEN="your-shared-secret"  # optional, enables bearer auth
export MCP_PORT=8000
mcp-mbie
```

The MCP endpoint will be available at `http://<host>:8000/mcp`.

When `MCP_AUTH_TOKEN` is set, all requests must include the header:

```
Authorization: Bearer your-shared-secret
```

Requests without a valid token receive a `401 Unauthorized` response.

## Tools

### NZBN API

| Tool | Description |
|------|-------------|
| `search_entities` | Search by name, NZBN, or legacy number. Filters for entity status, type, and industry code, with pagination. |
| `get_entity` | Full entity record by 13-digit NZBN — legal name, trading names, status, addresses, roles, GST numbers, industry classifications. |
| `get_entity_addresses` | Addresses of one type (REGISTERED, POSTAL, SERVICE, OFFICE, DELIVERY, INVOICE). |
| `get_entity_roles` | Directors, shareholders, and other roles for a known entity. |
| `get_company_details` | Companies Office details for NZ companies — annual return filing month, constitution, NZSX code. |
| `get_entity_non_company_details` | Register details for non-company entities — limited partnerships, charitable trusts, incorporated societies. |
| `get_entity_filings` | Complete filing history (annual returns, director changes, etc.) with document links. |
| `get_entity_phone_numbers` | Phone numbers for an entity. |
| `get_entity_email_addresses` | Email addresses for an entity. |
| `get_entity_websites` | Websites for an entity. |
| `get_entity_gst_numbers` | GST numbers registered for an entity. |
| `get_entity_industry_classifications` | Industry classifications (BIC codes) for an entity. |
| `get_entity_trading_areas` | Geographic trading areas declared for an entity. |
| `get_entity_history` | Full change history — name changes, status changes, address changes. |

### Companies Entity Role Search API

| Tool | Description |
|------|-------------|
| `search_entity_roles` | Search directors and shareholders by person or organisation name — finds all companies a person holds roles in. |

All tools are read-only and idempotent.

## Project Structure

```
mcp-mbie/
├── pyproject.toml              # Package metadata and dependencies
├── app.py                      # ASGI entry point for Azure App Service
└── src/mcp_mbie/
    ├── __init__.py
    └── server.py               # MCP server, tools, and HTTP transport
```

## License

MIT
