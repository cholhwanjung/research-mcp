# 🔬 Claude Desktop Research MCP Server

## Tools

| Tool | 기능 |
|------|------|
| `search_papers` | arXiv 키워드 검색 — 결과를 최근 1년/3년/5년으로 분류해 반환 |
| `get_paper_by_id` | arXiv ID · DOI · Semantic Scholar ID로 논문 상세 조회 (TL;DR 포함) |
| `read_paper` | arXiv PDF 다운로드 후 전문 텍스트 추출 |
| `get_references_by_citations` | 논문이 참조한 선행 연구를 인용수 기준으로 정렬 반환 |
| `get_citations_by_citations` | 논문을 인용한 후속 연구를 인용수 기준으로 정렬 반환 |

## 사용 흐름

```
"VLM 최신 논문 찾아줘"
  → search_papers("vision language model")

"2301.12597 논문 자세히 알려줘"
  → get_paper_by_id("2301.12597")

"이 논문 전문 읽어줘"
  → read_paper("2301.12597")

"이 논문을 인용한 후속 연구 뭐 있어?"
  → get_citations_by_citations("2304.08485", top_k=10)

"이 논문이 참고한 선행 연구는?"
  → get_references_by_citations("2301.12597", top_k=20)
```

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/cholhwanjung/research-mcp
cd research-mcp
uv sync
```

### 2. Claude Desktop 설정

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "research": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/research-mcp",
        "server.py"
      ]
    }
  }
}
```

