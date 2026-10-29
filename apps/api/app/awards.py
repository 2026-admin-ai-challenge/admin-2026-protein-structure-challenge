"""Special awards, worked out from a stored board: Public, or the final board once published.

efficiency: performance for the ZIP size. Each team's score and ZIP size on the board are
min-max scaled into [0.01, 1] over the teams with a ZIP record, and the highest
score' / size' wins. The 0.01 floor keeps the smallest ZIP from dividing by zero.

climb: the biggest rise since a team's first score. The rank "then" is the team's place on
the same board as it stood when its first scored submission finished, among the teams scored
by that moment; the rank "now" is its place on the stored board.

An organizer records the winner of each award; the record keeps that team's row as it was.
"""
import json

from .leaderboard import moment, rank_key, pick, scored_rows, standings
from .models import SpecialAward

KINDS = ("efficiency", "climb")
FLOOR = 0.01


def scaled(value, low, high):
    """Min-max scaling into [FLOOR, 1]. When every team has the same value, all get 1."""
    if high == low:
        return 1.0
    return FLOOR + (1 - FLOOR) * (value - low) / (high - low)


def efficiency(board_rows):
    rows = [(rank, entry, name, sub) for rank, (entry, name, sub) in enumerate(board_rows, 1)
            if sub.size_bytes is not None]
    if not rows:
        return []
    scores = [entry.score for _, entry, _, _ in rows]
    sizes = [sub.size_bytes for _, _, _, sub in rows]
    table = []
    for rank, entry, name, sub in rows:
        score = scaled(entry.score, min(scores), max(scores))
        size = scaled(sub.size_bytes, min(sizes), max(sizes))
        table.append({"team_id": entry.team_id, "team": name, "rank": rank, "submission_id": sub.id,
                      "score": entry.score, "size_bytes": sub.size_bytes,
                      "score_scaled": score, "size_scaled": size, "value": score / size})
    return ordered(table)


def board_at(by_team, until, board, selection):
    """Each team's rank key and score on the board as it stood at `until`."""
    places = {}
    for team_id, subs in by_team.items():
        best, score = pick([s for s in subs if moment(s) <= until], board, selection)
        if best is not None:
            places[team_id] = (rank_key(best, score), score)
    return places


def climb(board_rows, rows, board, selection):
    by_team = {}
    for row in rows:
        by_team.setdefault(row.team_id, []).append(row)
    table = []
    for rank, (entry, name, sub) in enumerate(board_rows, 1):
        subs = by_team.get(entry.team_id)
        if not subs:
            continue
        first = min(subs, key=lambda s: (moment(s), s.id))
        places = board_at(by_team, moment(first), board, selection)
        if entry.team_id not in places:
            continue
        then = sorted(places, key=lambda team_id: places[team_id][0]).index(entry.team_id) + 1
        table.append({"team_id": entry.team_id, "team": name, "rank": rank, "score": entry.score,
                      "first_submission_id": first.id, "first_at": moment(first),
                      "score_then": places[entry.team_id][1], "rank_then": then, "teams_then": len(places),
                      "value": then - rank})
    return ordered(table)


def ordered(table):
    """Award order: the higher value, then the better board rank."""
    table.sort(key=lambda row: (-row["value"], row["rank"]))
    for place, row in enumerate(table, 1):
        row["place"] = place
    return table


def tables(db, board, selection):
    """Both award tables for "public" or "final" (the private board)."""
    stored = "private" if board == "final" else "public"
    board_rows = standings(db, stored)
    return {"efficiency": efficiency(board_rows),
            "climb": climb(board_rows, scored_rows(db), stored, selection)}


def record_view(award):
    if award is None:
        return None
    return {"kind": award.kind, "board": award.board, "team_id": award.team_id, "team": award.team_name,
            "value": award.value, "detail": json.loads(award.detail),
            "recorded_by": award.recorded_by, "recorded_at": award.recorded_at}


def recorded(db):
    return {kind: record_view(db.get(SpecialAward, kind)) for kind in KINDS}


def snapshot(row):
    return json.dumps(row, ensure_ascii=False, default=lambda value: value.isoformat())
