"""vault 논문 프루닝 — "주요하지 않은 논문" 후보 산출 + 논문 단위 삭제 (ADR-073).

주요하지 않음 = **vault 안에서 아무도 쓰지 않는 논문**. 외부 인용수(velocity)는
가치를 예측하지 않으므로(ADR-057) 정렬에만 쓴다. 후보 조건은 전부 AND:

  (1) notes/ 통찰의 근거가 아니고, 인용 분석(`citation_analysis_at`)도 안 됨
  (2) papers/·notes/ 에서 들어오는 inbound wikilink 없음 — hub 자동 링크만 있거나 0
  (3) autopilot frontier(`source=F`)로 들어왔고 ingest 후 `min_age_days` 경과
  (4) 어떤 hub의 `seed_paper`도 아님

삭제는 `papers/<slug>/` 폴더 + `pdfs/<arxiv_id>.pdf` + `graphs/<slug>.md`. vault는
git 밖이라 되돌림은 arxiv_id 재ingest — 호출측(스킬)이 `_meta/prune-log.md`에 남긴다.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from analysis.linkgraph import build_link_graph
from wiki.frontmatter import parse_note
from wiki.linker import extract_links, read_vault_notes
from wiki.pdf_store import pdf_path
from wiki.vault import paper_dir, vault_root

# 조건 (2): 이 디렉토리에서 오는 inbound는 "쓰이고 있다"는 신호. 나머지(topics/·graphs/·
# tech-blog-digest/·research-autopilot/·_meta/)는 자동 생성 링크라 보호하지 않는다.
_PROTECTING_DIRS = ("papers/", "notes/")

_START_RE = re.compile(r"action=start \| id=(\S+) \| source=(\S+)")
_INGEST_RE = re.compile(r"action=ingest \| id=(\S+) \| slug=(\S+) \| status=ok")


@dataclass
class Candidate:
    slug: str
    arxiv_id: str
    title: str
    velocity: float
    ingested_at: str
    pdf_bytes: int
    inbound: list[str]


def frontier_slugs(log_text: str) -> set[str]:
    """autopilot 로그에서 `source=F`로 시작해 `status=ok`로 ingest된 slug 집합.

    start 줄(id, source)과 ingest 줄(id, slug)을 id로 join한다. 같은 id의 start가
    여럿이면(이어받기) 첫 줄의 source를 쓴다.
    """
    source_of: dict[str, str] = {}
    for m in _START_RE.finditer(log_text):
        source_of.setdefault(m.group(1), m.group(2))
    return {
        slug for pid, slug in _INGEST_RE.findall(log_text)
        if source_of.get(pid) == "F"
    }


def _float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _hub_seed_ids() -> set[str]:
    base = vault_root() / "topics"
    if not base.is_dir():
        return set()
    seeds: set[str] = set()
    for p in base.glob("*.md"):
        try:
            fm, _ = parse_note(p.read_text(encoding="utf-8", errors="ignore"))
        except yaml.YAMLError:
            continue
        if isinstance(fm, dict) and fm.get("seed_paper"):
            seeds.add(str(fm["seed_paper"]))
    return seeds


def prune_candidates(today: date | None = None, min_age_days: int = 90) -> list[Candidate]:
    """조건 (1)~(4)를 모두 만족하는 논문을 velocity 오름차순으로."""
    today = today or date.today()
    log = vault_root() / "_meta" / "autopilot-log.md"
    if not log.is_file():
        return []
    frontier = frontier_slugs(log.read_text(encoding="utf-8", errors="ignore"))
    if not frontier:
        return []

    notes = read_vault_notes()
    graph = build_link_graph(notes, {s: extract_links(c) for s, c in notes.items()})
    seeds = _hub_seed_ids()
    cutoff = today - timedelta(days=min_age_days)

    out: list[Candidate] = []
    for slug in sorted(frontier):
        key = f"papers/{slug}/{slug}"
        if key not in notes:
            continue
        fm, _ = parse_note(notes[key])
        if not isinstance(fm, dict):
            continue
        if fm.get("citation_analysis_at"):
            continue
        arxiv_id = str(fm.get("arxiv_id") or "")
        if arxiv_id in seeds:
            continue
        ingested = _date(fm.get("ingested_at"))
        if ingested is None or ingested > cutoff:
            continue
        inbound = graph.backward.get(key, [])
        if any(src.startswith(_PROTECTING_DIRS) for src in inbound):
            continue
        pdf = pdf_path(arxiv_id)
        out.append(Candidate(
            slug=slug,
            arxiv_id=arxiv_id,
            title=str(fm.get("title") or slug),
            velocity=_float(fm.get("citation_velocity")),
            ingested_at=ingested.isoformat(),
            pdf_bytes=pdf.stat().st_size if pdf.is_file() else 0,
            inbound=list(inbound),
        ))
    out.sort(key=lambda c: (c.velocity, c.slug))
    return out


def delete_paper(slug: str) -> dict:
    """`papers/<slug>/` + `pdfs/<arxiv_id>.pdf` + `graphs/<slug>.md` 삭제.

    반환: {"slug", "arxiv_id", "title", "removed": [vault 상대경로]}.
    폴더 없음 → FileNotFoundError. slug가 vault 밖을 가리키면 VaultPathError.
    """
    folder = paper_dir(slug)
    if not folder.is_dir():
        raise FileNotFoundError(f"papers/{slug}")
    note = folder / f"{slug}.md"
    if not note.is_file():
        note = folder / "index.md"
    fm: dict = {}
    if note.is_file():
        parsed, _ = parse_note(note.read_text(encoding="utf-8", errors="ignore"))
        fm = parsed if isinstance(parsed, dict) else {}
    arxiv_id = str(fm.get("arxiv_id") or "")

    root = vault_root()
    removed: list[str] = []
    shutil.rmtree(folder)
    removed.append(f"papers/{slug}")
    targets: list[Path] = []
    if arxiv_id:
        targets.append(pdf_path(arxiv_id))
    targets.append(root / "graphs" / f"{slug}.md")
    for p in targets:
        if p.is_file():
            p.unlink()
            removed.append(str(p.relative_to(root)) if root in p.parents else str(p))
    return {"slug": slug, "arxiv_id": arxiv_id, "title": str(fm.get("title") or slug), "removed": removed}
