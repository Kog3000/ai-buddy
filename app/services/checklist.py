"""Чек-лист адаптации: этапы (по сроку от начала стажировки), статусы задач, следующие шаги."""
from __future__ import annotations

from ..analytics import track
from ..models import ChecklistTask, User, UserTask, db, now
from ..permissions import PermissionDenied
from ..seed_data import CHECKLIST
from .notify import notify, post_to_chat, resolve

STAGES = {stage: (period, title) for stage, (period, title, _) in CHECKLIST.items()}


def _ensure(user: User) -> dict[int, UserTask]:
    rows = {ut.task_id: ut for ut in UserTask.query.filter_by(user_id=user.id).all()}
    missing = [t for t in ChecklistTask.query.all() if t.id not in rows]
    for task in missing:
        ut = UserTask(user_id=user.id, task_id=task.id, status="todo")
        db.session.add(ut)
        rows[task.id] = ut
    if missing:
        db.session.commit()
    return rows


def get_checklist(user: User) -> dict:
    rows = _ensure(user)
    tasks = ChecklistTask.query.order_by(ChecklistTask.week, ChecklistTask.order).all()
    weeks: list[dict] = []
    for week, (period, title) in STAGES.items():
        items = []
        for task in tasks:
            if task.week != week:
                continue
            ut = rows[task.id]
            items.append({
                "id": task.id, "title": task.title, "description": task.description,
                "status": ut.status, "done": ut.status == "done", "source": ut.source,
                "kb_topic": task.kb_topic_slug, "chat_prompt": task.chat_prompt,
                "auto": bool(task.auto_key), "by_mentor": task.confirm_by == "mentor",
                "waiting": ut.status == "review",
            })
        done = sum(1 for i in items if i["done"])
        weeks.append({"week": week, "period": period, "title": title, "tasks": items, "done": done,
                      "total": len(items)})
    total = sum(w["total"] for w in weeks)
    done = sum(w["done"] for w in weeks)
    current = user.stage_number()
    return {
        "weeks": weeks, "done": done, "total": total,
        "percent": round(done * 100 / total) if total else 0,
        "current_week": current,
    }


def set_status(user: User, task_id: int, done: bool, source: str = "manual") -> UserTask:
    """Отметка стажёром (source=manual) или по событию сервиса (source=auto)."""
    rows = _ensure(user)
    ut = rows.get(task_id)
    if ut is None:
        raise KeyError(task_id)
    if source == "manual" and ut.task.confirm_by == "mentor":
        raise PermissionDenied("Эту задачу отмечает наставник — попроси его подтвердить выполнение")
    return _apply(user, ut, done, source)


def _apply(user: User, ut: UserTask, done: bool, source: str) -> UserTask:
    task_id = ut.task_id
    ut.status = "done" if done else "todo"
    ut.completed_at = now() if done else None
    ut.source = source if done else None
    db.session.commit()
    track(user, "checklist_task_done" if done else "checklist_task_undone", task_id=task_id, source=source)
    return ut


def auto_complete(user: User, auto_key: str) -> ChecklistTask | None:
    """Закрывает задачу чек-листа по событию из корпоративного сервиса."""
    task = ChecklistTask.query.filter_by(auto_key=auto_key).first()
    if task is None:
        return None
    rows = _ensure(user)
    if rows[task.id].status == "done":
        return None
    set_status(user, task.id, True, source="auto")
    return task


def next_steps(user: User, limit: int = 3) -> list[dict]:
    data = get_checklist(user)
    result = []
    for week in data["weeks"]:
        for task in week["tasks"]:
            if not task["done"]:
                result.append({**task, "week": week["week"], "period": week["period"], "week_title": week["title"]})
                if len(result) >= limit:
                    return result
    return result


def request_confirm(intern: User, task_id: int) -> UserTask:
    """Стажёр просит наставника подтвердить выполнение задачи, которую отмечает наставник."""
    ut = _ensure(intern).get(task_id)
    if ut is None:
        raise KeyError(task_id)
    if ut.task.confirm_by != "mentor":
        raise ValueError("Эту задачу можно отметить самому")
    if ut.status == "done":
        raise ValueError("Задача уже выполнена")
    if intern.mentor is None:
        raise PermissionDenied("Наставник не назначен")
    ut.status = "review"
    db.session.commit()
    notify(intern.mentor, f"{intern.full_name} просит подтвердить задачу «{ut.task.title}»",
           f"/team/intern/{intern.id}", dedup_key=f"task-confirm:{intern.id}:{task_id}")
    track(intern, "checklist_confirm_requested", task_id=task_id)
    return ut


def mentor_set(mentor: User, intern: User, task_id: int, done: bool) -> UserTask:
    """Наставник отмечает задачу стажёра (любую — в том числе ту, что стажёр отмечает сам)."""
    if intern.mentor_id != mentor.id:
        raise PermissionDenied("Отмечать задачи может только наставник этого стажёра")
    ut = _ensure(intern).get(task_id)
    if ut is None:
        raise KeyError(task_id)
    _apply(intern, ut, done, "mentor")
    resolve(f"task-confirm:{intern.id}:{task_id}")
    if done:
        text = f"{mentor.full_name} подтвердил(а) выполнение задачи «{ut.task.title}»."
        notify(intern, text, "/checklist", dedup_key=f"task-done:{intern.id}:{task_id}")
        post_to_chat(intern, text, suggestions=["Что дальше?"])
    return ut


def waiting_for(mentor: User) -> list[dict]:
    """Задачи стажёров наставника, ждущие подтверждения."""
    rows = (UserTask.query.join(User, User.id == UserTask.user_id)
            .filter(User.mentor_id == mentor.id, UserTask.status == "review").all())
    return [{"intern_id": r.user_id, "intern": r.user.full_name, "task_id": r.task_id, "title": r.task.title}
            for r in rows]
