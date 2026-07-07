"""Principal and approver verification + PHI/DUA enforcement.

Environment variables:
    FHIR_MCP_PRINCIPALS  comma-separated agent actor IDs allowed to call tools
    FHIR_MCP_APPROVERS   comma-separated human IDs allowed to approve/reject
    FHIR_MCP_DUAS        comma-separated actor IDs with a signed Data Use Agreement
    FHIR_MCP_PHI_MODE    'strict' enables DUA gate on all PHI reads (default: off)
    FHIR_MCP_DEV_MODE    'true' explicitly opts into development mode

Fail-closed by default:
    FHIR_MCP_PRINCIPALS, FHIR_MCP_APPROVERS, and FHIR_MCP_DUAS must each be
    set explicitly. Leaving any of them unset raises AuthConfigurationError
    on first use, UNLESS FHIR_MCP_DEV_MODE=true is set. Dev mode disables
    all identity/DUA checks and must never be enabled against real PHI.

Production with real PHI — set all four:
    FHIR_MCP_PRINCIPALS=agent:prod
    FHIR_MCP_APPROVERS=dr.smith,dr.jones
    FHIR_MCP_DUAS=agent:prod          # only actors that signed your institutional DUA
    FHIR_MCP_PHI_MODE=strict

Local development only:
    FHIR_MCP_DEV_MODE=true            # skips all identity/DUA checks

DUA enforcement order (strict mode):
    1. Is actor in FHIR_MCP_PRINCIPALS?  (identity gate)
    2. Is actor in FHIR_MCP_DUAS?        (data use agreement gate)
    Both must pass before any PHI read is allowed.

Keep FHIR_MCP_PRINCIPALS and FHIR_MCP_APPROVERS disjoint:
    An agent principal must not appear in FHIR_MCP_APPROVERS.
"""
from __future__ import annotations

import os

_PHI_MODE = os.environ.get("FHIR_MCP_PHI_MODE", "").strip().lower()
PHI_MODE_STRICT: bool = _PHI_MODE == "strict"

_DEV_MODE_RAW = os.environ.get("FHIR_MCP_DEV_MODE", "").strip().lower()
DEV_MODE: bool = _DEV_MODE_RAW in ("1", "true", "yes")


class AuthError(Exception):
    """Raised when an actor fails any auth or DUA check."""


class AuthConfigurationError(Exception):
    """Raised when auth is unconfigured and dev mode was not explicitly enabled.

    This is a fail-closed guard: an unset FHIR_MCP_PRINCIPALS / APPROVERS /
    DUAS is treated as a misconfiguration, not an implicit bypass. Set
    FHIR_MCP_DEV_MODE=true to opt into the old skip-all-checks behavior for
    local development. Never enable dev mode against real PHI.
    """


def _allowed_set(env_var: str) -> frozenset[str] | None:
    """Return the allowed set, or None only if FHIR_MCP_DEV_MODE=true.

    Raises AuthConfigurationError if the var is unset and dev mode is not
    explicitly enabled. This is the fail-closed behavior: an operator must
    make an affirmative choice (either set the var, or opt into dev mode)
    rather than getting an open system by omission.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        if DEV_MODE:
            return None
        raise AuthConfigurationError(
            f"{env_var} is not set. Auth fails closed by default. "
            f"Set {env_var} explicitly for this deployment, or set "
            "FHIR_MCP_DEV_MODE=true to run in development mode "
            "(never against real PHI)."
        )
    return frozenset(v.strip() for v in raw.split(",") if v.strip())


def verify_agent_actor(actor: str) -> None:
    """Verify actor is an authorised principal.

    In strict PHI mode, also verifies DUA signature.

    Raises:
        AuthConfigurationError: FHIR_MCP_PRINCIPALS is unset and
            FHIR_MCP_DEV_MODE is not explicitly enabled.
        AuthError: actor is not in the configured principal set.
    """
    allowed = _allowed_set("FHIR_MCP_PRINCIPALS")
    if allowed is not None and actor not in allowed:
        raise AuthError(
            f"Actor '{actor}' is not an authorised principal. "
            "Set FHIR_MCP_PRINCIPALS to grant access."
        )
    if PHI_MODE_STRICT:
        verify_dua(actor)


def verify_approver(approver: str) -> None:
    """Verify approver is an authorised human approver.

    Raises:
        AuthConfigurationError: FHIR_MCP_APPROVERS is unset and
            FHIR_MCP_DEV_MODE is not explicitly enabled.
        AuthError: approver is not in the configured approver set.
    """
    allowed = _allowed_set("FHIR_MCP_APPROVERS")
    if allowed is not None and approver not in allowed:
        raise AuthError(
            f"Approver '{approver}' is not authorised. "
            "Set FHIR_MCP_APPROVERS to grant approval rights."
        )


def verify_dua(actor: str) -> None:
    """Verify the actor has a signed Data Use Agreement on file.

    Enforced when FHIR_MCP_PHI_MODE=strict OR called directly.

    In production: populate FHIR_MCP_DUAS with actor IDs whose
    institutional DUA paperwork has been completed and filed.

    PHI NOTE: This is a process gate, not a cryptographic one.
    It confirms the actor's ID appears on the approved list.
    Pair with mutual TLS or JWT verification at the network layer
    for cryptographic identity assurance.

    Raises:
        AuthConfigurationError: FHIR_MCP_DUAS is unset and
            FHIR_MCP_DEV_MODE is not explicitly enabled.
        AuthError: actor does not have a signed DUA on file.
    """
    dua_set = _allowed_set("FHIR_MCP_DUAS")
    if dua_set is None:
        return  # dev mode, explicitly enabled
    if actor not in dua_set:
        raise AuthError(
            f"Actor '{actor}' does not have a signed Data Use Agreement. "
            "Add actor to FHIR_MCP_DUAS after DUA paperwork is complete."
        )


def is_phi_mode_strict() -> bool:
    """Return True if FHIR_MCP_PHI_MODE=strict is set."""
    return PHI_MODE_STRICT


def is_dev_mode() -> bool:
    """Return True if FHIR_MCP_DEV_MODE=true is explicitly set."""
    return DEV_MODE
