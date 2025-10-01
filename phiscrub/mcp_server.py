"""PHISCRUB MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations
from phiscrub.core import scan, to_json

def serve() -> int:
    """Start an MCP stdio server. Requires the optional 'mcp' extra:
        pip install "cognis-phiscrub[mcp]"
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        print("Install the MCP extra: pip install 'cognis-phiscrub[mcp]'")
        return 1
    app = FastMCP("phiscrub")

    @app.tool()
    def phiscrub_scan(target: str) -> str:
        """Stream-scan logs, CSVs, and free-text notes for PHI (names, MRNs, SSNs, dates, addresses) and redact or tokenize in place.. Returns JSON findings."""
        return to_json(scan(target))

    app.run()
    return 0
