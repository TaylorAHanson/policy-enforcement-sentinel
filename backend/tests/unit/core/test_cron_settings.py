"""The scheduled scan settings.

The schedule is the only setting whose effect is invisible for hours after it is
saved, so the failure mode worth guarding is a value that is accepted, stored,
displayed as current, and never actually fires.
"""
from __future__ import annotations

import pytest

from app.core import settings_store
from app.core.config import settings


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    ["0 2 * * *", "*/15 * * * *", "0 2 * * 1", "0 0 1 * *", "  0 2 * * *  "],
)
def test_valid_expressions_are_accepted(expression):
    assert settings_store.validate_cron(expression) is None


def test_blank_is_valid_and_means_no_schedule():
    """Not an error state: it is how an admin turns unattended scanning off."""
    assert settings_store.validate_cron("") is None
    assert settings_store.validate_cron("   ") is None
    assert settings_store.next_cron_runs("") == []


@pytest.mark.parametrize(
    "expression", ["not a cron", "0 2 * *", "99 99 * * *", "* * * * * * * *"]
)
def test_unusable_expressions_are_rejected(expression):
    assert settings_store.validate_cron(expression) is not None


def test_the_wrong_field_count_is_explained_in_the_page_s_own_terms():
    """croniter says "columns ... iterator expression", which explains itself
    rather than the typo, next to a field labelled "five-field cron"."""
    problem = settings_store.validate_cron("0 2 * *")

    assert problem is not None
    assert "got 4" in problem
    assert "column" not in problem.lower()
    assert "iterator" not in problem.lower()


def test_next_runs_are_ordered_and_in_utc():
    runs = settings_store.next_cron_runs("0 2 * * *", count=3)

    assert len(runs) == 3
    assert runs == sorted(runs)
    assert all(r.endswith("+00:00") for r in runs)


# --- Storing ----------------------------------------------------------------


def test_a_bad_expression_is_refused_at_save_rather_than_logged(db_session):
    """Storing it would leave the page showing a schedule that never fires."""
    with pytest.raises(ValueError, match="not a valid cron"):
        settings_store.set_override(db_session, "SENTINEL_CRON_SCHEDULE", "0 2 * *")


def test_a_good_expression_applies_immediately(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", None)

    settings_store.set_override(db_session, "SENTINEL_CRON_SCHEDULE", "0 3 * * *")

    assert settings.SENTINEL_CRON_SCHEDULE == "0 3 * * *"


def test_clearing_the_schedule_is_stored_not_discarded(db_session, monkeypatch):
    """Blank has to survive the round trip, or scheduling cannot be turned off."""
    monkeypatch.setattr(settings, "SENTINEL_CRON_SCHEDULE", "0 3 * * *")

    settings_store.set_override(db_session, "SENTINEL_CRON_SCHEDULE", "")
    db_session.commit()

    assert settings.SENTINEL_CRON_SCHEDULE == ""
    assert settings_store.get_overrides(db_session)["SENTINEL_CRON_SCHEDULE"] == ""


def test_the_whole_schedule_is_editable(db_session):
    """Exposing the mode but not the schedule gated a feature you could not enable."""
    keys = set(settings_store.FIELDS_BY_KEY)

    assert {
        "SENTINEL_CRON_SCHEDULE",
        "SENTINEL_CRON_WORKSPACE",
        "SENTINEL_CRON_ENV",
        "SENTINEL_CRON_MODE",
    } <= keys


# --- The preview endpoint ---------------------------------------------------


def test_the_preview_shows_when_a_schedule_would_fire(client):
    response = client.get(
        "/api/v1/settings/cron-preview", params={"expression": "0 2 * * *"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["disabled"] is False
    assert len(body["next_runs"]) == 3


def test_the_preview_explains_a_bad_expression(client):
    response = client.get(
        "/api/v1/settings/cron-preview", params={"expression": "nope"}
    )

    body = response.json()
    assert body["valid"] is False
    assert body["error"]
    assert body["next_runs"] == []


def test_the_preview_calls_blank_disabled_rather_than_invalid(client):
    response = client.get("/api/v1/settings/cron-preview", params={"expression": ""})

    body = response.json()
    assert body["valid"] is True
    assert body["disabled"] is True


def test_the_preview_route_is_not_read_as_a_setting_key(client):
    """`/{key}` routes are declared after it; a collision would 404 or worse."""
    response = client.get("/api/v1/settings/cron-preview")
    assert response.status_code == 200
