from types import SimpleNamespace

from sqlalchemy import select

from app.accounts import sync_sheet
from app.models import AuditLog, User
from app.security import verify


def sign_in(client, name, password):
    return client.post("/api/auth/login", json={"username": name, "password": password})


def change(client, current, new):
    return client.post("/api/auth/password", json={"current_password": current, "new_password": new})


def test_a_team_changes_its_password(client, db, participant):
    teammate = client.cookies.get("admin_session")
    response = change(client, participant["password"], "Our-Own-Pass-1")
    assert response.status_code == 200, response.text
    # This browser stays signed in with a fresh cookie; every other session is signed out.
    assert client.get("/api/auth/me").json()["team_name"] == "Protein Learners"
    client.cookies.clear()
    client.cookies.set("admin_session", teammate)
    me = client.get("/api/auth/me")
    assert me.status_code == 401 and "비밀번호가 변경" in me.json()["detail"]
    client.cookies.clear()
    assert sign_in(client, "Protein Learners", participant["password"]).status_code == 401
    assert sign_in(client, "Protein Learners", "Our-Own-Pass-1").status_code == 200

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "user.change_password"))
    assert (entry.actor, entry.target) == ("Protein Learners", f"user:{participant['id']}")
    assert "Pass" not in (entry.detail or "")


def test_a_password_change_needs_the_current_password_and_a_new_one(client, participant, monkeypatch):
    monkeypatch.setattr("app.security.time", SimpleNamespace(time=lambda: 1_000_000_020.0))  # one rate window
    password = participant["password"]
    assert change(client, "wrong-password", "Our-Own-Pass-1").status_code == 400
    assert change(client, password, "short").status_code == 422
    assert change(client, password, password).status_code == 422
    assert change(client, password, "x" * 129).status_code == 422
    # A stolen session cannot guess its way to the password either.
    for _ in range(9):
        assert change(client, "wrong-password", "Our-Own-Pass-1").status_code == 400
    refused = change(client, "wrong-password", "Our-Own-Pass-1")
    assert refused.status_code == 429 and refused.json()["code"] == "rate_limited"
    assert change(client, password, "Our-Own-Pass-1").status_code == 200  # the right one still works
    client.cookies.clear()
    assert change(client, "Our-Own-Pass-1", "Another-Pass-2").status_code == 401


def test_organizers_change_their_password_on_the_server(client, organizer):
    client.cookies.set("admin_session", organizer)
    response = change(client, "longpassword123", "Another-Pass-2")
    assert response.status_code == 400 and "create_admin" in response.json()["detail"]


def test_a_sheet_sync_keeps_the_team_password_until_organizers_reset_it(client, db, participant, organizer):
    sheet = "team_name,username,password\nProtein Learners,teamlearner,Sheet-Pass-123\n"
    assert change(client, participant["password"], "Our-Own-Pass-1").status_code == 200
    user = db.get(User, participant["id"])
    assert user.password_changed_at is not None

    summary = sync_sheet(db, sheet)
    db.commit()
    assert summary["team_passwords_kept"] == 1 and summary["created"] == 0
    assert verify("Our-Own-Pass-1", user.password_hash) and not verify("Sheet-Pass-123", user.password_hash)

    # A team that forgot its own password gets a temporary one; the sheet manages it again.
    client.cookies.clear()
    client.cookies.set("admin_session", organizer)
    assert client.post(f"/api/admin/users/{user.id}/reset-password").status_code == 200
    db.refresh(user)
    assert user.password_changed_at is None
    summary = sync_sheet(db, sheet)
    db.commit()
    assert "team_passwords_kept" not in summary and summary["updated"] == 1
    assert verify("Sheet-Pass-123", user.password_hash)
