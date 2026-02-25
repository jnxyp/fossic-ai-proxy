from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from logger import get_logger

log = get_logger()
GLOSSARY_DIR = Path("glossary")


@dataclass
class GlossaryTerm:
    english: str
    chinese: str
    notes: str
    alternatives: list[str] = field(default_factory=list)

    def all_forms(self) -> list[str]:
        return [self.english] + self.alternatives


class Glossary:
    def __init__(self, terms: list[GlossaryTerm]):
        self.terms = terms

    def find_matches(self, text: str) -> list[GlossaryTerm]:
        text_lower = text.lower()
        matched = []
        seen: set[str] = set()
        for term in self.terms:
            if term.english in seen:
                continue
            for form in term.all_forms():
                if not form:
                    continue
                if re.search(r"\b" + re.escape(form.lower()) + r"\b", text_lower):
                    matched.append(term)
                    seen.add(term.english)
                    break
        return matched

    def build_system_message(self, matches: list[GlossaryTerm]) -> str:
        lines = ["以下是与当前原文可能相关的术语参考译法，请结合上下文判断含义是否符合，符合时采用对应译文：\n"]
        for term in matches:
            line = f"- {term.english} → {term.chinese}"
            if term.notes:
                line += f"（{term.notes}）"
            lines.append(line)
        return "\n".join(lines)


def _parse_json(path: Path) -> Glossary:
    data = json.loads(path.read_text(encoding="utf-8"))
    terms = []
    for t in data.get("terms", []):
        english = (t.get("term") or "").strip()
        chinese = (t.get("translation") or "").strip()
        if not english or not chinese:
            continue
        terms.append(GlossaryTerm(
            english=english,
            chinese=chinese,
            notes=(t.get("note") or "").strip(),
            alternatives=[v.strip() for v in (t.get("variants") or []) if v.strip()],
        ))
    return Glossary(terms)


class GlossaryLoader:
    """
    Wraps a JSON glossary file with mtime-based hot-reload.
    Drop-in replacement for Glossary — exposes the same find_matches /
    build_system_message interface so the rest of the code is unchanged.
    """

    def __init__(self, path: Path):
        self._path = path
        self._glossary: Glossary | None = None
        self._mtime: float = -1.0

    def _reload_if_needed(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime != self._mtime:
            self._glossary = _parse_json(self._path)
            self._mtime = mtime
            log.info(f"loaded glossary: {len(self._glossary.terms)} terms from {self._path}")

    def find_matches(self, text: str) -> list[GlossaryTerm]:
        self._reload_if_needed()
        return self._glossary.find_matches(text) if self._glossary else []

    def build_system_message(self, matches: list[GlossaryTerm]) -> str:
        if not self._glossary:
            return ""
        return self._glossary.build_system_message(matches)


def make_glossary_loader(filename: str) -> GlossaryLoader:
    return GlossaryLoader(GLOSSARY_DIR / filename)
