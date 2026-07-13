from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.mcp.python_tools import run_restricted_python


mcp = FastMCP("AIOS Python", instructions="Restricted, isolated Python calculations with no imports or file access.")


@mcp.tool()
def run_python(code: str, timeout_seconds: int = 5) -> dict:
    """Run restricted Python; assign a JSON-compatible value to `result` to return it."""
    return run_restricted_python(code, timeout_seconds)


if __name__ == "__main__":
    mcp.run(transport="stdio")
