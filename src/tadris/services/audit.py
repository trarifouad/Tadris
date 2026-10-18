import json
from typing import Any

from tadris.core.context import UserContext


def log(
    conn,
    ctx: UserContext,
    action: str,
    entity: str,
    entity_id: int | None = None,
    old: Any = None,
    new: Any = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log(user_id, action, entity_name, entity_id, old_value, new_value)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            ctx.user_id,
            action,
            entity,
            entity_id,
            None if old is None else json.dumps(old, ensure_ascii=False, default=str),
            None if new is None else json.dumps(new, ensure_ascii=False, default=str),
        ),
    )
