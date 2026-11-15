"""Снимок метаданных публичных курсов; сами видео не скачиваются."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((Path(__file__).parent / "data" / "avito_course_videos.json").read_text(encoding="utf-8"))


def lessons_for_topic(slug: str) -> list[dict]:
    modules = {"fe-js-web": 1, "fe-js-data": 2, "fe-js-this": 3,
               "fe-js-prototypes": 4, "fe-js-objects": 5}
    selections = {
        "fe-practice-review": (1, {1, 2, 3}), "fe-practice-errors": (1, {4}),
        "fe-practice-simple": (2, {1, 2}), "fe-practice-solid": (2, set(range(4, 10))),
        "fe-practice-patterns": (3, {5, 6, 8}),
    }
    lessons = catalog()["lessons"]
    if slug in modules:
        return [l for l in lessons if l["course"] == "javascript" and l["module"] == modules[slug]]
    if slug in selections:
        season, numbers = selections[slug]
        return [l for l in lessons if l["course"] == "patterns" and l["season"] == season and l["number"] in numbers]
    return []


def groups() -> list[dict]:
    lessons = catalog()["lessons"]
    result = []
    for course, key, label, count in (("javascript", "module", "JavaScript · модуль", 5),
                                     ("patterns", "season", "Паттерны и практики · сезон", 3)):
        for n in range(1, count + 1):
            result.append({"title": f"{label} {n}", "lessons": [l for l in lessons
                           if l["course"] == course and l[key] == n]})
    return result
