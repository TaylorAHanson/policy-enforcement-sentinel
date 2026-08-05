"""Configuration resolves in three layers, and the safety ones are guarded.

    default_config.py  ->  env / .env  ->  DB (Admin Settings)

Every test here restores the live settings object afterwards, because these
mutate a module-level singleton that the rest of the suite reads.
"""
import pytest

from app.core import settings_store
from app.core.config import settings
from app.core.default_config import DEFAULTS


@pytest.fixture
def restore_settings():
    """Snapshot every editable field and put it back."""
    snapshot = {
        field["key"]: getattr(settings, field["key"], None)
        for field in settings_store.EDITABLE_FIELDS
    }
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


# --- Defaults ---------------------------------------------------------------


def test_enforcement_ships_off():
    """The single most important default in the codebase."""
    assert DEFAULTS["ENFORCEMENT_ENABLED"] is False
    assert DEFAULTS["DESTRUCTIVE_ACTION_WORKSPACES"] == ""
    assert DEFAULTS["SENTINEL_CRON_MODE"] == "audit"


def test_every_editable_field_exists_on_the_settings_object():
    """A field in the UI with no backing attribute silently does nothing."""
    missing = [
        field["key"]
        for field in settings_store.EDITABLE_FIELDS
        if not hasattr(settings, field["key"])
    ]
    assert not missing, "Editable settings with no attribute: " + ", ".join(missing)


def test_the_safety_settings_are_all_marked_dangerous():
    """The UI requires a typed confirmation for anything in this set."""
    expected = {
        "ENFORCEMENT_ENABLED",
        "DESTRUCTIVE_ACTION_WORKSPACES",
        "DESTRUCTIVE_ACTION_MAX_RESOURCES",
        "SENTINEL_CRON_MODE",
    }
    assert expected <= settings_store.DANGER_KEYS


# --- Coercion ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("", False),
        ("nonsense", False),
    ],
)
def test_booleans_coerce_conservatively(raw, expected):
    """Anything unrecognised reads as False, so a typo cannot enable enforcement."""
    field = settings_store.FIELDS_BY_KEY["ENFORCEMENT_ENABLED"]
    assert settings_store._coerce(field, raw) is expected


def test_integers_are_clamped_to_their_declared_range():
    field = settings_store.FIELDS_BY_KEY["DESTRUCTIVE_ACTION_MAX_RESOURCES"]
    assert settings_store._coerce(field, "0") == field["min"]
    assert settings_store._coerce(field, "99999") == field["max"]


def test_an_unparseable_integer_is_ignored_rather_than_guessed():
    field = settings_store.FIELDS_BY_KEY["DESTRUCTIVE_ACTION_MAX_RESOURCES"]
    assert settings_store._coerce(field, "lots") is None


def test_a_select_rejects_a_value_outside_its_options():
    field = settings_store.FIELDS_BY_KEY["SENTINEL_CRON_MODE"]
    assert settings_store._coerce(field, "audit") == "audit"
    assert settings_store._coerce(field, "obliterate") is None


# --- Persistence ------------------------------------------------------------


def test_an_override_applies_immediately(db_session, restore_settings):
    """Call-time readers must see the change without a restart."""
    settings_store.set_override(db_session, "SENTINEL_SCAN_CONCURRENCY", 9, "admin")
    assert settings.SENTINEL_SCAN_CONCURRENCY == 9


def test_an_override_survives_a_reload(db_session, restore_settings):
    settings_store.set_override(db_session, "BRANDING_NAME", "Acme Governance", "admin")
    setattr(settings, "BRANDING_NAME", "something else")

    settings_store.load_overrides(db_session)
    assert settings.BRANDING_NAME == "Acme Governance"


def test_clearing_an_override_falls_back_to_the_env_layer(db_session, restore_settings):
    settings_store.set_override(db_session, "BRANDING_NAME", "Temporary", "admin")
    assert settings.BRANDING_NAME == "Temporary"

    settings_store.clear_override(db_session, "BRANDING_NAME")
    assert settings.BRANDING_NAME == DEFAULTS["BRANDING_NAME"]


def test_setting_something_that_is_not_editable_is_refused(db_session):
    with pytest.raises(ValueError, match="not an editable setting"):
        settings_store.set_override(db_session, "DATABASE_URL", "postgres://", "admin")


def test_an_invalid_value_is_refused_rather_than_stored(db_session, restore_settings):
    with pytest.raises(ValueError):
        settings_store.set_override(db_session, "SENTINEL_CRON_MODE", "obliterate", "a")


def test_rows_for_removed_settings_are_inert(db_session, restore_settings):
    """A setting deleted from the code must not resurrect via an old row."""
    from app.db.app_setting import AppSettingModel

    db_session.add(AppSettingModel(key="SETTING_THAT_NO_LONGER_EXISTS", value="true"))
    db_session.commit()

    overrides = settings_store.get_overrides(db_session)
    assert "SETTING_THAT_NO_LONGER_EXISTS" not in overrides


def test_describe_reports_which_values_are_overridden(db_session, restore_settings):
    settings_store.set_override(db_session, "BRANDING_NAME", "Acme", "admin")
    described = {f["key"]: f for f in settings_store.describe(db_session)}

    assert described["BRANDING_NAME"]["overridden"] is True
    assert described["BRANDING_NAME"]["value"] == "Acme"
    assert described["BRANDING_LOGO_URL"]["overridden"] is False


def test_enabling_enforcement_is_recorded_loudly(db_session, restore_settings, caplog):
    """An audit trail in the log for the setting that matters most."""
    with caplog.at_level("WARNING"):
        settings_store.set_override(
            db_session, "ENFORCEMENT_ENABLED", True, "admin@company.com"
        )

    assert any(
        "SAFETY SETTING CHANGED" in record.message
        and "admin@company.com" in str(record.args)
        for record in caplog.records
    )
