from urllib.parse import urlparse

from app.course_videos import catalog, groups, lessons_for_topic
from app.models import KBTopic, TopicProgress
from app.services import kb


def test_scraped_snapshot_has_complete_unique_lessons_and_platforms():
    lessons = catalog()["lessons"]
    assert len(lessons) == 49
    assert len({l["id"] for l in lessons}) == 49
    assert sum(len(l["platforms"]) for l in lessons) == 147
    for lesson in lessons:
        assert lesson["title"] and lesson["description"]
        assert {p["name"] for p in lesson["platforms"]} == {"YouTube", "RuTube", "VK Видео"}
        for platform in lesson["platforms"]:
            url = urlparse(platform["url"])
            assert url.scheme == "https"
            assert url.hostname in {"www.youtube.com", "youtu.be", "rutube.ru", "vkvideo.ru", "vk.com"}
        assert "Cache miss" not in lesson["description"]
    assert [len(g["lessons"]) for g in groups()] == [2, 6, 3, 2, 2, 12, 10, 12]


def test_spatial_source_order_does_not_mix_js_lessons():
    data = lessons_for_topic("fe-js-data")
    assert [l["number"] for l in data] == [1, 2, 3, 4, 5, 6]
    assert "typeof" in data[0]["description"]
    assert "QPU8GdQ2DoE" in data[0]["platforms"][0]["url"]
    assert "Oddball" in data[1]["description"]
    assert "IEEE" in data[2]["description"]
    prototypes = lessons_for_topic("fe-js-prototypes")
    assert "UE5Q8xjzlzQ" in prototypes[1]["platforms"][0]["url"]
    assert lessons_for_topic("fe-github-course") == []


def test_video_routes_and_descriptions_are_available_without_changing_progress(login, client, arina):
    login("arina")
    before = TopicProgress.query.filter_by(user_id=arina.id).count()
    page = client.get("/kb/topic/fe-js-data").get_data(as_text=True)
    assert page.count('class="video-lesson card-lav"') == 6
    assert "QPU8GdQ2DoE" in page and "Oddball" in page
    assert "YouTube ↗" in page and "VK Видео ↗" in page
    assert "Вся видеотека" in page
    all_videos = client.get("/kb/frontend/videos").get_data(as_text=True)
    assert all_videos.count('class="video-lesson card-lav"') == 49
    assert "Low Coupling" in all_videos and "Инструменты конструирования объектов" in all_videos
    assert TopicProgress.query.filter_by(user_id=arina.id).count() == before
    assert "Oddball" in KBTopic.query.filter_by(slug="fe-js-data").one().body
    assert "fe-js-data" in {h.topic.slug for h in kb.search(arina, "Oddball")}
