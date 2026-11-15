"""Короткие учебные диалоги: поиск, самопроверка, помощь при затруднении."""
from __future__ import annotations

import re
from uuid import uuid4

from ..analytics import flag
from ..textutil import normalize, tokens
from .quiz_bank import BANK, resolve

LEARNING_SUGGESTIONS = ["Что дальше?", "Найди материал по теме", "Проверь мои знания", "Я застрял"]
LEARNING_FLOWS = {"find_material", "quiz", "stuck"}


def reply(*args, **kwargs):
    from .agent import Reply
    return Reply(*args, **kwargs)


def remember(user, value):
    from .agent import _set_state
    _set_state(user, value)


def source(topic):
    return {"slug": topic["slug"], "title": topic["title"], "url": f'/kb/topic/{topic["slug"]}'}


def short(text, size=180):
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text).replace("**", "")
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size].rsplit(" ", 1)[0] + "…"


class LearningMixin:
    def _learning_hits(self, query):
        hits = [h for h in self.mcp.call("kb_search", query=query, limit=3)
                if h["score"] >= 3 and h.get("source") != "answer"]
        for hit in hits:
            if hit["slug"].startswith("fe-"):
                topic = self.mcp.call("kb_get_topic", slug=hit["slug"])
                paragraphs = topic["body"].split("\n\n")
                if len(paragraphs) > 1:
                    hit["snippet"] = paragraphs[1]
        return hits

    def _on_find_material(self, text, slots, state):
        query = slots.get("query", "").strip()
        if not query:
            remember(self.user, {"flow": "find_material", "stage": "topic"})
            return reply("По какой теме найти материал? Например, замыкания, this или код-ревью.",
                         suggestions=["Замыкания", "this", "Код-ревью", "Отмена"])
        hits = self._learning_hits(query)
        if not hits:
            remember(self.user, {"flow": "find_material", "stage": "topic"})
            return reply("Не нашёл подходящих материалов. Как можно точнее назвать тему?",
                         suggestions=["Замыкания", "this", "Код-ревью", "Отмена"], meta={"source": "not_found"})
        remember(self.user, {"topic_slug": hits[0]["slug"], "query": query})
        lines = [f'- **{h["title"]}** — {short(h["snippet"])}' for h in hits]
        return reply("Вот материалы по твоей теме:\n" + "\n".join(lines), sources=[source(h) for h in hits],
                     suggestions=["Проверь мои знания", "Я застрял", "Найди материал по теме"],
                     meta={"source": "material_search"})

    def _quiz_topic_prompt(self, message="По какой теме проверим знания?"):
        remember(self.user, {"flow": "quiz", "stage": "topic"})
        return reply(message + " Выбери тему — задам три вопроса с вариантами ответа. Это самопроверка AI-buddy.",
                     suggestions=["Замыкания", "this", "Прототипы", "DRY и KISS", "Отмена"],
                     meta={"stage": "topic"})

    def _quiz_question(self, state):
        slug, index = state["topic_slug"], state["index"]
        topic = self.mcp.call("kb_get_topic", slug=slug)  # права проверяются и на каждом следующем вопросе
        question = BANK[slug][2][index]
        options = "\n".join(f'{i + 1}. {option}' for i, option in enumerate(question["options"]))
        actions = [{"label": str(i + 1), "action": "quiz_answer", "params": {
            "quiz_id": state["quiz_id"], "question": index, "option": i}, "style": "secondary"}
                   for i in range(len(question["options"]))]
        actions.append({"label": "Отмена", "action": "cancel", "params": {}, "style": "secondary"})
        return reply(f'**{BANK[slug][0]} · Вопрос {index + 1} из 3**\n\n{question["text"]}\n{options}\n\n'
                     "Нажми номер ответа или напиши 1, 2 или 3.",
                     cards=[{"type": "confirm", "title": "Твой ответ", "actions": actions}],
                     sources=[source(topic)], meta={"stage": "answer", "question": index})

    def _on_quiz(self, text, slots, state):
        if not slots.get("start") and state.get("flow") == "quiz" and state.get("stage") == "answer":
            question = BANK[state["topic_slug"]][2][state["index"]]
            choice = normalize(text).strip().rstrip(".! ")
            index = next((i for i, option in enumerate(question["options"])
                          if choice in {str(i + 1), normalize(option)}), None)
            if index is None:
                result = self._quiz_question(state)
                result.text = "Выбери один вариант: 1, 2 или 3. Ответ пока не засчитан.\n\n" + result.text
                return result
            return self._grade_quiz(state, index)
        if not slots.get("start") and state.get("flow") == "quiz" and state.get("stage") == "feedback":
            if normalize(text).strip() in {"дальше", "следующий вопрос"}:
                return self._act_quiz_next({"quiz_id": state["quiz_id"], "question": state["index"]})
            return self._quiz_next_reply(state)
        query = slots.get("query", "").strip()
        slug = resolve(query) if query else state.get("topic_slug")
        if query and slug is None:
            return self._quiz_topic_prompt("По этой теме пока нет подготовленной проверки.")
        if slug not in BANK:
            return self._quiz_topic_prompt()
        self.mcp.call("kb_get_topic", slug=slug)
        current = {"flow": "quiz", "stage": "answer", "topic_slug": slug, "quiz_id": uuid4().hex,
                   "index": 0, "answers": []}
        remember(self.user, current)
        return self._quiz_question(current)

    def _quiz_state(self, params, stage):
        from .agent import _state
        state = _state(self.user).get()
        if (state.get("flow") != "quiz" or state.get("stage") != stage
                or params.get("quiz_id") != state.get("quiz_id")
                or params.get("question") != state.get("index")):
            return None
        return state

    def _stale_quiz(self):
        return reply("Эта кнопка относится к завершённому вопросу. Используй последний вопрос или начни новую проверку.",
                     suggestions=["Проверь мои знания"], meta={"error": True})

    def _act_quiz_answer(self, params):
        state = self._quiz_state(params, "answer")
        if state is None:
            return self._stale_quiz()
        choice = params.get("option")
        if type(choice) is not int or choice not in range(3):
            return self._quiz_question(state)
        return self._grade_quiz(state, choice)

    def _quiz_next_reply(self, state):
        return reply("Разбор ответа сохранён. Продолжим проверку?", cards=[{
            "type": "confirm", "title": "Следующий вопрос", "actions": [
                {"label": "Следующий вопрос", "action": "quiz_next", "params": {
                    "quiz_id": state["quiz_id"], "question": state["index"]}, "style": "primary"},
                {"label": "Отмена", "action": "cancel", "params": {}, "style": "secondary"}]}],
            meta={"stage": "feedback"})

    def _grade_quiz(self, state, choice):
        slug = state["topic_slug"]
        topic = self.mcp.call("kb_get_topic", slug=slug)
        question = BANK[slug][2][state["index"]]
        correct = choice == question["correct"]
        feedback = ("Верно. " if correct else f'Правильный вариант — {question["correct"] + 1}. ') + question["explanation"]
        state["answers"] = [*state["answers"], correct]
        if state["index"] == 2:
            score = sum(state["answers"])
            review = "\n".join(f'- {BANK[slug][2][i]["text"]}' for i, ok in enumerate(state["answers"]) if not ok)
            text = feedback + f"\n\n**Итог: {score} из 3.**"
            text += "\nПовтори по материалу:\n" + review if review else " Можно переходить к практике."
            text += "\nЭто самопроверка: задачи и отметки изучения не менялись."
            remember(self.user, {"topic_slug": slug})
            return reply(text, sources=[source(topic)], suggestions=LEARNING_SUGGESTIONS,
                         meta={"stage": "complete", "score": score, "source": "quiz"})
        state["stage"] = "feedback"
        remember(self.user, state)
        result = self._quiz_next_reply(state)
        result.text = feedback + ("\nПовтори этот момент по материалу ниже." if not correct else "")
        result.sources = [source(topic)]
        return result

    def _act_quiz_next(self, params):
        state = self._quiz_state(params, "feedback")
        if state is None:
            return self._stale_quiz()
        state["index"] += 1
        state["stage"] = "answer"
        remember(self.user, state)
        return self._quiz_question(state)

    def _stuck_draft(self, state):
        parts = ["Нужна помощь: " + state.get("problem", state.get("query", ""))]
        for key, label in (("details", "Ожидаемое и фактическое поведение"), ("attempts", "Уже пробовал(а)")):
            if state.get(key):
                parts.append(f"{label}: {state[key]}")
        return "\n".join(parts)

    def _stuck_escalation(self, state):
        remember(self.user, {"flow": "stuck", "stage": "offered", **{
            k: v for k, v in state.items() if k not in {"flow", "stage"}}})
        if self.user.role != "intern" or not self.user.mentor or not flag("mentor_escalation"):
            return reply("Лучше разобрать этот вопрос с наставником. В профиле пока нет доступного способа передать его из чата.",
                         suggestions=LEARNING_SUGGESTIONS)
        return reply("Собрал контекст. Проверь и при необходимости отредактируй вопрос — отправлю только после подтверждения.",
                     cards=[self._escalate_card(self._stuck_draft(state))], suggestions=["Отмена"])

    def _stuck_material(self, query, state):
        hits = self._learning_hits(query)
        if not hits:
            return self._stuck_escalation({**state, "query": query, "problem": state.get("problem") or query})
        top = hits[0]
        state = {"flow": "stuck", "stage": "helped", "query": query, "topic_slug": top["slug"],
                 "problem": state.get("problem") or query}
        remember(self.user, state)
        # Объяснение берётся из подготовленного разбора, не из выдуманной расшифровки видео.
        bank_slug = resolve(query)
        hint = short(top["snippet"])
        if bank_slug in BANK:
            terms = set(tokens(query))
            ranked = sorted(BANK[bank_slug][2], key=lambda q: len(terms & set(tokens(q["text"] + " " + q["explanation"]))),
                            reverse=True)
            if terms & set(tokens(ranked[0]["text"] + " " + ranked[0]["explanation"])):
                hint = ranked[0]["explanation"]
        return reply(f'Разберём по шагам. {hint}\n\nОткрой **{top["title"]}** и выпиши конкретный пример, '
                     "на котором возникает вопрос. Какой момент в нём непонятен?",
                     sources=[source(h) for h in hits],
                     suggestions=["Всё ещё непонятно", "Проверь мои знания", "Отмена"], meta={"source": "stuck_help"})

    def _on_stuck(self, text, slots, state):
        query = slots.get("query", "").strip()
        continuation = state.get("flow") == "stuck" and not slots.get("start")
        stage = state.get("stage") if continuation else None
        t = normalize(text)
        if stage in {"helped", "detail"}:
            if not query and ("непонятно" in t or "не помог" in t or "не ясно" in t or slots.get("repeat")):
                remember(self.user, {**state, "stage": "detail"})
                return reply("На каком конкретно примере или шаге возник вопрос?", suggestions=["Отмена"])
            return self._stuck_escalation({**state, "details": text.strip()})
        if stage == "task_problem":
            remember(self.user, {**state, "stage": "task_details", "problem": text.strip()})
            return reply("Какой результат ожидал(а) и что получилось вместо него?", suggestions=["Отмена"])
        if stage == "task_details":
            remember(self.user, {**state, "stage": "task_attempts", "details": text.strip()})
            return reply("Что уже пробовал(а), чтобы разобраться?", suggestions=["Отмена"])
        if stage == "task_attempts":
            return self._stuck_escalation({**state, "attempts": text.strip()})
        if stage == "offered":
            return self._stuck_escalation({**state, "details": text.strip()})
        if stage == "context":
            if "рабоч" in t or "задач" in t:
                remember(self.user, {"flow": "stuck", "stage": "task_problem"})
                return reply("Что за рабочая задача и на каком шаге застрял(а)?", suggestions=["Отмена"])
            if "учеб" in t or "темой" in t:
                remember(self.user, {"flow": "stuck", "stage": "learning_topic"})
                return reply("Какую тему разбираешь?", suggestions=["Замыкания", "this", "Прототипы", "Отмена"])
            query = text.strip()
        if stage == "learning_topic":
            query = text.strip()
        if query:
            if any(word in normalize(query) for word in ("рабоч", "задач", "не запуска", "сборк", "ошибка в проекте")):
                remember(self.user, {"flow": "stuck", "stage": "task_details", "problem": text.strip()})
                return reply("Какой результат ожидал(а) и что получилось вместо него?", suggestions=["Отмена"])
            return self._stuck_material(query, {"problem": text.strip()})
        if state.get("topic_slug"):
            topic = self.mcp.call("kb_get_topic", slug=state["topic_slug"])
            return self._stuck_material(topic["title"], {"problem": text.strip()})
        remember(self.user, {"flow": "stuck", "stage": "context"})
        return reply("Давай разберёмся. Ты застрял(а) с учебной темой или с рабочей задачей?",
                     suggestions=["С учебной темой", "С рабочей задачей", "Отмена"])
