from __future__ import annotations


def import_all_models() -> None:
    """Register every ORM table on Base.metadata (Alembic and test fixtures need the full set)."""
    from toolgate.audit import models as _audit  # noqa: F401
    from toolgate.auth import models as _auth  # noqa: F401
    from toolgate.policy import models as _policy  # noqa: F401
    from toolgate.registry import models as _registry  # noqa: F401
