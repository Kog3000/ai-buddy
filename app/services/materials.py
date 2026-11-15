"""Материалы от наставника: подборки статей по направлениям и персональные ссылки для стажёра.

Подборки (шаблоны) составляет куратор стажировки / методисты. Выдаёт материалы только наставник,
закреплённый за стажёром: целиком подборку по направлению или отдельные статьи (например, с Хабра).
"""
from __future__ import annotations

from urllib.parse import urlparse

from ..analytics import track
from ..models import AssignedMaterial, MaterialTemplate, TemplateArticle, User, db, now
from ..permissions import PermissionDenied
from .notify import notify

CATEGORIES = ["Обязательно к прочтению", "Технологии стека", "Процессы и практики", "Для развития"]


def _check_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Укажи ссылку, начинающуюся с http:// или https://")
    return url


def _check_mentor(mentor: User, intern: User) -> None:
    if intern is None or intern.role != "intern" or intern.mentor_id != mentor.id:
        raise PermissionDenied("Выдавать материалы может только наставник, закреплённый за стажёром")


# ------------------------------------------------------------------ подборки (куратор)
def templates() -> list[MaterialTemplate]:
    return MaterialTemplate.query.order_by(MaterialTemplate.id).all()


def create_template(admin: User, title: str, description: str = "") -> MaterialTemplate:
    if admin.role != "admin":
        raise PermissionDenied("Подборки составляет куратор стажировки")
    title = (title or "").strip()
    if len(title) < 2:
        raise ValueError("Укажи направление подборки")
    t = MaterialTemplate(title=title, description=(description or "").strip())
    db.session.add(t)
    db.session.commit()
    return t


def add_template_article(admin: User, template_id: int, category: str, title: str, url: str,
                         minutes: int = 15) -> TemplateArticle:
    if admin.role != "admin":
        raise PermissionDenied("Подборки составляет куратор стажировки")
    tpl = db.session.get(MaterialTemplate, template_id)
    if tpl is None:
        raise LookupError(template_id)
    if not (title or "").strip():
        raise ValueError("Укажи название статьи")
    art = TemplateArticle(template_id=tpl.id, category=(category or CATEGORIES[0]).strip(), title=title.strip(),
                          url=_check_url(url), minutes=max(1, int(minutes or 15)), order=len(tpl.articles))
    db.session.add(art)
    db.session.commit()
    return art


def remove_template_article(admin: User, article_id: int) -> None:
    if admin.role != "admin":
        raise PermissionDenied("Подборки составляет куратор стажировки")
    art = db.session.get(TemplateArticle, article_id)
    if art is None:
        raise LookupError(article_id)
    db.session.delete(art)
    db.session.commit()


# ------------------------------------------------------------------ выдача стажёру (наставник)
def _add(intern: User, mentor: User, category: str, title: str, url: str, minutes: int,
         template_id: int | None = None) -> AssignedMaterial | None:
    if AssignedMaterial.query.filter_by(intern_id=intern.id, url=url).first():
        return None  # уже выдана
    m = AssignedMaterial(intern_id=intern.id, assigned_by=mentor.id, template_id=template_id, category=category,
                         title=title, url=url, minutes=minutes)
    db.session.add(m)
    return m


def assign_template(mentor: User, intern: User, template_id: int) -> list[AssignedMaterial]:
    _check_mentor(mentor, intern)
    tpl = db.session.get(MaterialTemplate, template_id)
    if tpl is None:
        raise LookupError(template_id)
    added = [m for a in tpl.articles if (m := _add(intern, mentor, a.category, a.title, a.url, a.minutes, tpl.id))]
    db.session.commit()
    if added:
        notify(intern, f"{mentor.full_name} добавил(а) материалы «{tpl.title}» ({len(added)}) — они в базе знаний",
               "/kb#materials", dedup_key=f"materials:{intern.id}:{tpl.id}")
    track(mentor, "materials_template_assigned", template=tpl.title, count=len(added))
    return added


def assign_article(mentor: User, intern: User, category: str, title: str, url: str,
                   minutes: int = 15) -> AssignedMaterial:
    _check_mentor(mentor, intern)
    title = (title or "").strip()
    if not title:
        raise ValueError("Укажи название статьи")
    m = _add(intern, mentor, (category or CATEGORIES[0]).strip(), title, _check_url(url), max(1, int(minutes or 15)))
    if m is None:
        raise ValueError("Эта ссылка уже выдана стажёру")
    db.session.commit()
    notify(intern, f"{mentor.full_name} советует прочитать: «{m.title}»", "/kb#materials",
           dedup_key=f"material:{m.id}")
    track(mentor, "material_assigned")
    return m


def remove(mentor: User, material_id: int) -> None:
    m = db.session.get(AssignedMaterial, material_id)
    if m is None:
        raise LookupError(material_id)
    _check_mentor(mentor, db.session.get(User, m.intern_id))
    db.session.delete(m)
    db.session.commit()


def for_intern(intern: User) -> list[AssignedMaterial]:
    return AssignedMaterial.query.filter_by(intern_id=intern.id).order_by(AssignedMaterial.id).all()


def grouped(intern: User) -> list[dict]:
    """Материалы стажёра по категориям в порядке CATEGORIES, затем прочие."""
    items = for_intern(intern)
    order = CATEGORIES + sorted({m.category for m in items} - set(CATEGORIES))
    result = []
    for cat in order:
        group = [to_dict(m) for m in items if m.category == cat]
        if group:
            result.append({"category": cat, "entries": group, "done": sum(1 for g in group if g["done"])})
    return result


def mark(intern: User, material_id: int, done: bool) -> AssignedMaterial:
    m = db.session.get(AssignedMaterial, material_id)
    if m is None or m.intern_id != intern.id:
        raise LookupError(material_id)
    m.done = bool(done)
    m.done_at = now() if done else None
    db.session.commit()
    track(intern, "material_read" if done else "material_unread")
    return m


def stats(intern: User) -> dict:
    items = for_intern(intern)
    done = sum(1 for m in items if m.done)
    return {"done": done, "total": len(items)}


def to_dict(m: AssignedMaterial) -> dict:
    return {"id": m.id, "category": m.category, "title": m.title, "url": m.url, "minutes": m.minutes,
            "done": m.done, "host": urlparse(m.url).netloc.removeprefix("www.")}
