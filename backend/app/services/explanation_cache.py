"""Generated explanations, kept so the same Rego is only ever explained once.

The editor asks for an explanation whenever the Plain English tab is open and
the policy has changed, rather than when someone presses a button. That is the
right behaviour — an explanation nobody remembered to regenerate is worse than
none, because it is confidently about a policy that no longer exists — but it
means the request arrives on tab switches, on reloads, and once per person
looking at the same draft.

Keying on a hash of the content is what makes that affordable. It also makes it
correct: a hit can only ever be an explanation of exactly the Rego being asked
about, so there is no way to serve a reading of a policy that has since changed.

A miss costs one model call, and losing the whole table costs one call per
distinct policy body. So every failure here is swallowed: the cache is an
optimisation, and an unavailable database should degrade to "slower", never to
"the tab is broken".
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.db.policy_explanation import PolicyExplanationModel

logger = logging.getLogger(__name__)


def _session():
    """Resolved per call so tests can point the factory somewhere else."""
    from app.db.session import get_lakebase_session

    return get_lakebase_session()


def get(sha: str) -> Optional[str]:
    """A previously generated explanation of this exact content, if there is one."""
    try:
        db = _session()
    except Exception as e:
        logger.debug("Explanation cache unavailable for read: %s", e)
        return None

    try:
        row = db.query(PolicyExplanationModel).filter_by(content_sha=sha).one_or_none()
        return row.explanation if row else None
    except Exception as e:
        logger.warning("Could not read the explanation cache: %s", e)
        return None
    finally:
        db.close()


def put(sha: str, policy_name: str, explanation: str) -> None:
    """Store an explanation. Concurrent writers are expected and harmless."""
    if not explanation.strip():
        return

    try:
        db = _session()
    except Exception as e:
        logger.debug("Explanation cache unavailable for write: %s", e)
        return

    try:
        existing = db.query(PolicyExplanationModel).filter_by(content_sha=sha).one_or_none()
        if existing:
            return

        db.add(
            PolicyExplanationModel(
                content_sha=sha,
                policy_name=policy_name,
                explanation=explanation,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception as e:
        # Two people opening the same draft at once race on the primary key.
        # The loser has nothing to do: the row it wanted is now there.
        db.rollback()
        logger.debug("Could not write the explanation cache: %s", e)
    finally:
        db.close()
