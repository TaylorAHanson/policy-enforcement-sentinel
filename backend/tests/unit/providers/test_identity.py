"""Telling a person apart from a service principal.

Two rules turn on this: a production job or pipeline running as a human stops
working the day they leave. Getting it wrong in one direction nags people about
correctly-configured workloads; in the other it stays silent about the thing it
exists to find.
"""
from __future__ import annotations

import pytest

from app.providers.databricks import identity


class Stub:
    def __init__(self, **fields):
        self.__dict__.update(fields)


@pytest.mark.parametrize(
    "name",
    ["someone@company.com", "a.b.c@sub.company.co.uk"],
)
def test_an_email_address_is_a_person(name):
    assert identity.owner_type(None, name) == identity.USER


@pytest.mark.parametrize(
    "name",
    [
        "b6f1a5e2-3c4d-4e5f-8a9b-0c1d2e3f4a5b",
        "B6F1A5E2-3C4D-4E5F-8A9B-0C1D2E3F4A5B",
    ],
)
def test_an_application_id_is_a_service_principal(name):
    """Databricks identifies a service principal by its application ID, which is
    a UUID. Nothing else in this position looks like one."""
    assert identity.owner_type(None, name) == identity.SERVICE_PRINCIPAL


def test_the_run_as_object_wins_over_the_name():
    """`run_as` states the type outright. The name is only a fallback for the
    APIs that return a bare string."""
    run_as = Stub(service_principal_name="b6f1a5e2-3c4d-4e5f-8a9b-0c1d2e3f4a5b")
    assert identity.owner_type(run_as, "someone@company.com") == identity.SERVICE_PRINCIPAL

    run_as = Stub(user_name="someone@company.com")
    assert identity.owner_type(run_as, None) == identity.USER


def test_an_unrecognisable_name_is_unknown_rather_than_a_guess():
    """Both rules test for "user" specifically, so an unknown owner leaves them
    quiet. Guessing "user" would flag workloads on no evidence."""
    assert identity.owner_type(None, "etl-service") == identity.UNKNOWN
    assert identity.owner_type(None, "") == identity.UNKNOWN
    assert identity.owner_type(None, None) == identity.UNKNOWN
