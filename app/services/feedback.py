"""Обратная связь стажёра в конце стажировки.

Подсчёт эффекта (часы наставника и т. п.) в прототипе не ведётся: по договорённости с организаторами
статистику собирают из анкет стажёров и писем наставников после окончания стажировок.
"""
from __future__ import annotations

from ..analytics import track
from ..models import InternFeedback, User, db
from ..permissions import PermissionDenied
from . import checklist
from .notify import notify

QUESTIONS = {
    "easier": "Стало ли легче адаптироваться благодаря AI-buddy?",
    "bot_useful": "Насколько полезны были ответы и подсказки AI-buddy?",
    "mentor_support": "Хватало ли поддержки наставника?",
}


def get(intern: User) -> InternFeedback | None:
    return InternFeedback.query.filter_by(intern_id=intern.id).first()


def submit(intern: User, easier: int, bot_useful: int, mentor_support: int, hardest: str = "",
           improve: str = "") -> InternFeedback:
    if intern.role != "intern":
        raise PermissionDenied("Анкету заполняет стажёр")
    scores = [easier, bot_useful, mentor_support]
    try:
        scores = [int(s) for s in scores]
    except (TypeError, ValueError) as exc:
        raise ValueError("Поставь оценки от 1 до 5") from exc
    if any(s < 1 or s > 5 for s in scores):
        raise ValueError("Поставь оценки от 1 до 5")
    fb = get(intern) or InternFeedback(intern_id=intern.id, easier=0, bot_useful=0, mentor_support=0)
    fb.easier, fb.bot_useful, fb.mentor_support = scores
    fb.hardest, fb.improve = (hardest or "").strip()[:2000], (improve or "").strip()[:2000]
    db.session.add(fb)
    db.session.commit()
    checklist.auto_complete(intern, "feedback_sent")
    if intern.mentor:
        notify(intern.mentor, f"{intern.full_name} заполнил(а) анкету о стажировке", f"/team/intern/{intern.id}/report",
               dedup_key=f"feedback:{intern.id}")
    track(intern, "feedback_sent", easier=fb.easier)
    return fb


def summary(interns: list[User]) -> dict:
    rows = InternFeedback.query.filter(InternFeedback.intern_id.in_([i.id for i in interns] or [0])).all()
    avg = {key: round(sum(getattr(r, key) for r in rows) / len(rows), 1) if rows else None for key in QUESTIONS}
    return {"count": len(rows), "of": len(interns), "avg": avg, "questions": QUESTIONS,
            "comments": [{"name": r.intern.full_name, "hardest": r.hardest, "improve": r.improve}
                         for r in rows if r.hardest or r.improve]}


def to_dict(fb: InternFeedback | None) -> dict | None:
    if fb is None:
        return None
    return {"easier": fb.easier, "bot_useful": fb.bot_useful, "mentor_support": fb.mentor_support,
            "hardest": fb.hardest, "improve": fb.improve, "date": fb.created_at.strftime("%d.%m.%Y")}
