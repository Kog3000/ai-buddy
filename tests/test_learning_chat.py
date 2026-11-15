import pytest

from app.agent.nlu import detect
from app.models import ConversationState, MentorQuestion, TopicProgress, UserTask, db

from .conftest import user


def action(message, name):
    return next(a for c in message["cards"] for a in c.get("actions", []) if a["action"] == name)


def test_material_search(login, chat):
    login("arina")
    assert "тем" in chat("Найди материал по теме")["text"].lower()
    found = chat("замыкания")
    assert found["meta"]["intent"] == "find_material"
    assert 1 <= len(found["sources"]) <= 3
    assert any(s["slug"] == "fe-js-data" for s in found["sources"])
    assert len(found["text"]) < 1500
    assert "Открыть оригинал" not in found["text"]
    assert "rutube.ru/video" not in found["text"]  # не возвращать целиком каталог
    assert chat("Найди материалы по this")["sources"]
    assert detect("Найди материал ошибки").slots["query"] == "ошибки"
    assert detect("Не понимаю события").slots["query"] == "события"


def test_learning_permissions_and_missing_topic(login, chat):
    login("arina")
    result = chat("Найди материал по теме: шкала оценки стажёров")
    assert all(s["slug"] != "mentor-intern-assessment" for s in result["sources"])
    missing = chat("Найди материал по теме: квантовая телепортация фотона")
    assert not missing["sources"] and "не наш" in missing["text"].lower()
    quiz = chat("Проверь мои знания по квантовой телепортации")
    assert quiz["meta"]["stage"] == "topic"
    assert "Вопрос 1" not in quiz["text"]


def test_quiz_journey(login, chat):
    login("arina")
    before_tasks = [(t.id, t.status) for t in UserTask.query.all()]
    before_read = TopicProgress.query.count()
    question = chat("Проверь мои знания по замыканиям")
    assert "Вопрос 1 из 3" in question["text"]
    for index, option in enumerate((1, 2, 0)):
        answer = action(question, "quiz_answer")
        params = {**answer["params"], "option": option}
        reply = chat(action="quiz_answer", params=params)
        if index < 2:
            assert reply["meta"]["stage"] == "feedback"
            next_ = action(reply, "quiz_next")
            question = chat(action="quiz_next", params=next_["params"])
            assert f"Вопрос {index + 2} из 3" in question["text"]
    assert reply["meta"]["stage"] == "complete"
    assert reply["meta"]["score"] == 3
    assert "3 из 3" in reply["text"]
    assert [(t.id, t.status) for t in UserTask.query.all()] == before_tasks
    assert TopicProgress.query.count() == before_read


def test_quiz_invalid_and_stale_actions(login, chat):
    login("arina")
    q = chat("Проверь мои знания по замыканиям")
    params = action(q, "quiz_answer")["params"]
    assert chat("абракадабра")["meta"]["stage"] == "answer"
    assert chat(action="quiz_answer", params={**params, "option": 9})["meta"]["stage"] == "answer"
    feedback = chat("1")
    assert feedback["meta"]["stage"] == "feedback"
    assert "Повтори" in feedback["text"]
    assert chat(action="quiz_answer", params=params)["meta"]["error"]
    next_params = action(feedback, "quiz_next")["params"]
    chat(action="quiz_next", params=next_params)
    assert chat(action="quiz_next", params=next_params)["meta"]["error"]
    assert chat(action="quiz_answer", params=params)["meta"]["error"]


def test_quiz_isolation_and_switch(login, chat):
    login("arina")
    q = chat("Проверь мои знания по замыканиям")
    params = action(q, "quiz_answer")["params"]
    login("dima")
    assert chat(action="quiz_answer", params=params)["meta"]["error"]
    login("arina")
    assert "Вопрос" in chat("Отмена")["text"] or not db.session.get(ConversationState, user("arina").id).get()
    chat("Проверь мои знания по this")
    assert chat("Найди материал по теме: BigInt")["meta"]["intent"] == "find_material"
    assert chat(action="quiz_answer", params=params)["meta"]["error"]


@pytest.mark.parametrize("text", ["Я застрял", "я застряла", "ничего не понял", "ничего не поняла",
                                       "нифига не ясно", "не получается", "запутался", "запуталась",
                                       "не знаю, с чего начать", "вообще не понимаю", "непонятно", "нифига не понял"])
def test_stuck_variants(login, chat, text):
    login("arina")
    assert detect(text).name == "stuck"
    reply = chat(text)
    assert reply["meta"]["intent"] == "stuck"
    assert reply["text"].count("?") == 1


def test_stuck_topic_and_context(login, chat):
    login("arina")
    reply = chat("Ничего не понял в замыканиях")
    assert reply["sources"] and "замык" in reply["text"].lower()
    assert "какую тему" not in reply["text"].lower()
    chat("Отмена")
    chat("Найди материал по теме: замыкания")
    assert chat("Я застрял")["sources"]


def test_stuck_task_and_confirmed_escalation(login, chat):
    login("arina")
    count = MentorQuestion.query.count()
    chat("Я застрял")
    assert "задач" in chat("С рабочей задачей")["text"]
    assert "ожидал" in chat("Не запускается проект")["text"]
    assert "пробовал" in chat("Ожидала запуск, а получила ошибку сборки")["text"]
    final = chat("Переустановила зависимости")
    assert MentorQuestion.query.count() == count
    card = next(c for c in final["cards"] if c.get("fields"))
    draft = card["fields"][0]["value"]
    assert "Не запускается проект" in draft and "Переустановила зависимости" in draft
    sent = chat(action="escalate_confirm", params={"question": draft})
    assert sent["meta"]["source"] == "escalated"
    assert MentorQuestion.query.count() == count + 1


def test_learning_can_switch_to_existing_scenarios(login, chat):
    login("arina")
    chat("Проверь мои знания")
    assert chat("Хочу отгул в пятницу")["meta"]["intent"] == "absence"
    assert chat("Найди материал по теме")["meta"]["intent"] == "find_material"
    chat("Я застрял с доступом к VPN")
    assert chat("Что дальше?")["meta"]["intent"] == "next_steps"


def test_stuck_keeps_specific_question_and_collects_work_context(login, chat):
    login("arina")
    hint = chat("Ничего не понял в BigInt")
    assert "BigInt" in hint["text"] and "целые" in hint["text"]
    assert "лексическому окружению" not in hint["text"]
    detail = chat("Всё ещё непонятно")
    assert "конкретно" in detail["text"]
    draft = chat("Не понимаю разницу между Number и BigInt")
    assert action(draft, "escalate_confirm")
    chat("Отмена")
    inline = chat("Я застрял: не запускается проект")
    assert "ожидал" in inline["text"] and not inline["cards"]


def test_quick_prompts_are_visible_for_existing_chat(login, client, chat):
    login("arina")
    chat("Что дальше?")
    page = client.get("/chat").get_data(as_text=True)
    for prompt in ("Найди материал по теме", "Проверь мои знания", "Я застрял"):
        assert f'data-chat-prompt="{prompt}"' in page
    login("ivan")
    assert 'data-chat-prompt=' not in client.get("/chat").get_data(as_text=True)
