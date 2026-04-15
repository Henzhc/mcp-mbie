# mcp-nzbn

MCP server that connects AI assistants to the [NZBN (New Zealand Business Number) API](https://api.business.govt.nz/api/explore-apis/by-category?category=nzbn). Search the NZ business register, look up company details, directors, filings, and more — all through the Model Context Protocol.

## Prerequisites

- Python 3.10+
- An NZBN API subscription key — [register here](https://api.business.govt.nz/)

## Install

```bash
git clone https://github.com/Henzhc/mcp-nzbn.git
cd mcp-nzbn
pip install -e .
```

## Configuration

All configuration is via environment variables.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NZBN_API_KEY` | Yes | — | Your NZBN API subscription key |
| `NZBN_API_BASE_URL` | No | `https://api.business.govt.nz/gateway/nzbn/v5` | API base URL |
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
mcp-nzbn
```

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "nzbn": {
      "command": "mcp-nzbn",
      "env": {
        "NZBN_API_KEY": "your-key"
      }
    }
  }
}
```

### Remote (Streamable HTTP)

Run as a shared HTTP server for your team. Teammates connect their Claude clients to the URL.

```bash
export NZBN_API_KEY="your-key"
export MCP_TRANSPORT=streamable-http
export MCP_AUTH_TOKEN="your-shared-secret"  # optional, enables bearer auth
export MCP_PORT=8000
mcp-nzbn
```

The MCP endpoint will be available at `http://<host>:8000/mcp`.

When `MCP_AUTH_TOKEN` is set, all requests must include the header:

```
Authorization: Bearer your-shared-secret
```

Requests without a valid token receive a `401 Unauthorized` response.

## Tools

| Tool | Description |
|------|-------------|
| `search_entities` | Search by name, NZBN, or legacy number. Supports filters for entity status and type, with pagination. |
| `get_entity` | Full entity details by 13-digit NZBN — legal name, trading names, status, addresses, directors, shareholders. |
| `get_entity_addresses` | Registered and service addresses, filterable by address type. |
| `get_entity_roles` | Directors, shareholders, and other roles for an entity. |
| `get_company_details` | Companies Office details — annual return filing month, constitution, etc. |
| `get_entity_filings` | Filing history (annual returns, etc.) with pagination. |
| `get_entity_history` | Full change history — name changes, status changes, address changes. |

All tools are read-only and idempotent.

## Project Structure

```
mcp-nzbn/
├── pyproject.toml              # Package metadata and dependencies
├── nzbn_mcp.py                 # Convenience entry point (python nzbn_mcp.py)
└── src/mcp_nzbn/
    ├── __init__.py
    └── server.py               # MCP server, tools, and HTTP transport
```

## License

MIT
