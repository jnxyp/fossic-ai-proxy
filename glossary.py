from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

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


def load_glossary_csv(filename: str) -> Glossary:
    path = GLOSSARY_DIR / filename
    terms: list[GlossaryTerm] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            english = row[0].strip()
            chinese = row[1].strip()
            if not english or not chinese:
                continue
            alternatives_raw = row[3].strip() if len(row) > 3 else ""
            notes = row[4].strip() if len(row) > 4 else ""
            alternatives = [a.strip() for a in alternatives_raw.splitlines() if a.strip()]
            terms.append(GlossaryTerm(
                english=english,
                chinese=chinese,
                notes=notes,
                alternatives=alternatives,
            ))
    return Glossary(terms)
