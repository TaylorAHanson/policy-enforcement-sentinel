"""Builders for the models tests need.

Before these existed, tests constructed rows by hand with every column spelled
out, which meant adding a column broke a dozen unrelated tests and each one
quietly disagreed about what a "normal" row looks like. Every factory takes the
session explicitly, so nothing here can accidentally write to the real
``sentinel.db``.
"""
from tests.factories.allowlist import AllowlistFactory
from tests.factories.audit import EnforcementAuditFactory
from tests.factories.sentinel import SentinelFindingFactory, SentinelRunFactory

__all__ = [
    "AllowlistFactory",
    "EnforcementAuditFactory",
    "SentinelFindingFactory",
    "SentinelRunFactory",
]
