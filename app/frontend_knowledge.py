"""Проверенная редакционная подборка; запуск не требует доступа к сайтам курсов.

Карточки основаны на публичных программах, а не на расшифровках видео.
Стабильные slug позволяют обновлять каталог без потери отметок изучения.
"""
from __future__ import annotations

from .models import KBCategory, KBTopic, TopicProgress, User, db

CATEGORY_SLUG = "frontend"
JS = "https://avito.tech/education/javascript#watch"
PATTERNS = "https://avito.tech/patterns"
REVIEWED = "15.11.2026"

# slug, название, источник, ориентир в программе, аннотация, вопросы для самопроверки, теги
TOPICS = [
    ("fe-js-web", "01. Современный веб и введение в JavaScript", JS, "JavaScript · модуль 1",
     "Знакомство с браузером, обменом данными и средами исполнения JavaScript.",
     ["Как запрос проходит от браузера к серверу и обратно?", "Чем запуск скрипта в браузере отличается от запуска в Node.js?"],
     "javascript js фронтенд frontend браузер веб http node"),
    ("fe-js-data", "02. Данные, область видимости и замыкания", JS, "JavaScript · модуль 2 · части 1–6",
     "Типы данных, числа, BigInt, области видимости, замыкания, поднятие объявлений и преобразования типов.",
     ["Как функция может сохранить доступ к переменной после завершения внешнего вызова?", "В чём различия var, let и const?"],
     "javascript js типы числа bigint замыкание замыкания closure hoisting область видимости"),
    ("fe-js-this", "03. Контекст исполнения и this", JS, "JavaScript · модуль 3 · части 1–3",
     "Контексты исполнения, окружения и управление this с помощью bind, call и apply.",
     ["От чего зависит this при вызове обычной функции?", "Как стрелочная функция получает this?"],
     "javascript js this контекст исполнения bind call apply стрелочная функция"),
    ("fe-js-prototypes", "04. ООП и прототипное наследование", JS, "JavaScript · модуль 4 · части 1–2",
     "Прототипы объектов, цепочки наследования и риски изменения чужих объектов.",
     ["Что происходит при чтении свойства, которого нет у самого объекта?", "Чем отличаются __proto__ и prototype?"],
     "javascript js ооп прототип prototype наследование object"),
    ("fe-js-objects", "05. Конструирование объектов и классы", JS, "JavaScript · модуль 5 · части 1–2",
     "Функции-конструкторы, оператор new и классы JavaScript.",
     ["Какие действия выполняет new?", "Как классы связаны с прототипной моделью JavaScript?"],
     "javascript js класс class new конструктор объект"),
    ("fe-practice-review", "06. Код-ревью и читаемость", PATTERNS,
     "Паттерны и практики · сезон 1 · уроки 1–3",
     "Читаемость, устройство кода, вложенность и комментарии.",
     ["Как назвать функцию, чтобы было понятно её назначение?", "Как уменьшить вложенность без изменения поведения?"],
     "фронтенд frontend читаемость качество рефакторинг комментарии вложенность"),
    ("fe-practice-errors", "07. Работа с исключениями", PATTERNS,
     "Паттерны и практики · сезон 1 · урок 4",
     "Выбор подхода к исключениям при проектировании кода.",
     ["Какие ошибки нужно обработать рядом с местом возникновения?", "Как пользователь узнает, что операция не выполнена?"],
     "фронтенд frontend исключения ошибки error exception обработка"),
    ("fe-practice-simple", "08. DRY, KISS и YAGNI", PATTERNS,
     "Паттерны и практики · сезон 2 · уроки 1–2",
     "Повторения в коде и выбор достаточной сложности решения.",
     ["Всегда ли похожие фрагменты нужно объединять?", "Какая часть решения нужна сейчас, а какая появилась на вырост?"],
     "фронтенд frontend dry kiss yagni дублирование простота"),
    ("fe-practice-solid", "09. SOLID и зависимости", PATTERNS,
     "Паттерны и практики · сезон 2 · уроки 4–9",
     "Ответственность компонентов, контракты и передача зависимостей.",
     ["Как разделить получение данных и их отображение?", "Как подменить зависимость при проверке поведения?"],
     "фронтенд frontend solid srp ocp lsp isp dip dependency injection зависимости"),
    ("fe-practice-patterns", "10. Паттерны для расширения кругозора", PATTERNS,
     "Паттерны и практики · сезон 3 · уроки 5–6 и 8",
     "Адаптер, фасад, декоратор, стратегия и состояние как варианты организации кода.",
     ["Как изолировать внешний API от остального приложения?", "Когда отдельная стратегия проще набора условий?"],
     "фронтенд frontend паттерн adapter facade decorator strategy state архитектура"),
    ("fe-github-course", "11. Дополнительные материалы JS-курса",
     "https://github.com/avito-tech/js-course/blob/main/materials.md", "GitHub · avito-tech/js-course · materials.md",
     "Навигатор авторов курса: устройство веба, Node.js и детали движка V8. Это подборка внешних ссылок, а не самостоятельная учебная платформа.",
     ["Какая ссылка помогает разобраться с текущим вопросом?", "Кто автор выбранного материала и когда он опубликован?"],
     "фронтенд javascript js github v8 node дополнительные материалы"),
    ("fe-github-principles", "12. Принципы разработки AvitoTech",
     "https://github.com/avito-tech/playbook/blob/master/development-principles.md", "GitHub · AvitoTech Playbook · Принципы разработки",
     "Публичный справочник о проектировании, интерфейсах, документации и работе с данными. Правила конкретной команды следует уточнять у наставника.",
     ["Какое правило применимо к твоей первой задаче?", "Какие договорённости нужно дополнительно уточнить в команде?"],
     "фронтенд frontend github playbook принципы разработка документация интерфейс"),
]


def is_frontend_topic(slug: str) -> bool:
    return any(row[0] == slug for row in TOPICS)


def _body(row: tuple, include_videos: bool = True) -> str:
    _, _, url, location, annotation, questions, _ = row
    body = "\n\n".join([
        f"**Где искать:** {location}.",
        annotation,
        f"[Открыть оригинал]({url})",
        "**Как пользоваться:** открой материал в оригинале или выбери площадку просмотра в списке видео.",
        "**Вопросы для самопроверки AI-buddy**\n" + "\n".join(f"- {q}" for q in questions),
        "Сохрани свои выводы и вопросы в заметках к встрече с наставником. "
        "Отметка «изучено» ставится самостоятельно после знакомства с материалом.",
        f"**Источник проверен:** {REVIEWED}. Аннотация составлена AI-buddy по публичной программе или странице. "
        "Видео не расшифрованы; вопросы составлены для этой подборки и не являются заданиями авторов курса. "
        "Оценка 10 минут относится к знакомству с карточкой и самопроверке, без просмотра видео. "
        "Порядок рекомендательный: обязательные задания и сроки определяются отдельно.",
    ])
    if include_videos:
        from .course_videos import lessons_for_topic
        for lesson in lessons_for_topic(row[0]):
            links = " · ".join(f'[{p["name"]}]({p["url"]})' for p in lesson["platforms"])
            body += f'\n\n**{lesson["title"]}**\n\n{lesson["description"]}\n\n{links}'
    return body


def editorial_body(slug: str) -> str | None:
    row = next((row for row in TOPICS if row[0] == slug), None)
    return _body(row, include_videos=False) if row else None


def ensure_frontend_knowledge() -> None:
    """Дополняет как новую, так и существующую БД, не трогая пользовательский прогресс."""
    category = KBCategory.query.filter_by(slug=CATEGORY_SLUG).first()
    if category is None:
        category = KBCategory(slug=CATEGORY_SLUG, title="Frontend · JavaScript и практики", hours=2, order=-1)
        db.session.add(category)
        db.session.flush()
    for order, row in enumerate(TOPICS):
        slug, title, _, _, _, _, tags = row
        topic = KBTopic.query.filter_by(slug=slug).first()
        if topic is None:
            topic = KBTopic(slug=slug, category_id=category.id)
            db.session.add(topic)
        topic.title, topic.body, topic.tags = title, _body(row), tags
        topic.minutes, topic.order, topic.source = 10, order, "kb"
    db.session.commit()
    from .services import kb
    kb._INDEX.clear()


def overview(user: User) -> dict | None:
    """Публичные учебные материалы доступны всем; подборку выделяем в Frontend/Fullstack профилях."""
    position = user.position.casefold().replace("-", "").replace(" ", "")
    if user.role != "intern" or not any(p in position for p in ("frontend", "fullstack", "фронтенд", "фулстэк")):
        return None
    slugs = [row[0] for row in TOPICS]
    topics = KBTopic.query.filter(KBTopic.slug.in_(slugs)).all()
    done = TopicProgress.query.filter(TopicProgress.user_id == user.id,
                                     TopicProgress.topic_id.in_([t.id for t in topics])).count()
    return {"done": done, "total": len(topics), "first": slugs[0], "category": CATEGORY_SLUG}
