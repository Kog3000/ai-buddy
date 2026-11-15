"""Заполнение БД синтетическими данными. Даты считаются относительно дня запуска,
чтобы демо всегда начиналось с первого этапа стажировки (неделя 1)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from werkzeug.security import generate_password_hash

from .analytics import ensure_flags
from .models import (ChatMembership, ChatRoom, ChecklistTask, KBCategory, KBTopic, Meeting, MentorQuestion, Note,
                     Resource, TopicProgress, User, UserTask, db, now)
from .seed_data import (CHAT_ROOMS, CHECKLIST, KB, MATERIAL_TEMPLATES, MENTOR_CONFIRMED_TASKS, RESOURCES,
                        RESTRICTED_TOPICS, TEAM)

DEMO_PASSWORD = "demo123"


def _next_weekday(start: date, weekday: int) -> date:
    delta = (weekday - start.weekday()) % 7
    return start + timedelta(days=delta or 7)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(d.day, 28))


def seed(today: date | None = None) -> None:
    if User.query.first() is not None:
        ensure_flags()
        return
    today = today or date.today()
    start = today - timedelta(days=2)
    pwd = generate_password_hash(DEMO_PASSWORD)

    maria = User(login="maria", password_hash=pwd, full_name="Мария Смирнова", role="lead", team=TEAM,
                 position="Руководитель команды", email="maria.smirnova@example.com", phone="+7 900 000-00-01")
    elena = User(login="elena", password_hash=pwd, full_name="Елена Орлова", role="admin", team="Программа стажировок",
                 position="Куратор стажировки", email="elena.orlova@example.com", phone="+7 900 000-00-02")
    db.session.add_all([maria, elena])
    db.session.flush()
    ivan = User(login="ivan", password_hash=pwd, full_name="Иван Иванов", role="mentor", team=TEAM,
                position="Senior Frontend engineer", email="ivan.ivanov@example.com", phone="+7 900 000-00-03",
                lead_id=maria.id)
    db.session.add(ivan)
    db.session.flush()
    arina = User(login="arina", password_hash=pwd, full_name="Арина Язева", role="intern", team=TEAM,
                 position="Frontend engineer", phone="+7 910 777-77-77", email="example@mail.ru",
                 program="Осенняя стажировка Avito 2026", start_date=start, end_date=_add_months(start, 7),
                 mentor_id=ivan.id, lead_id=maria.id)
    dima = User(login="dima", password_hash=pwd, full_name="Дмитрий Ким", role="intern", team=TEAM,
                position="Frontend engineer", phone="+7 910 555-55-55", email="dima@example.com",
                program="Осенняя стажировка Avito 2026", start_date=start - timedelta(days=14),
                end_date=_add_months(start - timedelta(days=14), 7), mentor_id=ivan.id, lead_id=maria.id)
    db.session.add_all([arina, dima])
    db.session.flush()

    for order, (slug, title, hours, topics) in enumerate(KB):
        cat = KBCategory(slug=slug, title=title, hours=hours, order=order)
        db.session.add(cat)
        db.session.flush()
        minutes = max(10, round(hours * 60 / len(topics)))
        for t_order, (t_slug, t_title, body, tags, extra) in enumerate(topics):
            db.session.add(KBTopic(slug=t_slug, category_id=cat.id, title=t_title, body=body, tags=tags,
                                   minutes=minutes, order=t_order, team=extra.get("team"),
                                   audience=extra.get("audience", "all")))
    db.session.flush()
    for cat_slug, t_slug, t_title, body, tags, extra in RESTRICTED_TOPICS:
        cat = KBCategory.query.filter_by(slug=cat_slug).first()
        db.session.add(KBTopic(slug=t_slug, category_id=cat.id, title=t_title, body=body, tags=tags,
                               minutes=15, order=50, audience=extra["audience"]))

    tasks_by_title = {}
    for week, (_, _, tasks) in CHECKLIST.items():
        for order, (title, desc, kb_slug, prompt, auto_key, _) in enumerate(tasks):
            task = ChecklistTask(week=week, order=order, title=title, description=desc, kb_topic_slug=kb_slug,
                                 chat_prompt=prompt, auto_key=auto_key,
                                 confirm_by="mentor" if title in MENTOR_CONFIRMED_TASKS else "intern")
            db.session.add(task)
            tasks_by_title[title] = (task, week, order)
    db.session.flush()
    for title, (task, week, order) in tasks_by_title.items():
        pre_done = CHECKLIST[week][2][order][5]
        db.session.add(UserTask(user_id=arina.id, task_id=task.id, status="done" if pre_done else "todo",
                                completed_at=now() if pre_done else None, source="manual" if pre_done else None))
        dima_done = week < 3 or (week == 3 and order < 2)
        dima_review = week == 3 and order == 2  # Дмитрий попросил наставника подтвердить разбор ревью
        db.session.add(UserTask(user_id=dima.id, task_id=task.id,
                                status="done" if dima_done else "review" if dima_review else "todo",
                                completed_at=now() if dima_done else None, source="manual" if dima_done else None))

    owners = {"maria": maria}
    for code, name, desc, aliases, levels, intern_max, base, rule, owner in RESOURCES:
        db.session.add(Resource(code=code, name=name, description=desc, aliases=aliases, levels=levels,
                                intern_max_level=intern_max, base=base, approver_rule=rule,
                                owner_id=owners[owner].id if owner else None))

    tomorrow = today + timedelta(days=1)
    if tomorrow.weekday() >= 5:
        tomorrow = _next_weekday(today, 0)
    friday = _next_weekday(today, 4)
    monday = _next_weekday(today, 0)
    db.session.add_all([
        Meeting(title="Обсудить первые задачи", kind="mentor", organizer_id=ivan.id, attendee_id=arina.id,
                start=datetime.combine(tomorrow, time(11)), end=datetime.combine(tomorrow, time(12))),
        Meeting(title="Вводное обучение", kind="training", organizer_id=maria.id, attendee_id=arina.id,
                start=datetime.combine(friday, time(11)), end=datetime.combine(friday, time(13))),
        Meeting(title="Командная встреча", kind="team", organizer_id=maria.id, attendee_id=arina.id,
                start=datetime.combine(monday, time(12)), end=datetime.combine(monday, time(13))),
        Meeting(title="Ревью задач стажёров", kind="team", organizer_id=maria.id, attendee_id=ivan.id,
                start=datetime.combine(friday, time(15)), end=datetime.combine(friday, time(16))),
    ])
    db.session.add(Note(user_id=arina.id, title="Вводная встреча",
                        body="Договорились, что я прочитаю раздел доступы и сервисы в базе знаний. "
                             "Иван пришлёт полезные материалы."))
    for slug in ("access-how-to-request", "access-base-services"):
        topic = KBTopic.query.filter_by(slug=slug).first()
        db.session.add(TopicProgress(user_id=arina.id, topic_id=topic.id))
    # Дмитрий на третьей неделе: прошедшие 1:1, изученные материалы, цели на стажировку
    for weeks_ago in (2, 1):
        day = today - timedelta(days=7 * weeks_ago)
        day -= timedelta(days=max(0, day.weekday() - 4))
        db.session.add(Meeting(title="1:1 с наставником", kind="mentor", organizer_id=ivan.id, attendee_id=dima.id,
                               start=datetime.combine(day, time(16)), end=datetime.combine(day, time(17))))
    for topic in KBTopic.query.filter(KBTopic.source == "kb", KBTopic.audience == "all").order_by(KBTopic.id).limit(14):
        db.session.add(TopicProgress(user_id=dima.id, topic_id=topic.id))
    from .models import Goal
    db.session.add_all([
        Goal(user_id=dima.id, title="Закрыть 2 задачи из бэклога самостоятельно",
             metric="2 merge request приняты в main", status="done", agreed_by_lead=True),
        Goal(user_id=dima.id, title="Разобраться в релизном процессе и провести релиз с наставником",
             metric="релиз выполнен без откатов", agreed_by_lead=True,
             due=(dima.start_date or today) + timedelta(days=60)),
    ])
    rooms = {}
    for code, name, desc, scope, team, required in CHAT_ROOMS:
        room = ChatRoom(code=code, name=name, description=desc, scope=scope, team=team, required=required)
        db.session.add(room)
        rooms[code] = room
    db.session.flush()
    for code in ("announcements",):
        db.session.add(ChatMembership(user_id=arina.id, room_id=rooms[code].id))
    for code, _, _, _, _, required in CHAT_ROOMS:
        if required:
            db.session.add(ChatMembership(user_id=dima.id, room_id=rooms[code].id))
    next_wed = _next_weekday(today, 2)
    pending = Meeting(title="1:1: разбор комментариев ревью", kind="mentor", status="pending", organizer_id=dima.id,
                      attendee_id=ivan.id, start=datetime.combine(next_wed, time(14)),
                      end=datetime.combine(next_wed, time(15)), agenda="- Комментарии к MR FE-412")
    question = MentorQuestion(intern_id=dima.id, mentor_id=ivan.id,
                              question="Можно ли мержить MR без второго аппрува, если ревьюер в отпуске?")
    db.session.add_all([pending, question])
    db.session.commit()
    from .services.calendar import fmt_dt
    from .services.notify import notify
    notify(ivan, f"{dima.full_name} предлагает встречу «{pending.title}» — {fmt_dt(pending.start)}", "/meetings",
           dedup_key=f"meeting:{pending.id}")
    from .models import AssignedMaterial, MaterialTemplate, TemplateArticle
    templates = []
    for title, desc, articles in MATERIAL_TEMPLATES:
        tpl = MaterialTemplate(title=title, description=desc)
        tpl.articles = [TemplateArticle(category=c, title=t, url=u, minutes=m, order=n)
                        for n, (c, t, u, m) in enumerate(articles)]
        db.session.add(tpl)
        templates.append(tpl)
    db.session.flush()
    for intern, read in ((arina, 1), (dima, 3)):  # наставник выдал подборку Frontend обоим стажёрам
        for n, a in enumerate(templates[0].articles):
            db.session.add(AssignedMaterial(intern_id=intern.id, assigned_by=ivan.id, template_id=templates[0].id,
                                            category=a.category, title=a.title, url=a.url, minutes=a.minutes,
                                            done=n < read, done_at=now() if n < read else None))
    db.session.commit()
    review_task = ChecklistTask.query.filter_by(title="Разобрать комментарии ревью с наставником").first()
    notify(ivan, f"{dima.full_name} просит подтвердить задачу «{review_task.title}»", f"/team/intern/{dima.id}",
           dedup_key=f"task-confirm:{dima.id}:{review_task.id}")
    notify(ivan, f"Новый вопрос от {dima.full_name}: «{question.question[:80]}»", "/team/questions",
           dedup_key=f"question:{question.id}")
    ensure_flags()
