"""The seven read-only RYO research tools, over MCP or REST.

Both transports satisfy the same source contract, so snapshots, integrity
checks, replay and fact extraction are identical either way. MCP is the
path the hackathon credential is issued for; REST is kept for the case
where a plain HTTP endpoint is published.
"""

from .client import DEFAULT_BASE, TOOLS, RyoToolSource, build_sources
from .facts import Extraction, extract_market_facts
from .mcp import McpClient, McpError, RyoMcpSource, ToolResult, build_mcp_sources

__all__ = [
    "DEFAULT_BASE",
    "Extraction",
    "McpClient",
    "McpError",
    "RyoMcpSource",
    "RyoToolSource",
    "TOOLS",
    "ToolResult",
    "build_mcp_sources",
    "build_sources",
    "extract_market_facts",
]
