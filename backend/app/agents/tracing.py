"""Optional MLflow tracing, off by default.

Tracing is genuinely useful for debugging a tool loop that took a strange route,
and genuinely expensive to have on by default: it adds a network dependency to
every LLM call and writes prompts, which may quote policy text and resource
names, to an experiment.

So it is opt-in, and every failure here is swallowed. Observability that can
break the thing it observes is worse than no observability.
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_initialized = False
_enabled = False


def init_tracing() -> bool:
    """Turn on autologging if configured. Safe to call repeatedly."""
    global _initialized, _enabled

    if _initialized:
        return _enabled
    _initialized = True

    from app.core.config import settings

    if not settings.MLFLOW_TRACING_ENABLED:
        return False

    try:
        import mlflow

        if settings.MLFLOW_TRACKING_URI:
            mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        if settings.MLFLOW_EXPERIMENT:
            mlflow.set_experiment(settings.MLFLOW_EXPERIMENT)
        mlflow.openai.autolog()
        _enabled = True
        logger.info("MLflow tracing enabled for the policy assistant.")
    except Exception as e:
        logger.warning("MLflow tracing was requested but could not start: %s", e)
        _enabled = False

    return _enabled


def traced(name: str) -> Callable:
    """Wrap an agent capability in an MLflow span when tracing is on."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not init_tracing():
                return await func(*args, **kwargs)

            try:
                import mlflow

                with mlflow.start_span(name=name):
                    return await func(*args, **kwargs)
            except Exception as e:
                # Only reached if starting the span itself fails. The capability
                # still has to run.
                logger.debug("Could not trace %s: %s", name, e)
                return await func(*args, **kwargs)

        return wrapper

    return decorator
