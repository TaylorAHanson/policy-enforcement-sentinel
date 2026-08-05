"""Release notes, including the committed ones.

The parsing tests run against fixtures. The last few run against the real
``docs/release-notes/`` directory, because a front-matter typo in a committed
file produces a release with an empty title in the UI and nothing else catches
it.
"""
from pathlib import Path

import pytest

from app.api.v1.endpoints import release_notes
from app.api.v1.endpoints.release_notes import load_releases, release_notes_dir


@pytest.fixture
def notes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(release_notes, "release_notes_dir", lambda: tmp_path)
    return tmp_path


def write(directory: Path, name: str, text: str) -> None:
    (directory / name).write_text(text, encoding="utf-8")


NOTE = """---
version: 1.0.0
date: 2026-08-04
title: Safety first
highlight: Every policy now starts at WARN.
---

## What changed

The action ladder landed.
"""


# --- Parsing ----------------------------------------------------------------


def test_front_matter_becomes_metadata_and_the_rest_is_the_body(notes_dir):
    write(notes_dir, "1.0.0.md", NOTE)

    release = load_releases()[0]

    assert release.version == "1.0.0"
    assert release.title == "Safety first"
    assert release.highlight == "Every policy now starts at WARN."
    assert release.body.startswith("## What changed")
    assert "---" not in release.body


def test_versions_sort_numerically_not_alphabetically(notes_dir):
    """1.10.0 is newer than 1.9.0. String sorting gets this backwards."""
    for version in ("1.9.0", "1.10.0", "0.1.0", "2.0.0"):
        write(notes_dir, f"{version}.md", f"---\nversion: {version}\n---\nnotes")

    assert [r.version for r in load_releases()] == ["2.0.0", "1.10.0", "1.9.0", "0.1.0"]


def test_files_that_are_not_versions_are_skipped(notes_dir):
    write(notes_dir, "README.md", "How to write release notes.")
    write(notes_dir, "notes.txt", "scratch")
    write(notes_dir, "1.0.0.md", NOTE)

    assert [r.version for r in load_releases()] == ["1.0.0"]


def test_a_note_without_front_matter_still_loads(notes_dir):
    """Degraded, not missing. The version comes from the filename."""
    write(notes_dir, "1.2.3.md", "Just some prose.")

    release = load_releases()[0]
    assert release.version == "1.2.3"
    assert release.title == "Version 1.2.3"
    assert release.body == "Just some prose."


def test_quotes_are_stripped_from_values(notes_dir):
    write(notes_dir, "1.0.0.md", '---\nversion: 1.0.0\ntitle: "Quoted"\n---\nbody')
    assert load_releases()[0].title == "Quoted"


def test_a_missing_directory_yields_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(release_notes, "release_notes_dir", lambda: tmp_path / "gone")
    assert load_releases() == []


# --- Endpoints --------------------------------------------------------------


def test_the_list_endpoint_reports_the_latest_version(client, notes_dir):
    write(notes_dir, "1.0.0.md", NOTE)
    write(notes_dir, "0.1.0.md", "---\nversion: 0.1.0\n---\nolder")

    body = client.get("/api/v1/release-notes").json()

    assert body["latest_version"] == "1.0.0"
    assert body["latest_highlight"] == "Every policy now starts at WARN."
    assert [r["version"] for r in body["releases"]] == ["1.0.0", "0.1.0"]


def test_the_latest_endpoint_omits_the_body(client, notes_dir):
    """The sidebar polls this on every navigation; it should stay small."""
    write(notes_dir, "1.0.0.md", NOTE)

    body = client.get("/api/v1/release-notes/latest").json()

    assert body["version"] == "1.0.0"
    assert "body" not in body


def test_the_latest_endpoint_copes_with_no_releases(client, notes_dir):
    """A fresh deployment must not 500 the sidebar."""
    response = client.get("/api/v1/release-notes/latest")

    assert response.status_code == 200
    assert response.json()["version"] is None


def test_one_release_can_be_fetched_by_version(client, notes_dir):
    write(notes_dir, "1.0.0.md", NOTE)

    body = client.get("/api/v1/release-notes/1.0.0").json()
    assert body["title"] == "Safety first"


def test_an_unknown_version_is_a_404(client, notes_dir):
    assert client.get("/api/v1/release-notes/9.9.9").status_code == 404


# --- The committed notes ----------------------------------------------------


def test_the_committed_release_notes_parse():
    directory = release_notes_dir()
    if not directory.is_dir():
        pytest.skip("Release notes are not deployed beside the backend.")

    releases = load_releases(directory)
    assert releases, f"No release notes parsed from {directory}"

    incomplete = [
        r.version for r in releases if not (r.title and r.date and r.highlight)
    ]
    assert not incomplete, (
        "These releases are missing front matter, so they render with an empty "
        "title in the UI: " + ", ".join(incomplete)
    )


def test_every_committed_release_has_a_body():
    directory = release_notes_dir()
    if not directory.is_dir():
        pytest.skip("Release notes are not deployed beside the backend.")

    empty = [r.version for r in load_releases(directory) if not r.body.strip()]
    assert not empty, "Releases with no body: " + ", ".join(empty)
