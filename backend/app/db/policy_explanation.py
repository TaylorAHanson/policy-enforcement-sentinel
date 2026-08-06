from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.orm import Mapped

from app.db.base import Base


class PolicyExplanationModel(Base):
    """A generated plain-English reading of a policy, keyed by what it explains.

    The editor generates these on its own now, rather than behind a button, so
    the same policy body would otherwise be sent to the model every time anyone
    opened the tab. Keying on a hash of the content rather than the file name is
    what makes that safe: an explanation is only ever served for the exact Rego
    it was written about, so a cache hit cannot describe a policy that has since
    changed, and a hit is shared across everyone looking at the same version.

    Nothing here is a source of truth. The reviewed explanation is the ``.md``
    committed beside the policy; this is a cache of readings of drafts, and
    dropping the table costs one regeneration each.
    """

    __tablename__ = "policy_explanations"

    content_sha: Mapped[str] = Column(
        String(64),
        primary_key=True,
        comment="SHA-256 of the policy content this explains",
    )
    policy_name: Mapped[str] = Column(
        String, nullable=False, index=True, comment="For debugging and cleanup only"
    )
    explanation: Mapped[str] = Column(Text, nullable=False)
    created_at: Mapped[datetime] = Column(
        DateTime, default=datetime.utcnow, nullable=False
    )
