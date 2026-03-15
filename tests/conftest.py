"""Shared pytest fixtures for worship-catalog tests."""

import pytest
from pathlib import Path
from worship_catalog.db import Database
from worship_catalog.pptx_reader import Slide, SlideText, SlideImage


@pytest.fixture
def db_with_songs(tmp_path):
    """Create a minimal test DB with one service, two songs, and copy events."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.connect()
    db.init_schema()

    song_id1 = db.insert_or_get_song("amazing grace", "Amazing Grace")
    song_id2 = db.insert_or_get_song("how great thou art", "How Great Thou Art")

    edition_id1 = db.insert_or_get_song_edition(
        song_id1, words_by="John Newton", music_by=None, arranger=None
    )
    edition_id2 = db.insert_or_get_song_edition(
        song_id2, words_by="Stuart K. Hine", music_by="Stuart K. Hine", arranger=None
    )

    service_id = db.insert_or_update_service(
        service_date="2026-02-15",
        service_name="AM Worship",
        source_file="test.pptx",
        source_hash="abc123",
        song_leader="Matt",
    )

    db.insert_service_song(service_id, song_id1, ordinal=1, song_edition_id=edition_id1)
    db.insert_service_song(service_id, song_id2, ordinal=2, song_edition_id=edition_id2)

    db.insert_or_get_copy_event(service_id, song_id1, "projection", song_edition_id=edition_id1)
    db.insert_or_get_copy_event(service_id, song_id2, "projection", song_edition_id=edition_id2)

    db.close()
    return db_path


@pytest.fixture
def db(db_with_songs):
    """Connected Database object pointing at the same test DB used by the client fixture."""
    database = Database(db_with_songs)
    database.connect()
    database.init_schema()
    yield database
    database.close()


def make_slide(
    index: int = 0,
    lines: list[str] | None = None,
    hidden: bool = False,
    image_blobs: list[bytes | None] | None = None,
) -> Slide:
    """Factory for creating test Slide objects without a real PPTX file."""
    text = SlideText(text_lines=lines or [])
    images = []
    if image_blobs:
        for i, blob in enumerate(image_blobs):
            images.append(SlideImage(shape_id=i + 1, blob=blob))
    return Slide(index=index, hidden=hidden, text=text, images=images)
