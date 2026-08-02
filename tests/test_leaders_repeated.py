"""Leaders report: repeated-songs column and sorting (#585).

The column is the row count of that leader's Top Songs page — distinct songs
the leader has repeated (>= `_LEADER_MIN_SONG_COUNT` distinct services), not
total repeat performances.

The trap this file exists to pin: `query_all_leaders` groups leaders by
`LOWER(COALESCE(song_leader,'Unknown'))` (exact, case-folded) while
`query_leader_top_songs` matches with `LIKE '%name%'` (substring).  Deriving
the new column per-row from the substring query would let one leader's songs
count toward another whose name is a substring of theirs, so the new column
would not line up with the `Services` column beside it.
"""

from __future__ import annotations

import pytest

from worship_catalog.db import Database


@pytest.fixture
def leaders_db(tmp_path):
    """Two leaders where one name is a substring of the other — the trap case."""
    db = Database(str(tmp_path / "leaders.db"))
    db.connect()
    db.init_schema()

    amazing = db.insert_or_get_song("amazing grace", "Amazing Grace")
    holy = db.insert_or_get_song("holy holy holy", "Holy Holy Holy")
    blessed = db.insert_or_get_song("blessed assurance", "Blessed Assurance")

    def service(date: str, leader: str, songs: list[int]) -> None:
        svc = db.insert_or_update_service(date, "AM", f"{date}.pptx", date, song_leader=leader)
        for ordinal, song_id in enumerate(songs, start=1):
            db.insert_service_song(svc, song_id, ordinal=ordinal)

    # "Matt" repeats Amazing Grace (2 services) and sings Holy once.
    service("2026-01-04", "Matt", [amazing, holy])
    service("2026-01-11", "Matt", [amazing])
    # "Matt Smith" — a superstring of "Matt" — repeats Blessed Assurance.
    service("2026-02-01", "Matt Smith", [blessed])
    service("2026-02-08", "Matt Smith", [blessed])
    # A leader who repeats nothing.
    service("2026-03-01", "Dana", [holy])

    yield db
    db.close()


class TestRepeatedSongCount:
    def _by_leader(self, rows: list[dict]) -> dict[str, dict]:
        return {row["leader"]: row for row in rows}

    def test_counts_distinct_repeated_songs_not_performances(self, leaders_db) -> None:
        """Matt repeated one song (Amazing Grace) across two services — count is 1."""
        rows = self._by_leader(leaders_db.query_all_leaders())
        assert rows["Matt"]["repeated_song_count"] == 1

    def test_leader_who_repeats_nothing_counts_zero(self, leaders_db) -> None:
        rows = self._by_leader(leaders_db.query_all_leaders())
        assert rows["Dana"]["repeated_song_count"] == 0

    def test_substring_leader_names_do_not_bleed(self, leaders_db) -> None:
        """The documented trap: `LIKE '%Matt%'` also matches `Matt Smith`.

        If the column were derived from query_leader_top_songs, Matt would
        inherit Matt Smith's repeated song and report 2.
        """
        rows = self._by_leader(leaders_db.query_all_leaders())
        assert rows["Matt"]["repeated_song_count"] == 1, (
            "Matt must not absorb Matt Smith's repeated songs — the column has to "
            "use the same exact grouping key as the Services column beside it"
        )
        assert rows["Matt Smith"]["repeated_song_count"] == 1

    def test_column_agrees_with_the_services_column(self, leaders_db) -> None:
        """Both numbers must describe the same set of services."""
        rows = self._by_leader(leaders_db.query_all_leaders())
        assert rows["Matt"]["service_count"] == 2
        assert rows["Matt Smith"]["service_count"] == 2

    def test_matches_the_top_songs_page_row_count_for_an_unambiguous_name(
        self, leaders_db
    ) -> None:
        """For a name that is nobody's substring, the two must agree exactly."""
        rows = self._by_leader(leaders_db.query_all_leaders())
        top_songs = leaders_db.query_leader_top_songs("Dana", min_count=2)
        assert rows["Dana"]["repeated_song_count"] == len(top_songs)


class TestLeadersSorting:
    def test_default_order_is_unchanged(self, leaders_db) -> None:
        """First load must look the same as before: most services first."""
        rows = leaders_db.query_all_leaders()
        counts = [row["service_count"] for row in rows]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.parametrize(
        "column", ["leader", "service_count", "repeated_song_count"]
    )
    def test_every_column_is_sortable(self, leaders_db, column: str) -> None:
        """A table where only one header is clickable reads as a bug."""
        ascending = leaders_db.query_all_leaders(sort=column, sort_dir="ASC")
        descending = leaders_db.query_all_leaders(sort=column, sort_dir="DESC")
        assert [row[column] for row in ascending] == sorted(
            row[column] for row in ascending
        )
        assert [row[column] for row in descending] == sorted(
            (row[column] for row in descending), reverse=True
        )

    def test_ties_break_stably_on_leader_name(self, leaders_db) -> None:
        """Many leaders share a count (especially 0); rows must not shuffle."""
        first = leaders_db.query_all_leaders(sort="repeated_song_count", sort_dir="DESC")
        second = leaders_db.query_all_leaders(sort="repeated_song_count", sort_dir="DESC")
        assert [row["leader"] for row in first] == [row["leader"] for row in second]
        tied = [row["leader"] for row in first if row["repeated_song_count"] == 1]
        assert tied == sorted(tied), "tied rows should fall back to leader name"

    def test_invalid_sort_column_is_rejected(self, leaders_db) -> None:
        """The allowlist is what keeps ORDER BY off an f-string (S608)."""
        with pytest.raises(ValueError, match="Invalid sort column"):
            leaders_db.query_all_leaders(sort="leader; DROP TABLE services--")

    def test_invalid_sort_direction_is_rejected(self, leaders_db) -> None:
        with pytest.raises(ValueError, match="Invalid sort direction"):
            leaders_db.query_all_leaders(sort="leader", sort_dir="; DROP TABLE services--")


class TestLeadersPage:
    """Route and markup for the new column (#585)."""

    @pytest.fixture
    def client(self, db_with_songs, tmp_path, monkeypatch):
        from importlib import reload

        from starlette.testclient import TestClient

        inbox = tmp_path / "inbox"
        inbox.mkdir()
        monkeypatch.setenv("DB_PATH", str(db_with_songs))
        monkeypatch.setenv("INBOX_DIR", str(inbox))
        import worship_catalog.web.app as app_module

        reload(app_module)
        return TestClient(app_module.app)

    def test_page_renders_the_new_column(self, client) -> None:
        html = client.get("/leaders").text
        assert "Repeated Songs" in html

    def test_every_header_is_sortable(self, client) -> None:
        """One clickable header among three reads as a bug."""
        html = client.get("/leaders").text
        for col in ("leader", "service_count", "repeated_song_count"):
            assert f"sort={col}" in html, f"{col} header is not sortable"

    def test_active_column_exposes_aria_sort(self, client) -> None:
        html = client.get("/leaders?sort=repeated_song_count&sort_dir=asc").text
        assert 'aria-sort="ascending"' in html

    def test_sort_links_toggle_direction(self, client) -> None:
        html = client.get("/leaders?sort=service_count&sort_dir=desc").text
        assert "sort=service_count&sort_dir=asc" in html, (
            "clicking the active column should flip direction, not re-apply it"
        )

    def test_bad_sort_param_falls_back_instead_of_500ing(self, client) -> None:
        response = client.get("/leaders?sort=%3Bdrop%20table%20services--")
        assert response.status_code == 200, (
            "a hand-edited query string must fall back to the default, not error"
        )

    def test_head_is_answered(self, client) -> None:
        assert client.head("/leaders").status_code == 200
