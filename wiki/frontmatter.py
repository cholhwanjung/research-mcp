"""Obsidian-스타일 YAML frontmatter parse/dump.

규약: `---\\n<yaml>\\n---\\n<body>`. allow_unicode=True로 한국어 보존.
"""

from __future__ import annotations

import yaml

_DELIM = "---\n"


def parse_note(content: str) -> tuple[dict, str]:
    if not content.startswith(_DELIM):
        return {}, content
    end = content.find("\n" + _DELIM, len(_DELIM))
    if end == -1:
        return {}, content
    yaml_block = content[len(_DELIM) : end + 1]
    body = content[end + 1 + len(_DELIM) :]
    fm = yaml.safe_load(yaml_block) or {}
    return fm, body


def dump_note(fm: dict, body: str) -> str:
    if not fm:
        return body
    yaml_block = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
    return _DELIM + yaml_block + _DELIM + body
