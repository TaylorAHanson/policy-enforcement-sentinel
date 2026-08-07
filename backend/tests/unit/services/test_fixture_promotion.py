"""Keeping captures out of the repository, and getting one in on purpose.

A capture is a resource document from somebody's production estate. It is the
most useful kind of test here — the exact spellings and nulls the Databricks API
produces, which is what every dead rule in this release turned out to hinge on —
and it is named after a real catalog, schema and volume.

Both of those follow from the same fact, so the two directories exist to stop
them being traded off against each other: captures are local and ignored,
shipped tests are generic and committed, and promotion is the one door between
them.
"""
import json
import os

import pytest

from app.services import synthetic_estate

# A real Unity Catalog volume, of the shape captured from a live workspace. The
# `VolumeType.MANAGED` spelling is not incidental: a shipped rule compares
# against `"dbfs"` and cannot fire because of it, and that is exactly the kind
# of thing only a capture reveals.
REAL_VOLUME = {
    "id": "psk.genie_space_optimizer.scentre_group_raw_data",
    "name": "scentre_group_raw_data",
    "type": "storage",
    "storage_type": "VolumeType.MANAGED",
    "owner": "owner@example.com",
    "catalog": "psk",
    "schema": "genie_space_optimizer",
    "tags": {},
}


def capture_payload(resource=None, **over):
    payload = {
        "description": "Captured from run abc-123",
        "workspace": "customer-prod-ws",
        "environment": "prod",
        "source": "captured",
        "resource": dict(resource or REAL_VOLUME),
        "expect": {"fires": ["CTL-VOL-003"], "passes": ["SEC-VOL-002"]},
    }
    payload.update(over)
    return payload


@pytest.fixture
def captures(tmp_path):
    directory = tmp_path / "captured"
    directory.mkdir()
    path = directory / "captured_storage_scentre_group_raw_data.json"
    path.write_text(json.dumps(capture_payload()), encoding="utf-8")
    return directory


# --- The two directories ----------------------------------------------------


def test_a_capture_is_written_where_git_ignores_it(monkeypatch, tmp_path):
    """The point of the split. Captures used to land beside the committed tests,
    where they sat untracked in the git panel, one `git add .` from publishing a
    customer's resource names."""
    shipped = tmp_path / "synthetic"
    captured = tmp_path / "captured"
    monkeypatch.setattr(synthetic_estate, "fixtures_dir", lambda: str(shipped))
    monkeypatch.setattr(synthetic_estate, "captures_dir", lambda: str(captured))

    assert synthetic_estate.captures_dir() != synthetic_estate.fixtures_dir()


def test_the_shipped_and_the_local_are_loaded_together(monkeypatch, tmp_path):
    """Running a capture locally is the reason for taking it."""
    shipped = tmp_path / "synthetic"
    shipped.mkdir()
    (shipped / "generic.json").write_text(json.dumps(capture_payload()), encoding="utf-8")
    captured = tmp_path / "captured"
    captured.mkdir()
    (captured / "local.json").write_text(json.dumps(capture_payload()), encoding="utf-8")

    monkeypatch.setattr(synthetic_estate, "fixtures_dir", lambda: str(shipped))
    monkeypatch.setattr(synthetic_estate, "captures_dir", lambda: str(captured))

    names = {f.name for f in synthetic_estate.load_fixtures()}
    assert names == {"generic", "local"}


def test_coverage_can_be_asked_for_the_shipped_set_alone(monkeypatch, tmp_path):
    """Otherwise the coverage number is higher on the laptop that took the
    captures than anywhere the app is deployed, and a number that changes with
    who is looking at it is what this page exists to stop."""
    shipped = tmp_path / "synthetic"
    shipped.mkdir()
    (shipped / "generic.json").write_text(json.dumps(capture_payload()), encoding="utf-8")
    captured = tmp_path / "captured"
    captured.mkdir()
    (captured / "local.json").write_text(json.dumps(capture_payload()), encoding="utf-8")

    monkeypatch.setattr(synthetic_estate, "fixtures_dir", lambda: str(shipped))
    monkeypatch.setattr(synthetic_estate, "captures_dir", lambda: str(captured))

    names = {f.name for f in synthetic_estate.load_fixtures(include_captures=False)}
    assert names == {"generic"}


def test_where_a_test_came_from_is_decided_by_its_directory(monkeypatch, tmp_path):
    """Not by the file's own `source` field, which a capture can claim anything
    in. What matters is whether git will publish it."""
    captured = tmp_path / "captured"
    captured.mkdir()
    (captured / "lying.json").write_text(
        json.dumps(capture_payload(source="handwritten")), encoding="utf-8"
    )
    monkeypatch.setattr(synthetic_estate, "fixtures_dir", lambda: str(tmp_path / "none"))
    monkeypatch.setattr(synthetic_estate, "captures_dir", lambda: str(captured))

    fixture = synthetic_estate.load_fixtures()[0]
    assert fixture.captured is True
    assert fixture.source == "captured"


# --- Scrubbing --------------------------------------------------------------


def test_the_names_are_replaced():
    result = synthetic_estate.scrub(capture_payload())
    resource = result["payload"]["resource"]

    assert "scentre" not in json.dumps(result["payload"]).lower()
    assert resource["catalog"] == "main"
    assert resource["schema"] == "analytics"


def test_the_shape_is_kept():
    """The entire reason to promote a capture rather than write one. The exact
    enum spelling is the evidence that a rule comparing against "dbfs" is dead."""
    result = synthetic_estate.scrub(capture_payload())
    assert result["payload"]["resource"]["storage_type"] == "VolumeType.MANAGED"


def test_a_null_survives():
    """`null` where an author would have assumed the key was absent is the single
    most valuable thing a capture carries."""
    resource = {**REAL_VOLUME, "policy_id": None, "autotermination_minutes": 0}
    result = synthetic_estate.scrub(capture_payload(resource))

    assert result["payload"]["resource"]["policy_id"] is None
    assert result["payload"]["resource"]["autotermination_minutes"] == 0


def test_an_unowned_resource_stays_unowned():
    """The capture anonymiser's old bug, which must not come back here. Replacing
    "unknown" with a valid-looking address turns an unowned resource into an
    owned one and silently inverts the no-owner expectation the file records."""
    result = synthetic_estate.scrub(capture_payload({**REAL_VOLUME, "owner": "unknown"}))
    assert result["payload"]["resource"]["owner"] == "unknown"


def test_a_compound_id_stays_compound():
    """A Unity Catalog id is catalog.schema.name. Scrubbed as one opaque string
    it becomes `id-1`, discarding a structural property any rule that splits an
    id on dots would depend on."""
    result = synthetic_estate.scrub(capture_payload())
    assert result["payload"]["resource"]["id"] == "main.analytics.name-1"


def test_the_run_id_does_not_travel():
    """Not identifying by itself, but it points at one scan of one estate."""
    result = synthetic_estate.scrub(capture_payload())
    assert "abc-123" not in result["payload"]["description"]


def test_an_address_anywhere_is_replaced_even_under_an_unknown_key():
    result = synthetic_estate.scrub(
        capture_payload({**REAL_VOLUME, "some_new_field": "person@customer.com"})
    )
    assert result["payload"]["resource"]["some_new_field"] == synthetic_estate.ANONYMISED_OWNER


# --- Checking its own work --------------------------------------------------


def test_an_identifying_value_under_an_unrecognised_key_is_reported():
    """The important one. IDENTIFYING_KEYS is a guess written against today's
    handlers, and the next handler will emit a key nobody added to it. Rather
    than discover that in a pull request, promotion checks whether any word it
    set out to remove is still present."""
    result = synthetic_estate.scrub(
        capture_payload({**REAL_VOLUME, "parent_volume": "scentre_group_raw_data"})
    )

    assert result["survivors"], "the customer's name is still in the file"
    assert result["survivors"][0]["path"] == "parent_volume"


def test_a_clean_capture_reports_nothing_to_worry_about():
    assert synthetic_estate.scrub(capture_payload())["survivors"] == []


def test_placeholders_do_not_report_themselves():
    """`main` and `analytics` are ordinary words, and a residual check that
    flagged its own substitutions would cry wolf on every promotion."""
    result = synthetic_estate.scrub(capture_payload({**REAL_VOLUME, "catalog": "main"}))
    assert result["survivors"] == []


# --- Promotion --------------------------------------------------------------


def test_promotion_writes_a_file_named_for_what_it_shows(captures, tmp_path):
    """It can no longer be named for a resource, so it is named for the rule it
    demonstrates."""
    target = tmp_path / "synthetic"
    written = run_promote(captures, target)

    assert written["name"] == "real_storage_ctl_vol_003"
    assert os.path.isfile(written["path"])


def test_the_promoted_file_carries_no_trace_of_the_customer(captures, tmp_path):
    target = tmp_path / "synthetic"
    written = run_promote(captures, target)

    with open(written["path"], encoding="utf-8") as handle:
        text = handle.read().lower()

    for token in ("scentre", "psk", "genie_space_optimizer", "customer-prod-ws"):
        assert token not in text, f"{token} survived promotion"


def test_promotion_refuses_when_something_identifying_survives(tmp_path):
    """Fails closed. This is the only path from a real estate into a committed
    file, so it stops rather than writing the file and noting the problem in a
    field nobody reads."""
    captured = tmp_path / "captured"
    captured.mkdir()
    (captured / "c.json").write_text(
        json.dumps(capture_payload({**REAL_VOLUME, "parent_volume": "scentre_group_raw_data"})),
        encoding="utf-8",
    )

    with pytest.raises(synthetic_estate.FixtureError) as e:
        run_promote(captured, tmp_path / "synthetic", name="c")

    assert "parent_volume" in str(e.value), "it says which value it is unhappy about"


def test_promotion_refuses_to_overwrite_a_name_given_by_hand(captures, tmp_path):
    """Derived names get a suffix, so the only way to collide is to ask for a
    name that is already taken."""
    target = tmp_path / "synthetic"
    run_promote(captures, target, target_name="chosen")

    with pytest.raises(synthetic_estate.FixtureError):
        run_promote(captures, target, target_name="chosen")


def test_two_captures_of_the_same_rule_both_survive(captures, tmp_path):
    """Six apps in one workspace break the same rule, so six captures derive the
    same name. They are six different resource documents and worth keeping
    apart, so the second gets a suffix rather than being refused."""
    target = tmp_path / "synthetic"
    first = run_promote(captures, target)
    second = run_promote(captures, target)

    assert first["name"] == "real_storage_ctl_vol_003"
    assert second["name"] == "real_storage_ctl_vol_003_2"


def test_promoting_something_that_is_not_there_says_so(tmp_path):
    with pytest.raises(synthetic_estate.FixtureError):
        run_promote(tmp_path / "captured", tmp_path / "synthetic", name="nope")


def test_the_capture_is_left_alone(captures, tmp_path):
    """Promotion copies. The local capture keeps the real names, which is what
    makes it useful for reading against a live workspace."""
    run_promote(captures, tmp_path / "synthetic")

    remaining = os.listdir(captures)
    assert remaining == ["captured_storage_scentre_group_raw_data.json"]


def run_promote(
    source,
    target,
    name="captured_storage_scentre_group_raw_data",
    target_name=None,
):
    """Promotion without the behaviour check, which needs a running OPA.

    The check itself is covered in the integration suite; everything here is
    about what gets written and what gets refused.
    """
    import asyncio

    return asyncio.run(
        synthetic_estate.promote(
            name,
            directory=str(source),
            target_directory=str(target),
            target_name=target_name,
            verify=False,
        )
    )


# --- Not vouching for a rule that does not work -----------------------------


def test_a_capture_does_not_get_to_endorse_a_broken_rule(monkeypatch):
    """The first capture promoted here asserted that SEC-VOL-001 passes, and
    SEC-VOL-001 compares `storage_type` against "dbfs" while the API sends
    "VolumeType.MANAGED" — it cannot fire at all.

    A capture records what the policies did, so a broken rule looks like a rule
    that passed, and committing that writes a green tick vouching for it. The
    endorsement is dropped rather than the promotion refused: the test keeps
    everything it really demonstrates and simply says nothing about the broken
    rule, which leaves it visibly untested, which is true.
    """
    monkeypatch.setattr(
        "app.services.rule_diagnosis.diagnose",
        lambda **_: {"rules": [{"rule_id": "SEC-VOL-001", "category": "suspect"}]},
    )
    payload = capture_payload()
    payload["expect"]["passes"] = ["SEC-VOL-001", "SEC-VOL-002"]

    withheld = synthetic_estate._withhold_broken_endorsements(payload)

    assert withheld == ["SEC-VOL-001"]
    assert payload["expect"]["passes"] == ["SEC-VOL-002"]


def test_a_working_rule_is_still_endorsed(monkeypatch):
    monkeypatch.setattr(
        "app.services.rule_diagnosis.diagnose",
        lambda **_: {"rules": [{"rule_id": "SEC-VOL-001", "category": "working"}]},
    )
    payload = capture_payload()
    payload["expect"]["passes"] = ["SEC-VOL-001"]

    assert synthetic_estate._withhold_broken_endorsements(payload) == []
    assert payload["expect"]["passes"] == ["SEC-VOL-001"]


def test_what_fires_is_never_withheld(monkeypatch):
    """A rule that fired, fired. That is observed behaviour and the most valuable
    thing the capture holds, whatever the diagnosis thinks of the rule."""
    monkeypatch.setattr(
        "app.services.rule_diagnosis.diagnose",
        lambda **_: {"rules": [{"rule_id": "CTL-VOL-003", "category": "suspect"}]},
    )
    payload = capture_payload()

    synthetic_estate._withhold_broken_endorsements(payload)
    assert payload["expect"]["fires"] == ["CTL-VOL-003"]


def test_promotion_survives_the_diagnosis_being_unavailable(monkeypatch):
    """Advisory, not load-bearing. Promotion should not fail because a coverage
    report could not be computed."""
    def boom(**_):
        raise RuntimeError("no policies loaded")

    monkeypatch.setattr("app.services.rule_diagnosis.diagnose", boom)
    payload = capture_payload()

    assert synthetic_estate._withhold_broken_endorsements(payload) == []
    assert payload["expect"]["passes"] == ["SEC-VOL-002"]


def test_the_resource_type_is_not_mistaken_for_a_leaked_name():
    """A warehouse named "Serverless Starter Warehouse" put "warehouse" on the
    list of words to hunt for, and the check then flagged `type: sql_warehouse`
    and refused to promote a capture that gives away nothing.

    The type is a fixed vocabulary the handler sets, never something a customer
    chose. A false refusal is not harmless — it teaches people the block is
    noise, which is the last thing a safety check can afford.
    """
    result = synthetic_estate.scrub(
        capture_payload(
            {
                "id": "abc",
                "name": "Serverless Starter Warehouse",
                "type": "sql_warehouse",
            }
        )
    )

    assert result["survivors"] == []
    assert result["payload"]["resource"]["type"] == "sql_warehouse"


def test_a_real_leak_is_still_caught_when_it_shares_a_word_with_the_type():
    """The exemption is for the type's own vocabulary, not an amnesty on every
    value that happens to contain one of its words."""
    result = synthetic_estate.scrub(
        capture_payload(
            {
                "id": "abc",
                "name": "scentre_group_raw_data",
                "type": "storage",
                "parent": "scentre_group_raw_data",
            }
        )
    )

    assert [s["path"] for s in result["survivors"]] == ["parent"]
