"""MCP 진입점. tool 등록만 한다 — 비즈니스 로직은 tools/, analysis/, sources/, core/ 참조.

문서: CLAUDE.md, docs/ARCHITECTURE.md.
"""

from fastmcp import FastMCP

from tools import (
    blog_tools,
    citation_tools,
    feed_tools,
    pdf_tools,
    search_tools,
    viz_tools,
    wiki_tools,
)

mcp = FastMCP("Research Agent")

search_tools.register(mcp)
citation_tools.register(mcp)
pdf_tools.register(mcp)
wiki_tools.register(mcp)
feed_tools.register(mcp)
viz_tools.register(mcp)
blog_tools.register(mcp)


if __name__ == "__main__":
    mcp.run()
