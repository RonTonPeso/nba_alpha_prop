"""Tests for the kalshi_player_aliases CSV seed CLI.

Verifies the upsert behavior: new rows insert, existing rows with
unchanged player_id do nothing, existing rows with changed player_id
update in place.
"""

from pathlib import Path

from sqlmodel import Session, select

from app.data.kalshi_seed_aliases import seed_aliases
from app.db.tables import KalshiPlayerAlias, Player


def _seed_players(session: Session) -> None:
    session.add(Player(player_id=1641705, current_name="Victor Wembanyama"))
    session.add(Player(player_id=1628983, current_name="Shai Gilgeous-Alexander"))
    session.flush()


def _write_csv(tmp_path: Path, rows: list[tuple[str, int]]) -> Path:
    p = tmp_path / "aliases.csv"
    lines = ["kalshi_player_name,player_id"]
    for name, pid in rows:
        lines.append(f"{name},{pid}")
    p.write_text("\n".join(lines) + "\n")
    return p


def test_seed_inserts_new_rows(db_session: Session, tmp_path: Path) -> None:
    _seed_players(db_session)
    csv_path = _write_csv(
        tmp_path,
        [
            ("Victor Wembanyama", 1641705),
            ("Shai Gilgeous-Alexander", 1628983),
        ],
    )

    summary = seed_aliases(db_session, csv_path=csv_path)

    assert summary.csv_rows == 2
    assert summary.inserted == 2
    assert summary.updated == 0
    assert summary.unchanged == 0

    aliases = list(db_session.exec(select(KalshiPlayerAlias)).all())
    assert {a.kalshi_player_name for a in aliases} == {
        "Victor Wembanyama",
        "Shai Gilgeous-Alexander",
    }


def test_seed_is_idempotent_when_csv_unchanged(db_session: Session, tmp_path: Path) -> None:
    _seed_players(db_session)
    csv_path = _write_csv(tmp_path, [("Victor Wembanyama", 1641705)])

    seed_aliases(db_session, csv_path=csv_path)
    summary2 = seed_aliases(db_session, csv_path=csv_path)

    assert summary2.inserted == 0
    assert summary2.unchanged == 1
    assert len(list(db_session.exec(select(KalshiPlayerAlias)).all())) == 1


def test_seed_updates_when_player_id_changes(db_session: Session, tmp_path: Path) -> None:
    """If CSV maps an existing alias name to a different player_id, update."""
    _seed_players(db_session)
    csv_path = _write_csv(tmp_path, [("Victor Wembanyama", 1641705)])
    seed_aliases(db_session, csv_path=csv_path)

    # Edit: same name, different player_id (e.g., correcting a wrong mapping).
    csv_path2 = _write_csv(tmp_path, [("Victor Wembanyama", 1628983)])
    summary = seed_aliases(db_session, csv_path=csv_path2)

    assert summary.updated == 1
    assert summary.inserted == 0
    alias = db_session.get(KalshiPlayerAlias, "Victor Wembanyama")
    assert alias is not None
    assert alias.player_id == 1628983
