"""Сброс должен очищать прогоны и переносить демо на новую дату без потери учебной базы."""
from datetime import date, timedelta

from app.models import AccessRequest, ChatMessage, ChecklistTask, Meeting, User, UserTask, KBTopic, db
from app.services import access, kb


def test_reset_requires_confirmation_and_keeps_data_on_abort(app, arina):
    original_id = arina.id
    db.session.add(ChatMessage(user_id=original_id, role="user", text="Не удалять"))
    db.session.commit()
    runner = app.test_cli_runner()
    assert runner.invoke(args=["reset-demo"], input="n\n").exit_code != 0
    assert ChatMessage.query.filter_by(text="Не удалять").count() == 1
    assert runner.invoke(args=["reset-demo", "--date", "invalid", "--yes"]).exit_code != 0
    assert ChatMessage.query.filter_by(text="Не удалять").count() == 1


def test_reset_rebuilds_dates_and_removes_previous_run(app, arina):
    access.create_request(arina, "jira", "edit", "Задачи первого прогона")
    db.session.add(ChatMessage(user_id=arina.id, role="user", text="Старый чат"))
    db.session.commit()
    kb.search(arina, "доступ")
    target = date.today() + timedelta(days=31)
    result = app.test_cli_runner().invoke(args=["reset-demo", "--yes", "--date", target.isoformat()])
    assert result.exit_code == 0, result.output
    assert target.isoformat() in result.output
    fresh = User.query.filter_by(login="arina").one()
    assert fresh.start_date == target - timedelta(days=2)
    assert fresh.mentor.login == "ivan" and fresh.lead.login == "maria"
    assert AccessRequest.query.count() == 0 and ChatMessage.query.count() == 0
    assert Meeting.query.filter_by(attendee_id=fresh.id).all()
    assert all(m.start.date() > target for m in Meeting.query.filter_by(attendee_id=fresh.id))
    assert UserTask.query.filter_by(user_id=fresh.id, status="done").count() == 3
    assert ChecklistTask.query.count() == 28
    assert KBTopic.query.filter_by(slug="fe-js-data").count() == 1
    assert not kb._INDEX.get("docs")
    assert kb.search(fresh, "замыкания")
    counts = {table.name: db.session.execute(db.select(db.func.count()).select_from(table)).scalar()
              for table in db.metadata.sorted_tables}
    again = app.test_cli_runner().invoke(args=["reset-demo", "--yes", "--date", target.isoformat()])
    assert again.exit_code == 0, again.output
    assert counts == {table.name: db.session.execute(db.select(db.func.count()).select_from(table)).scalar()
                      for table in db.metadata.sorted_tables}


def test_reset_defaults_to_today(app):
    result = app.test_cli_runner().invoke(args=["reset-demo", "--yes"])
    assert result.exit_code == 0, result.output
    assert User.query.filter_by(login="arina").one().start_date == date.today() - timedelta(days=2)
