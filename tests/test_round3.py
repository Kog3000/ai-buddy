"""Доработки по ответам организаторов: встречи от наставника, задачи с подтверждением наставника,
база ответов AI-buddy, материалы от наставника, итоговый отчёт, анкета стажёра."""
from datetime import datetime

import pytest

from app.models import ChecklistTask, InternFeedback, Notification, UserTask
from app.permissions import PermissionDenied
from app.services import calendar, checklist, feedback, materials, report

from .conftest import user


def _task(title: str) -> ChecklistTask:
    return ChecklistTask.query.filter_by(title=title).first()


# ------------------------------------------------------------------ встречи: назначает и наставник
def test_mentor_proposes_meeting_and_intern_decides(app):
    arina, ivan, dima = user("arina"), user("ivan"), user("dima")
    slot = calendar.free_slots(arina, ivan, limit=1)[0]
    m = calendar.propose_to_intern(ivan, arina.id, slot, "Разбор задачи", "MR FE-1")
    assert m.status == "pending" and m.organizer_id == ivan.id
    assert calendar.to_dict(m, arina)["status_label"] == "Ждёт твоего подтверждения"
    assert calendar.to_dict(m, ivan)["status_label"] == "Ждёт подтверждения стажёра"
    assert calendar.to_dict(m, arina)["to_me"] and calendar.to_dict(m, ivan)["mine"]
    assert m in calendar.pending_for(arina) and m in calendar.sent_by(ivan)
    with pytest.raises(PermissionDenied):
        calendar.decide(ivan, m.id, True)  # подтверждает приглашённый, а не автор
    calendar.decide(arina, m.id, True, "Буду")
    assert m.status == "accepted"
    assert Notification.query.filter_by(user_id=ivan.id, dedup_key=f"meeting-result:{m.id}").first().link == "/meetings"
    with pytest.raises(PermissionDenied):
        calendar.propose_to_intern(ivan, user("maria").id, slot)
    with pytest.raises(PermissionDenied):
        calendar.propose_to_intern(user("maria"), dima.id, slot)
    m2 = calendar.propose_to_intern(ivan, dima.id, calendar.free_slots(dima, ivan, limit=1)[0])
    assert calendar.cancel(ivan, m2.id).decision_comment == "Приглашение отозвано"


def test_mentor_meeting_api(login, client):
    login("ivan")
    arina_id = user("arina").id
    days = client.get(f"/api/meetings/availability?intern_id={arina_id}").get_json()["days"]
    start = next(d for d in days if d["slots"])["slots"][0]["start"]
    assert client.get(f"/api/meetings/availability?intern_id={user('maria').id}").status_code == 403
    mid = client.post("/api/meetings", json={"start": start, "intern_id": str(arina_id), "title": "1:1"}).get_json()["id"]
    assert "Отправленные приглашения" in client.get("/meetings").get_data(as_text=True)
    login("arina")
    page = client.get("/mentor").get_data(as_text=True)
    assert "Ждёт твоего подтверждения" in page and "Не смогу" in page
    assert client.post(f"/api/meetings/{mid}/decide", json={"accept": False, "comment": "Занята"}).status_code == 200
    login("ivan")
    assert any("не может" in n["text"] for n in client.get("/api/me").get_json()["notifications"])
    bad = client.post("/api/meetings", json={"start": start, "intern_id": "abc"})
    assert bad.status_code == 403


# ------------------------------------------------------------------ задачи, которые отмечает наставник
def test_mentor_confirmed_tasks(app):
    arina, ivan, dima = user("arina"), user("ivan"), user("dima")
    task = _task("Развернуть проект локально")
    assert task.confirm_by == "mentor"
    with pytest.raises(PermissionDenied):
        checklist.set_status(arina, task.id, True)
    ut = checklist.request_confirm(arina, task.id)
    assert ut.status == "review"
    item = next(t for w in checklist.get_checklist(arina)["weeks"] for t in w["tasks"] if t["id"] == task.id)
    assert item["by_mentor"] and item["waiting"] and not item["done"]
    assert any(w["title"] == task.title for w in checklist.waiting_for(ivan))
    with pytest.raises(PermissionDenied):
        checklist.mentor_set(user("maria"), arina, task.id, True)
    checklist.mentor_set(ivan, arina, task.id, True)
    assert UserTask.query.filter_by(user_id=arina.id, task_id=task.id).first().source == "mentor"
    assert Notification.query.filter_by(user_id=arina.id, dedup_key=f"task-done:{arina.id}:{task.id}").first()
    with pytest.raises(ValueError):
        checklist.request_confirm(arina, task.id)  # уже выполнена
    with pytest.raises(ValueError):
        checklist.request_confirm(arina, _task("Изучить процесс code review").id)  # отмечает сам
    with pytest.raises(KeyError):
        checklist.request_confirm(arina, 9999)
    with pytest.raises(KeyError):
        checklist.mentor_set(ivan, dima, 9999, True)
    # авто-закрытие по событиям сервиса работает и для задач наставника
    assert checklist.set_status(arina, task.id, False, source="auto").status == "todo"


def test_mentor_tasks_api_and_pages(login, client, chat):
    task = _task("Развернуть проект локально")
    login("arina")
    assert client.post(f"/api/checklist/{task.id}", json={"done": True}).status_code == 403
    page = client.get("/checklist").get_data(as_text=True)
    assert "Попросить подтвердить" in page and "отмечает наставник" in page
    assert client.post(f"/api/checklist/{task.id}/request-confirm").status_code == 200
    assert client.post("/api/checklist/9999/request-confirm").status_code == 404
    assert "ждёт подтверждения наставника" in client.get("/checklist").get_data(as_text=True)
    # бот: «готово» по задаче наставника превращается в запрос подтверждения
    other = _task("Выполнить первую задачу и отправить MR на ревью")
    assert "Отправил ему запрос" in chat(action="task_done", params={"task_id": other.id})["text"]
    assert "уже отправлен" in chat(action="task_done", params={"task_id": other.id})["text"]
    login("ivan")
    arina_id = user("arina").id
    page = client.get(f"/team/intern/{arina_id}").get_data(as_text=True)
    assert "Ждут подтверждения" in page and "Развернуть проект локально" in page
    overview = chat("Сводка по стажёрам")
    confirm = next(c for c in overview["cards"] if c["actions"][0]["action"] == "task_confirm")
    assert "отмечена выполненной" in chat(action="task_confirm", params=confirm["actions"][0]["params"])["text"]
    assert client.post(f"/api/interns/{arina_id}/checklist/{task.id}", json={"done": True}).status_code == 200
    assert client.post(f"/api/interns/{arina_id}/checklist/9999", json={"done": True}).status_code == 404
    assert client.post("/api/interns/9999/checklist/1", json={"done": True}).status_code == 404
    login("maria")
    assert client.post(f"/api/interns/{arina_id}/checklist/{task.id}", json={"done": True}).status_code == 403


# ------------------------------------------------------------------ база ответов AI-buddy
def test_answers_base_flow(login, client, chat):
    login("arina")
    chat(action="escalate_confirm", params={"question": "Где взять пропуск на парковку?"})
    login("ivan")
    q = [n for n in client.get("/api/me").get_json()["notifications"] if "парковку" in n["text"]]
    assert q
    from app.models import MentorQuestion
    qid = MentorQuestion.query.filter(MentorQuestion.question.like("%парковку%")).first().id
    client.post(f"/api/mentor/questions/{qid}/answer", json={"answer": "Пропуск выдаёт ресепшен на 1 этаже",
                                                              "publish": True})
    page = client.get("/team/questions").get_data(as_text=True)
    assert "База ответов AI-buddy" in page and "Пропуск выдаёт ресепшен" in page
    login("dima")
    reply = chat("Где взять пропуск на парковку?")
    assert reply["text"].startswith("Похожий вопрос уже задавали наставнику")
    assert not client.get("/api/kb/search?q=парковку").get_json()["results"]
    login("ivan")
    from app.models import KBTopic
    topic_id = KBTopic.query.filter_by(source="answer").first().id
    assert client.delete(f"/api/kb/answers/{topic_id}").status_code == 200
    assert client.delete(f"/api/kb/answers/{topic_id}").status_code == 404


# ------------------------------------------------------------------ материалы от наставника
def test_materials_service(app):
    arina, ivan, elena, dima = user("arina"), user("ivan"), user("elena"), user("dima")
    tpl = materials.create_template(elena, "QA-инженер", "Тестирование")
    art = materials.add_template_article(elena, tpl.id, "Технологии стека", "Pytest docs", "https://docs.pytest.org/")
    with pytest.raises(PermissionDenied):
        materials.create_template(ivan, "X")
    with pytest.raises(PermissionDenied):
        materials.add_template_article(ivan, tpl.id, "", "t", "https://a.b/")
    with pytest.raises(ValueError):
        materials.create_template(elena, " ")
    with pytest.raises(ValueError):
        materials.add_template_article(elena, tpl.id, "", "Статья", "ftp://x")
    with pytest.raises(ValueError):
        materials.add_template_article(elena, tpl.id, "", "", "https://a.b/")
    with pytest.raises(LookupError):
        materials.add_template_article(elena, 999, "", "t", "https://a.b/")
    added = materials.assign_template(ivan, arina, tpl.id)
    assert len(added) == 1 and materials.assign_template(ivan, arina, tpl.id) == []
    with pytest.raises(PermissionDenied):
        materials.assign_template(user("maria"), arina, tpl.id)
    with pytest.raises(LookupError):
        materials.assign_template(ivan, arina, 999)
    m = materials.assign_article(ivan, arina, "Для развития", "Статья на Хабре", "https://habr.com/ru/articles/1/")
    with pytest.raises(ValueError):
        materials.assign_article(ivan, arina, "", "Дубль", "https://habr.com/ru/articles/1/")
    with pytest.raises(ValueError):
        materials.assign_article(ivan, arina, "", "", "https://habr.com/ru/articles/2/")
    assert materials.to_dict(m)["host"] == "habr.com"
    with pytest.raises(LookupError):
        materials.mark(dima, m.id, True)
    materials.mark(arina, m.id, True)
    assert materials.stats(arina)["done"] >= 2
    cats = [g["category"] for g in materials.grouped(arina)]
    assert cats.index("Обязательно к прочтению") < cats.index("Для развития")
    materials.remove(ivan, m.id)
    with pytest.raises(LookupError):
        materials.remove(ivan, m.id)
    materials.remove_template_article(elena, art.id)
    with pytest.raises(LookupError):
        materials.remove_template_article(elena, art.id)
    with pytest.raises(PermissionDenied):
        materials.remove_template_article(ivan, 1)


def test_materials_api_and_pages(login, client):
    login("elena")
    assert "Frontend-разработчик" in client.get("/admin/materials").get_data(as_text=True)
    tid = client.post("/api/admin/templates", json={"title": "QA"}).get_json()["id"]
    aid = client.post(f"/api/admin/templates/{tid}/articles",
                      json={"title": "Pytest", "url": "https://docs.pytest.org/", "category": "Технологии стека"}).get_json()["id"]
    assert client.delete(f"/api/admin/articles/{aid}").status_code == 200
    client.post(f"/api/admin/templates/{tid}/articles", json={"title": "Pytest", "url": "https://docs.pytest.org/"})
    login("ivan")
    arina_id = user("arina").id
    page = client.get(f"/team/intern/{arina_id}").get_data(as_text=True)
    assert "Выдать подборку" in page
    assert client.post(f"/api/interns/{arina_id}/materials", json={"template_id": tid}).get_json()["added"] == 1
    mid = client.post(f"/api/interns/{arina_id}/materials",
                      json={"title": "Хабр", "url": "https://habr.com/ru/articles/5/", "category": ""}).get_json()["id"]
    assert client.post(f"/api/interns/{arina_id}/materials", json={"title": "x", "url": "bad"}).status_code == 400
    assert client.post("/api/interns/9999/materials", json={"template_id": tid}).status_code == 404
    login("arina")
    assert "Материалы от наставника" in client.get("/kb").get_data(as_text=True)
    assert client.post(f"/api/materials/{mid}", json={"done": True}).get_json()["done"] is True
    assert any("советует прочитать" in n["text"] for n in client.get("/api/me").get_json()["notifications"])
    login("ivan")
    assert client.delete(f"/api/materials/{mid}").status_code == 200


# ------------------------------------------------------------------ анкета и итоговый отчёт
def test_feedback_service(app):
    arina, ivan = user("arina"), user("ivan")
    with pytest.raises(ValueError):
        feedback.submit(arina, 0, 5, 5)
    with pytest.raises(ValueError):
        feedback.submit(arina, "x", 5, 5)
    with pytest.raises(PermissionDenied):
        feedback.submit(ivan, 5, 5, 5)
    fb = feedback.submit(arina, 5, 4, "5", "Доступы", "Больше примеров")
    assert fb.mentor_support == 5 and InternFeedback.query.count() == 1
    feedback.submit(arina, 4, 4, 4)  # повторная отправка обновляет ответы
    assert InternFeedback.query.count() == 1
    task = next(t for w in checklist.get_checklist(arina)["weeks"] for t in w["tasks"]
                if t["title"] == "Пройти опрос о стажировке")
    assert task["done"] and task["source"] == "auto"
    s = feedback.summary([arina, user("dima")])
    assert s["count"] == 1 and s["of"] == 2 and s["avg"]["easier"] == 4.0
    assert feedback.summary([])["avg"]["easier"] is None


def test_report_and_letter(login, client):
    dima = user("dima")
    r = report.build(user("ivan"), dima)
    assert r["meetings"] == 2 and r["goals_done"] == 1 and r["kb"]["done"] >= 14
    assert "Дмитрий Ким" in r["letter"] and "Сильные стороны" in r["letter"]
    with pytest.raises(PermissionDenied):
        report.build(user("arina"), dima)
    with pytest.raises(PermissionDenied):
        report.save_letter(user("maria"), dima, "текст")
    with pytest.raises(ValueError):
        report.save_letter(user("ivan"), dima, "  ")
    login("dima")
    client.post("/api/feedback", json={"easier": 5, "bot_useful": 4, "mentor_support": 5, "improve": "Шаблоны"})
    assert "Обновить ответы" in client.get("/progress").get_data(as_text=True)
    login("ivan")
    page = client.get(f"/team/intern/{dima.id}/report").get_data(as_text=True)
    assert "Письмо-характеристика" in page and "Шаблоны" in page
    assert client.put(f"/api/interns/{dima.id}/report", json={"letter": "Готовое письмо"}).status_code == 200
    assert "Готовое письмо" in client.get(f"/team/intern/{dima.id}/report").get_data(as_text=True)
    assert "Характеристика стажёра" in client.delete(f"/api/interns/{dima.id}/report").get_json()["letter"]
    assert client.get(f"/team/intern/{user('maria').id}/report").status_code == 403
    m = client.get("/api/metrics").get_json()
    assert m["survey"]["count"] == 1 and m["survey"]["comments"][0]["improve"] == "Шаблоны"
    assert "Обратная связь стажёров" in client.get("/metrics").get_data(as_text=True)
    login("maria")
    page = client.get(f"/team/intern/{dima.id}/report").get_data(as_text=True)
    assert "<pre class=\"letter\">" in page  # руководитель читает, но не редактирует
    login("elena")
    assert client.get(f"/team/intern/{dima.id}/report").status_code == 200


def test_draft_letter_without_goals(app):
    arina = user("arina")
    r = report.build(user("ivan"), arina, today=datetime.now().date())
    assert "цели на стажировку" not in r["letter"]
