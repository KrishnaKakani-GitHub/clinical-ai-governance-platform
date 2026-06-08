"""Structured audit logging.

Every tool call emits one JSON line: who / what / when / why / outcome.
This is the healthcare audit-trail requirement made concrete.

PHI NOTE: audit lines record resource *IDs and actions*, never record
*contents* (no names, no observation values). That is PHI minimisation —
the log proves what happened without copying the sensitive payload into a
second place that then also has to be secured.

In production, point this at an append-only / tamper-evident sink (e.g. a
write-once log store), not stdout. stderr is used here so audit output never
collides with the JSON-RPC protocol traffic on stdout (stdio transport).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("fhir_mcp.audit")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)  # NOT stdout (protocol channel)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


def audit(
    *,
    actor: str,
    action: str,
    reason: str,
    target_ids: list[str] | None = None,
    outcome: str = "ok",
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit one structured audit record.

    actor:      who initiated it (agent id / human approver).
    action:     what happened (e.g. 'read_patient', 'approve_write').
    reason:     why (free text the caller supplies).
    target_ids: which records, by ID only (never contents).
    outcome:    'ok' or 'error'.
    """
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "action": action,
        "reason": reason,
        "target_ids": target_ids or [],
        "outcome": outcome,
    }
    if extra:
        record.update(extra)
    _logger.info(json.dumps(record, separators=(",", ":")))
