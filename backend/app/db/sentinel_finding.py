from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
)

from app.db.base import Base


class SentinelFindingModel(Base):
    """One policy verdict about one resource.

    Both violations and passing checks are recorded (``kind``), because "we
    looked and it was fine" is materially different from "we never looked", and
    only storing failures makes those indistinguishable.

    The action columns are the visible record of the safety model: what the
    policy asked for, what the chokepoint permitted, and why they differ.
    """

    __tablename__ = "sentinel_findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String, ForeignKey("sentinel_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind = Column(String, nullable=False, comment="violation | check | ws_failure")
    workspace = Column(String, nullable=False, index=True)
    environment = Column(String, nullable=True)

    resource_id = Column(String, nullable=True)
    resource_type = Column(String, nullable=True, index=True)
    resource_name = Column(String, nullable=True)
    owner = Column(String, nullable=True, index=True)

    policy = Column(String, nullable=True, index=True, comment="Rego package name")
    rule_id = Column(String, nullable=True, comment="Rule key within the policy")
    policy_id = Column(String, nullable=True, index=True, comment="Stable ID, e.g. SEC-0001")
    category = Column(String, nullable=True, index=True, comment="security | cost | control")
    severity = Column(String, nullable=True, index=True)
    message = Column(Text, nullable=True)

    # --- The safety record ------------------------------------------------
    requested_action = Column(String, nullable=True, comment="What the policy asked for")
    effective_action = Column(String, nullable=True, comment="What the chokepoint permitted")
    tier = Column(Integer, nullable=True, comment="Tier of the effective action")
    requested_tier = Column(Integer, nullable=True)
    downgrade_reason = Column(Text, nullable=True, comment="Why they differ, in plain language")
    executed = Column(Boolean, nullable=False, default=False)

    #: Lowercased concatenation of the searchable fields, so the dashboard's
    #: free-text filter is one indexed ILIKE instead of an OR across six columns.
    search_text = Column(Text, nullable=True)

    #: The full finding, including the resource snapshot the policy saw.
    data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_findings_run_kind", "run_id", "kind"),
        Index("ix_findings_run_kind_severity", "run_id", "kind", "severity"),
        Index("ix_findings_run_action", "run_id", "effective_action"),
    )

    def build_search_text(self) -> str:
        parts = [
            self.resource_id,
            self.resource_name,
            self.resource_type,
            self.owner,
            self.policy,
            self.policy_id,
            self.rule_id,
            self.message,
            self.workspace,
        ]
        return " ".join(p for p in parts if p).lower()


@event.listens_for(SentinelFindingModel, "before_insert")
@event.listens_for(SentinelFindingModel, "before_update")
def _populate_search_text(mapper, connection, target: SentinelFindingModel) -> None:
    """Keep the denormalised search column in step with the row.

    Derived data maintained by the caller drifts the moment a second write path
    appears, and the failure is quiet: the row saves, and then never matches a
    search. Deriving it here means it cannot be forgotten.
    """
    target.search_text = target.build_search_text()
