"""Итоговый отчёт наставника по стажёру и черновик письма-характеристики.

Отчёт собирается из данных прототипа (чек-лист, цели, материалы, вопросы, встречи, анкета стажёра).
Черновик письма наставник редактирует и сохраняет — по нему потом пишется характеристика / рекомендация.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from ..agent.nlu import CATEGORIES, categorize
from ..models import ChatMessage, InternReport, Meeting, MentorQuestion, User, db
from ..permissions import PermissionDenied, can_view_user
from . import checklist, feedback, goals, kb, materials


def _fmt(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "—"


def build(viewer: User, intern: User, today: date | None = None) -> dict:
    if intern is None or intern.role != "intern" or not can_view_user(viewer, intern):
        raise PermissionDenied("Нет доступа к данным этого стажёра")
    today = today or date.today()
    data = checklist.get_checklist(intern)
    goal_items = [goals.to_dict(g) for g in goals.list_goals(viewer, intern)]
    asked = [m.text for m in ChatMessage.query.filter_by(user_id=intern.id, role="user").all() if m.text.strip()]
    escalations = MentorQuestion.query.filter_by(intern_id=intern.id).all()
    cats = Counter(categorize(q.question, "kb") for q in escalations)
    meetings = Meeting.query.filter(Meeting.kind == "mentor", Meeting.status == "accepted",
                                    db.or_(Meeting.organizer_id == intern.id, Meeting.attendee_id == intern.id),
                                    Meeting.start <= datetime.now()).count()
    saved = InternReport.query.filter_by(intern_id=intern.id).first()
    report = {
        "intern": {"id": intern.id, "name": intern.full_name, "position": intern.position, "team": intern.team,
                   "program": intern.program, "start": _fmt(intern.start_date), "end": _fmt(intern.end_date),
                   "days": (today - intern.start_date).days if intern.start_date else 0,
                   "mentor": intern.mentor.full_name if intern.mentor else "—",
                   "lead": intern.lead.full_name if intern.lead else "—"},
        "checklist": {"done": data["done"], "total": data["total"], "percent": data["percent"],
                      "stages": [{"title": f"{w['period']}. {w['title']}", "done": w["done"], "total": w["total"]}
                                 for w in data["weeks"]]},
        "goals": goal_items,
        "goals_done": sum(1 for g in goal_items if g["status"] == "done"),
        "kb": kb.progress(intern),
        "materials": materials.stats(intern),
        "questions_to_bot": len(asked),
        "questions_to_mentor": len(escalations),
        "question_topics": [{"label": CATEGORIES[k], "count": v} for k, v in cats.most_common()],
        "meetings": meetings,
        "feedback": feedback.to_dict(feedback.get(intern)),
        "saved": bool(saved),
        "updated": saved.updated_at.strftime("%d.%m.%Y %H:%M") if saved and saved.updated_at else "",
    }
    report["letter"] = saved.letter if saved and saved.letter else draft_letter(report)
    return report


def draft_letter(r: dict) -> str:
    i = r["intern"]
    lines = [
        "Характеристика стажёра",
        "",
        f"{i['name']} проходит стажировку в Avito ({i['team']}) с {i['start']}"
        + (f" по {i['end']}" if i["end"] != "—" else "") + (f" на позиции «{i['position']}»." if i["position"] else "."),
        f"Наставник — {i['mentor']}, руководитель — {i['lead']}.",
        "",
        "Результаты стажировки:",
        f"— выполнено {r['checklist']['done']} из {r['checklist']['total']} задач плана адаптации "
        f"({r['checklist']['percent']}%);",
    ]
    if r["goals"]:
        lines.append(f"— цели на стажировку: достигнуто {r['goals_done']} из {len(r['goals'])}:")
        lines += [f"    • {g['title']}{' — выполнено' if g['status'] == 'done' else ''}" for g in r["goals"]]
    lines.append(f"— изучено материалов базы знаний: {r['kb']['done']} из {r['kb']['total']}"
                 + (f", статей от наставника: {r['materials']['done']} из {r['materials']['total']}"
                    if r["materials"]["total"] else "") + ";")
    if r["meetings"]:
        lines.append(f"— проведено встреч 1:1 с наставником: {r['meetings']}.")
    lines += [
        "",
        "Сильные стороны: [дополните — например, самостоятельность, качество кода, коммуникация]",
        "Зоны роста: [дополните]",
        "",
        "Рекомендация: [дополните — например, рекомендую к переводу в штат на позицию …]",
        "",
        f"Наставник: {i['mentor']}",
    ]
    return "\n".join(lines)


def save_letter(mentor: User, intern: User, letter: str) -> InternReport:
    if intern is None or intern.mentor_id != mentor.id:
        raise PermissionDenied("Письмо по стажёру составляет его наставник")
    letter = (letter or "").strip()
    if not letter:
        raise ValueError("Письмо пустое")
    rep = InternReport.query.filter_by(intern_id=intern.id).first()
    if rep is None:
        rep = InternReport(intern_id=intern.id, author_id=mentor.id)
        db.session.add(rep)
    rep.letter = letter[:20000]
    db.session.commit()
    return rep


def reset_letter(mentor: User, intern: User) -> None:
    if intern is None or intern.mentor_id != mentor.id:
        raise PermissionDenied("Письмо по стажёру составляет его наставник")
    InternReport.query.filter_by(intern_id=intern.id).delete()
    db.session.commit()
