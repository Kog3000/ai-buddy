from app.frontend_knowledge import ensure_frontend_knowledge, overview
from app.models import KBTopic, TopicProgress, UserTask, db
from app.services import kb

from .conftest import user


def test_catalog_refresh_preserves_progress_and_does_not_assign_tasks(arina):
    kb.mark_done(arina, "fe-js-data")
    topic = KBTopic.query.filter_by(slug="fe-js-data").one()
    original_id = topic.id
    count, tasks = KBTopic.query.count(), UserTask.query.count()
    kb.search(arina, "замыкания")
    topic.body = "stale"
    db.session.commit()
    ensure_frontend_knowledge()
    ensure_frontend_knowledge()
    assert KBTopic.query.count() == count
    assert UserTask.query.count() == tasks
    assert KBTopic.query.filter_by(slug="fe-js-data").one().id == original_id
    assert TopicProgress.query.filter_by(user_id=arina.id, topic_id=original_id).count() == 1
    assert overview(arina)["done"] == 1
    assert "fe-js-data" in {h.topic.slug for h in kb.search(arina, "замыкания")}


def test_recommendation_is_profile_specific_and_progress_is_personal(arina):
    kb.mark_done(arina, "fe-js-data")
    assert overview(user("dima"))["done"] == 0
    assert overview(user("ivan")) is None
    arina.position = "Full-stack engineer"
    assert overview(arina)["total"] == 12
    arina.position = "Backend engineer"
    assert overview(arina) is None


def test_frontend_pages_explain_source_and_estimates(login, client):
    login("arina")
    assert "Арина, твоя фронтенд-подборка" in client.get("/kb").get_data(as_text=True)
    category = client.get("/kb/frontend").get_data(as_text=True)
    assert "не включает просмотр видео" in category
    topic = client.get("/kb/topic/fe-js-data").get_data(as_text=True)
    assert "https://avito.tech/education/javascript#watch" in topic
    assert "Видео не расшифрованы" in topic
    assert "вопросы составлены для этой подборки" in topic
    assert "на карточку · видео отдельно" in topic
    assert client.post("/api/kb/topics/fe-js-data/done", json={"done": True}).status_code == 200
    assert "1 из 12 изучено" in client.get("/kb").get_data(as_text=True)
