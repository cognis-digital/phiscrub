"""PHISCRUB MCP server — exposes scan() as an MCP tool for Cognis.Studio."""
from __future__ import annotations

import json

from phiscrub.core import scan_path


def _findings_to_json(results: dict) -> str:
    """Serialise scan_path() results to a JSON string."""
    payload = {
        fp: [f.to_dict() for f in findings]
        for fp, findings in results.items()
        if findings
    }
    return json.dumps(payload, indent=2)


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
        """Scan a file or directory for PHI (names, MRNs, SSNs, dates,
        addresses).  Returns JSON findings."""
        if not target or not isinstance(target, str):
            return json.dumps({"error": "target must be a non-empty string"})
        results = scan_path(target)
        return _findings_to_json(results)

    app.run()
    return 0
