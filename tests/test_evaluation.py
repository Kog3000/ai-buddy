"""Контракт отчёта оценки: новые запросы могут ухудшать метрику и должны оставаться видны."""
import importlib.util
from pathlib import Path


def test_evaluation_is_isolated_and_reports_failures(app, arina):
    from app.models import ChatMessage, db

    db.session.add(ChatMessage(user_id=arina.id, role="user", text="Данные работающего приложения"))
    db.session.commit()
    path = Path(__file__).resolve().parents[1] / "eval/run.py"
    spec = importlib.util.spec_from_file_location("evaluation_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.evaluate()
    assert len(report["retrieval"]) == 42 and len(report["scenarios"]) == 10
    assert all(r["passed"] for r in report["scenarios"])
    assert report["summary"]["top1"] == sum(r["top1"] for r in report["retrieval"])
    assert report["summary"]["top3"] == sum(r["top3"] for r in report["retrieval"])
    assert report["metadata"]["llm"] == "offline"
    assert report["metadata"]["dataset_sha256"].keys() == {"retrieval.json", "scenarios.json"}
    assert ChatMessage.query.filter_by(text="Данные работающего приложения").count() == 1
