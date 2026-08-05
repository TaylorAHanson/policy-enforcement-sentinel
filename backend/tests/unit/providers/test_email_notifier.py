"""Email delivery for WARN, the action almost everything downgrades to.

WARN is the effective action for nearly every finding, because enforcement ships
off. That makes this the most-exercised side effect in the system and makes an
unreported delivery failure worse than it looks: the audit row would say the
owner was told when nobody was.

No SMTP server is contacted. ``smtplib.SMTP`` is replaced with a recorder.
"""
from __future__ import annotations

import smtplib

import pytest

from app.core.config import settings
from app.providers.notifications import email as email_module
from app.providers.notifications.email import EmailNotifier


class FakeSMTP:
    """Records what would have been sent."""

    sent = []
    logins = []
    started_tls = []
    raise_on_connect = None

    def __init__(self, server, port):
        if FakeSMTP.raise_on_connect:
            raise FakeSMTP.raise_on_connect
        self.server = server
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        FakeSMTP.started_tls.append(True)

    def login(self, username, password):
        FakeSMTP.logins.append((username, password))

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.sent = []
    FakeSMTP.logins = []
    FakeSMTP.started_tls = []
    FakeSMTP.raise_on_connect = None
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def notifier(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "", raising=False)
    return EmailNotifier()


# --- Warnings ---------------------------------------------------------------


def test_a_warning_names_the_resource_and_the_reason(notifier, fake_smtp):
    assert notifier.send_warning("owner@company.com", "cluster-7", "No owner tag.")

    message = fake_smtp.sent[0]
    assert message["To"] == "owner@company.com"
    assert "cluster-7" in message["Subject"]
    assert "No owner tag." in message.get_payload()[0].get_payload()


@pytest.mark.parametrize("owner", ["", None, "unknown"])
def test_an_unknown_owner_reports_failure_rather_than_pretending(notifier, owner):
    """A resource with no owner is a real gap. Returning True would hide it."""
    assert notifier.send_warning(owner, "cluster-7", "No owner tag.") is False


def test_an_smtp_failure_is_reported_not_swallowed(notifier, fake_smtp):
    """The audit row must not claim the owner was told when they were not."""
    fake_smtp.raise_on_connect = smtplib.SMTPConnectError(421, "unavailable")

    assert notifier.send_warning("owner@company.com", "cluster-7", "x") is False


def test_an_smtp_failure_does_not_raise(notifier, fake_smtp):
    """A dead mail server must not abort a scan of thousands of resources."""
    fake_smtp.raise_on_connect = OSError("connection refused")

    notifier.send_warning("owner@company.com", "cluster-7", "x")


def test_credentials_are_only_used_when_configured(monkeypatch, fake_smtp):
    """Local development runs against an unauthenticated catcher on :1025."""
    monkeypatch.setattr(settings, "SMTP_USERNAME", "", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "", raising=False)
    EmailNotifier().send_warning("owner@company.com", "c1", "x")

    assert fake_smtp.logins == []
    assert fake_smtp.started_tls == []


def test_tls_is_started_before_authenticating(monkeypatch, fake_smtp):
    """Credentials must never cross the wire in the clear."""
    monkeypatch.setattr(settings, "SMTP_USERNAME", "sentinel", raising=False)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret", raising=False)

    EmailNotifier().send_warning("owner@company.com", "c1", "x")

    assert fake_smtp.started_tls, "logged in without starting TLS"
    assert fake_smtp.logins == [("sentinel", "secret")]


# --- Run reports ------------------------------------------------------------


def body_of(message) -> str:
    return message.get_payload()[0].get_payload()


def test_an_audit_report_says_nothing_was_actually_done(notifier, fake_smtp):
    """Without this line the report reads as a list of actions taken."""
    notifier.send_report(
        "admin@company.com",
        "prod",
        "audit",
        [{"policy": "clusters", "action": "WARN", "resource_id": "c1"}],
    )

    assert "AUDIT MODE ACTIVE" in body_of(fake_smtp.sent[0])


def test_a_remediate_report_omits_the_audit_banner(notifier, fake_smtp):
    notifier.send_report("admin@company.com", "prod", "remediate", [])

    assert "AUDIT MODE ACTIVE" not in body_of(fake_smtp.sent[0])


def test_violations_are_grouped_by_policy(notifier, fake_smtp):
    violations = [
        {"policy": "clusters", "action": "WARN", "resource_id": f"c{i}"}
        for i in range(3)
    ] + [{"policy": "jobs", "action": "WARN", "resource_id": "j1"}]

    notifier.send_report("admin@company.com", "prod", "audit", violations)

    body = body_of(fake_smtp.sent[0])
    assert "Policy: clusters (3 violations)" in body
    assert "Policy: jobs (1 violations)" in body
    assert "Total Violations: 4" in body


def test_a_long_list_is_truncated_with_a_count(notifier, fake_smtp):
    """A report listing ten thousand resources is not a report."""
    violations = [
        {"policy": "clusters", "action": "WARN", "resource_id": f"c{i}"}
        for i in range(50)
    ]

    notifier.send_report("admin@company.com", "prod", "audit", violations)

    body = body_of(fake_smtp.sent[0])
    assert "... and 45 more." in body
    assert "Total Violations: 50" in body


def test_a_clean_report_is_still_sent(notifier, fake_smtp):
    """Silence and "nothing found" have to be distinguishable in the inbox too."""
    assert notifier.send_report("admin@company.com", "prod", "audit", [])
    assert "Total Violations: 0" in body_of(fake_smtp.sent[0])


def test_a_report_with_no_recipient_is_skipped(notifier, fake_smtp):
    assert notifier.send_report("", "prod", "audit", []) is False
    assert fake_smtp.sent == []
