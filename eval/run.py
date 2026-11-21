"""Офлайн-оценка на отдельной SQLite в памяти. Рабочая БД и внешние API не используются."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import create_app
from app.agent.agent import Agent
from app.config import TestConfig
from app.frontend_knowledge import ensure_frontend_knowledge
from app.models import AccessRequest, ConversationState, KBTopic, MentorQuestion, User, db
from app.permissions import topic_visible
from app.seed import seed
from app.services import kb


class EvalConfig(TestConfig):
    # Не наследуем DATABASE_URL / LLM-настройки процесса, в том числе в Docker.
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    SEED_ON_START = False
    LLM_PROVIDER = "offline"
    LLM_API_KEY = ""


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError(f"Пустой набор или повторяющиеся ID: {path}")
    return cases


def actions(reply) -> set[str]:
    return {a["action"] for c in reply.cards for a in c.get("actions", [])}


def check_scenario(user, case: dict) -> dict:
    state = db.session.get(ConversationState, user.id)
    if state:
        state.set({})
        db.session.commit()
    before = (AccessRequest.query.count(), MentorQuestion.query.count())
    replies = [Agent(user).handle_message(text) for text in case["messages"]]
    reply = replies[-1]
    expect = case["expect"]
    errors = []
    for key, value in expect.get("meta", {}).items():
        if reply.meta.get(key) != value:
            errors.append(f"meta.{key}: ожидалось {value!r}, получено {reply.meta.get(key)!r}")
    slugs = {s["slug"] for s in reply.sources}
    if "source" in expect and expect["source"] not in slugs:
        errors.append("Нет ожидаемого источника: " + expect["source"])
    if expect.get("forbidden_source") in slugs:
        errors.append("В ответ попал недоступный источник")
    if "action" in expect and expect["action"] not in actions(reply):
        errors.append("Нет действия: " + expect["action"])
    if "text_contains" in expect and expect["text_contains"].casefold() not in reply.text.casefold():
        errors.append("Нет ожидаемого фрагмента: " + expect["text_contains"])
    state = db.session.get(ConversationState, user.id)
    data = state.get() if state else {}
    if "state_flow" in expect and data.get("flow") != expect["state_flow"]:
        errors.append("Неверное состояние диалога")
    if expect.get("state_empty") and data:
        errors.append("Состояние не очищено")
    after = (AccessRequest.query.count(), MentorQuestion.query.count())
    if expect.get("no_access_created") and after[0] != before[0]:
        errors.append("Заявка создана без подтверждения")
    if expect.get("no_mentor_created") and after[1] != before[1]:
        errors.append("Вопрос отправлен без подтверждения")
    if "inaccessible_slug" in expect:
        try:
            kb.get_topic(user, expect["inaccessible_slug"])
        except LookupError:
            pass
        else:
            errors.append("Сервис выдал недоступный материал")
    if reply.meta.get("error"):
        errors.append("Ошибка обработчика")
    return {"id": case["id"], "name": case["name"], "passed": not errors,
            "errors": errors, "reply": reply.text, "sources": sorted(slugs)}


def evaluate() -> dict:
    retrieval = load_cases(ROOT / "eval/retrieval.json")
    scenarios = load_cases(ROOT / "eval/scenarios.json")
    kb._INDEX.clear()
    app = create_app(EvalConfig)
    with app.app_context():
        try:
            seed(today=date(2026, 11, 16))
            ensure_frontend_knowledge()
            user = User.query.filter_by(login="arina").one()
            results = []
            for case in retrieval:
                for slug in case["expected"]:
                    topic = KBTopic.query.filter_by(slug=slug).one()
                    if not topic_visible(user, topic):
                        raise ValueError(f"Эталон недоступен пользователю: {case['id']} / {slug}")
                hits = kb.search(user, case["query"], limit=3)
                got = [h.topic.slug for h in hits]
                expected = set(case["expected"])
                results.append({**case, "actual": got, "top1": bool(got and got[0] in expected),
                                "top3": bool(expected.intersection(got)),
                                "scores": [round(h.score, 3) for h in hits]})
            flows = [check_scenario(user, c) for c in scenarios]
        finally:
            db.session.remove()
            db.engine.dispose()
            kb._INDEX.clear()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        commit, dirty = "unknown", None
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT / "eval/retrieval.json", ROOT / "eval/scenarios.json")}
    return {"metadata": {"commit": commit, "working_tree_changes": dirty, "dataset_sha256": hashes,
                         "demo_date": "2026-11-16", "login": "arina", "llm": "offline",
                         "database": "isolated SQLite in memory"},
            "summary": {"retrieval_total": len(results), "top1": sum(r["top1"] for r in results),
                        "top3": sum(r["top3"] for r in results),
                        "scenarios_total": len(flows), "scenarios_passed": sum(r["passed"] for r in flows)},
            "retrieval": results, "scenarios": flows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "eval/results/latest.json")
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = report["summary"]
    print(f"Top-1: {s['top1']}/{s['retrieval_total']} ({s['top1']/s['retrieval_total']:.1%})")
    print(f"Top-3: {s['top3']}/{s['retrieval_total']} ({s['top3']/s['retrieval_total']:.1%})")
    print(f"Сценарии: {s['scenarios_passed']}/{s['scenarios_total']}")
    for row in report["scenarios"]:
        if not row["passed"]:
            print(row["id"], "; ".join(row["errors"]))
    print(f"Отчёт: {args.output}")
    # Промахи поиска фиксируются в метрике. Нарушение контракта сценария — ошибка запуска.
    return int(s["scenarios_passed"] != s["scenarios_total"])


if __name__ == "__main__":
    raise SystemExit(main())
