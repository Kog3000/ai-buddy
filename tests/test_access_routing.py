"""Заявка на согласование уходит руководителю того, кто её подал, а не всегда владельцу ресурса."""
import pytest

from app.models import AccessRequest, Notification, Resource, User, db
from app.permissions import PermissionDenied
from app.services import access


def _user(login, role, lead=None):
    u = User(login=login, full_name=login.title(), role=role, team="Команда аналитики",
             password_hash="x", lead_id=lead.id if lead else None)
    db.session.add(u)
    db.session.commit()
    return u


def test_request_goes_to_interns_own_lead(app):
    lead = _user("petr", "lead")
    intern = _user("nina", "intern", lead)
    req = access.create_request(intern, "stash", "read", "Нужно для задач")
    assert req.approver_id == lead.id
    assert "руководитель" in req.approver_label
    assert [r.id for r in access.for_approval(lead)] == [req.id]
    assert Notification.query.filter_by(user_id=lead.id, dedup_key=f"access:{req.id}").count() == 1
    access.decide(lead, req.id, True)
    assert db.session.get(AccessRequest, req.id).status == "granted"


def test_no_lead_falls_back_to_owner(app):
    intern = _user("oleg", "intern")
    req = access.create_request(intern, "stash", "read", "Нужно для задач")
    assert req.approver.login == "maria" and "владелец" in req.approver_label


def test_no_approver_at_all_is_an_error_not_silent(app):
    intern = _user("oleg", "intern")
    Resource.query.filter_by(code="stash").first().owner_id = None
    db.session.commit()
    with pytest.raises(PermissionDenied, match="не назначен руководитель"):
        access.create_request(intern, "stash", "read", "Нужно для задач")
    assert AccessRequest.query.count() == 0


def test_sync_auto_approves_only_policy_resources(app):
    app.config["ACCESS_AUTO_APPROVE_SECONDS"] = 0
    intern = _user("oleg", "intern")
    req = access.create_request(intern, "stash", "read", "Нужно для задач")
    req.approver_id = None  # например, согласующего удалили
    db.session.commit()
    access.sync()
    assert db.session.get(AccessRequest, req.id).status == "pending_approval"
