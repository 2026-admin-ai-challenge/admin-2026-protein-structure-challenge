import pytest
from sqlalchemy import select

from app.awards import scaled
from app.leaderboard import rebuild
from app.models import AuditLog, SpecialAward, Team
from conftest import add_account
from test_worker import scored


def board(client, name="public"):
    response = client.get(f"/api/admin/awards?board={name}")
    assert response.status_code == 200, response.text
    return response.json()


def test_efficiency_scales_score_and_zip_size_into_one_hundredth_to_one(client, db, organizer):
    best = add_account(db, "Best score", "bestscore")
    small = add_account(db, "Smallest zip", "smallestzip")
    worst = add_account(db, "Worst score", "worstscore")
    no_zip = add_account(db, "No zip record", "nozip")
    scored(db, best, 0.9, 0.9, zip_bytes=1000)
    scored(db, small, 0.5, 0.5, zip_bytes=100)
    scored(db, worst, 0.1, 0.1, zip_bytes=10000)
    scored(db, no_zip, 0.7, 0.7)
    rebuild(db)
    db.commit()
    client.cookies.set("admin_session", organizer)

    rows = board(client)["efficiency"]
    # The smallest ZIP gets 0.01, not 0, so it divides like any other team.
    assert [(r["place"], r["team"], r["rank"]) for r in rows] == [
        (1, "Smallest zip", 3), (2, "Best score", 1), (3, "Worst score", 4)]
    assert [r["value"] for r in rows] == pytest.approx([0.505 / 0.01, 1 / 0.1, 0.01 / 1])
    assert (rows[0]["score_scaled"], rows[0]["size_scaled"], rows[0]["size_bytes"]) == (pytest.approx(0.505), 0.01, 100)
    assert scaled(5, 5, 5) == 1.0  # every team the same: no division by zero either


def test_climb_counts_from_the_rank_when_the_first_score_came_in(client, db, organizer):
    early = add_account(db, "Early", "earlyteam")
    middle = add_account(db, "Middle", "middleteam")
    late = add_account(db, "Late", "lateteam")
    scored(db, early, 0.5, 0.1, seconds=0)    # 1st of 1
    scored(db, middle, 0.6, 0.8, seconds=10)  # 1st of 2
    first = scored(db, late, 0.2, 0.3, seconds=20)  # 3rd of 3
    scored(db, late, 0.9, 0.4, seconds=30)
    scored(db, early, 0.55, 0.2, seconds=40)
    rebuild(db)
    db.commit()
    client.cookies.set("admin_session", organizer)

    rows = board(client)["climb"]
    assert [(r["team"], r["rank_then"], r["teams_then"], r["rank"], r["value"]) for r in rows] == [
        ("Late", 3, 3, 1, 2), ("Middle", 1, 2, 2, -1), ("Early", 1, 1, 3, -2)]
    assert (rows[0]["first_submission_id"], rows[0]["score_then"], rows[0]["score"]) == (first.id, 0.2, 0.9)

    # The final board needs the published final ranking and ranks by Private score.
    assert client.get("/api/admin/awards?board=final").status_code == 409
    assert client.patch("/api/admin/competition", json={"is_open": False}).status_code == 200
    assert client.post("/api/admin/leaderboard/finalize").status_code == 200
    final = board(client, "final")["climb"]
    # final_selection best_public: then and now take each team's best Public submission.
    assert [(r["team"], r["rank_then"], r["rank"], r["value"]) for r in final] == [
        ("Middle", 1, 1, 0), ("Late", 2, 2, 0), ("Early", 1, 3, -2)]
    assert final[1]["score_then"] == 0.3 and final[1]["score"] == 0.4


def test_recording_a_winner_keeps_the_numbers_it_was_decided_on(client, db, participant, organizer):
    climber = add_account(db, "Climber", "climberteam")
    other = add_account(db, "Other", "otherteam")
    scored(db, participant, 0.5, 0.5, seconds=0, zip_bytes=500)
    scored(db, other, 0.6, 0.6, seconds=10, zip_bytes=5000)
    scored(db, climber, 0.1, 0.1, seconds=20)
    scored(db, climber, 0.9, 0.9, seconds=30)
    rebuild(db)
    db.commit()
    assert client.get("/api/admin/awards").status_code == 403
    assert client.post("/api/admin/awards/climb", json={"team_id": climber["team_id"]}).status_code == 403
    client.cookies.set("admin_session", organizer)

    assert client.post("/api/admin/awards/best-poster", json={"team_id": climber["team_id"]}).status_code == 404
    assert client.post("/api/admin/awards/climb", json={"team_id": climber["team_id"], "board": "final"}).status_code == 409
    # No ZIP record, so not in the efficiency table; Other went from 1st to 2nd.
    assert client.post("/api/admin/awards/efficiency", json={"team_id": climber["team_id"]}).status_code == 409
    refused = client.post("/api/admin/awards/climb", json={"team_id": other["team_id"]})
    assert refused.status_code == 409 and "오르지 않은" in refused.json()["detail"]

    response = client.post("/api/admin/awards/climb", json={"team_id": climber["team_id"]})
    assert response.status_code == 200, response.text
    recorded = response.json()
    assert (recorded["team"], recorded["board"], recorded["value"], recorded["recorded_by"]) == ("Climber", "public", 2, "organizer")
    assert (recorded["detail"]["rank_then"], recorded["detail"]["rank"]) == (3, 1)
    assert client.post("/api/admin/awards/efficiency", json={"team_id": other["team_id"]}).status_code == 200
    # Recording again replaces the winner of that award only.
    assert client.post("/api/admin/awards/efficiency", json={"team_id": participant["team_id"]}).status_code == 200
    winners = board(client)["recorded"]
    assert (winners["climb"]["team"], winners["efficiency"]["team"]) == ("Climber", participant["team_name"])

    # A later score changes the table but not the record.
    scored(db, other, 0.95, 0.95, seconds=40, zip_bytes=5000)
    rebuild(db)
    db.commit()
    now = board(client)
    assert (now["climb"][0]["team"], now["climb"][0]["rank"], now["climb"][0]["value"]) == ("Climber", 2, 1)
    assert (now["recorded"]["climb"]["value"], now["recorded"]["climb"]["detail"]["rank"]) == (2, 1)
    db.get(Team, climber["team_id"]).name = "Renamed"
    db.commit()
    assert board(client)["recorded"]["climb"]["team"] == "Climber"

    assert client.post("/api/admin/awards/climb/delete").status_code == 200
    assert board(client)["recorded"]["climb"] is None
    assert client.post("/api/admin/awards/climb/delete").status_code == 404
    actions = db.scalars(select(AuditLog.action).order_by(AuditLog.id)).all()
    assert actions == ["award.record"] * 3 + ["award.delete"]
    assert db.scalars(select(SpecialAward.kind)).all() == ["efficiency"]
