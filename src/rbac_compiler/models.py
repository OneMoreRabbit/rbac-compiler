"""
Pydantic models for the RBAC registry files.

File roles:
  classification_constants.yml  ->  Constants    (grade_range, reserved_tokens, compiler config)
  orgs/<org>.yml                ->  OrgDataFile  (org definition + data entries)
  agent_registry.yml            ->  AgentRegistry
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LINUX_USERNAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
ORG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


# ── Shared ────────────────────────────────────────────────────────────────────

class Meta(BaseModel):
    version: str
    stage: str | None = None
    last_modified: str | None = None
    last_modified_by: str | None = None
    description: str | None = None


# ── classification_constants.yml ──────────────────────────────────────────────

class GradeRange(BaseModel):
    min: int = 0
    max: int = 20


class ReservedTokens(BaseModel):
    any_vertical: str = "any"
    global_scope: str = "global"


class CompilerConfig(BaseModel):
    registry_dir: str = "~/registry"
    orgs_dir: str = "orgs"
    agents_dir: str = "agents"
    output_file: str = ".compiled/compiled_plan.yml"
    schema_version: str = "0.4"


class Constants(BaseModel):
    # extra='allow' tolerates fields owned by other platform tools (e.g.
    # agent_user_defaults consumed by apply_rbac_plan.yml, directory_defaults
    # reserved for future use). The compiler does not validate them.
    model_config = ConfigDict(extra="allow")

    meta: Meta
    grade_range: GradeRange = Field(default_factory=GradeRange)
    reserved_tokens: ReservedTokens = Field(default_factory=ReservedTokens)
    compiler: CompilerConfig = Field(default_factory=CompilerConfig)
    admins: list[str] = Field(default_factory=list)

    @field_validator("admins")
    @classmethod
    def admins_are_valid_usernames(cls, v: list[str]) -> list[str]:
        for name in v:
            if not LINUX_USERNAME_RE.match(name):
                raise ValueError(
                    f"admin '{name}' is not a valid Linux username "
                    "(lowercase, alphanumeric + underscores, ≤ 32 chars, must start with a letter)"
                )
        return v


# ── orgs/<org>.yml ────────────────────────────────────────────────────────────

def _relative_path_valid(v: str) -> str:
    if not v:
        raise ValueError("path must not be empty")
    if ".." in v:
        raise ValueError("path must not contain '..'")
    if v.startswith("/"):
        raise ValueError("path must not start with '/'")
    return v


class DataEntry(BaseModel):
    path: str
    grade: int
    vertical: str
    scope: str
    description: str | None = None

    @field_validator("path")
    @classmethod
    def path_valid(cls, v: str) -> str:
        return _relative_path_valid(v)


class OrgDefinition(BaseModel):
    """Org metadata and vocabulary declared at the top of each orgs/<org>.yml."""

    key: str
    name: str
    description: str | None = None
    website: str | None = None
    verticals: list[str]
    scopes: list[str]
    grades: dict[int, str]

    @field_validator("key")
    @classmethod
    def key_valid(cls, v: str) -> str:
        if not ORG_KEY_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid org key "
                "(lowercase alphanumeric + underscores, ≤ 32 chars, must start with a letter)"
            )
        return v

    @field_validator("verticals", "scopes")
    @classmethod
    def lists_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("verticals")
    @classmethod
    def verticals_has_any(cls, v: list[str]) -> list[str]:
        if "any" not in v:
            raise ValueError("verticals must contain the wildcard 'any'")
        return v

    @field_validator("scopes")
    @classmethod
    def scopes_has_global(cls, v: list[str]) -> list[str]:
        if "global" not in v:
            raise ValueError("scopes must contain the wildcard 'global'")
        return v

    @field_validator("grades", mode="before")
    @classmethod
    def parse_grades(cls, v: Any) -> dict[int, str]:
        if not isinstance(v, dict):
            raise ValueError("grades must be a mapping")
        return {int(k): str(val) for k, val in v.items()}

    @field_validator("grades")
    @classmethod
    def grades_nonempty(cls, v: dict[int, str]) -> dict[int, str]:
        if not v:
            raise ValueError("grades must not be empty")
        return v


class AclGrantEntry(BaseModel):
    """v0.9 (compiled-rbac-plan): an ACL-only grant on a path RBAC does not
    necessarily classify. The (grade, vertical, scope) tuple + the org file's
    key derive the share group exactly as a data entry would — the tuple
    creates the group, not a classification. Applied downstream as an added
    ACL; owner, group and mode are never touched.
    """

    path: str
    grade: int
    vertical: str
    scope: str
    access: Literal["read", "rw"]
    default_acl: bool = False
    description: str | None = None

    @field_validator("path")
    @classmethod
    def path_valid(cls, v: str) -> str:
        return _relative_path_valid(v)


class OrgDataFile(BaseModel):
    """Represents one orgs/<org>.yml file."""

    meta: Meta
    org_definition: OrgDefinition
    data: list[DataEntry] = Field(default_factory=list)
    # v0.9: optional ACL-only grants (seat data sharing design §4).
    acl_grants: list[AclGrantEntry] = Field(default_factory=list)

    @property
    def org(self) -> str:
        return self.org_definition.key


# ── agent_registry.yml ────────────────────────────────────────────────────────

class AccessGrant(BaseModel):
    org: str
    grade: int
    vertical: str   # specific vertical name or the reserved 'any' token
    scope: str      # specific scope name or the reserved 'global' token


class ShareClass(BaseModel):
    """An agent's home classification — the (org, grade, vertical, scope)
    tuple that classifies its memory/sessions/scratch surfaces. Lower grade
    number = more privileged.
    """

    org: str
    grade: int
    vertical: str
    scope: str


class Shares(BaseModel):
    """Optional per-surface path overrides. Convention paths are used when a
    surface is absent. Surfaces: configs, memory, sessions, scratch.
    """

    configs: str | None = None
    memory: str | None = None
    sessions: str | None = None
    scratch: str | None = None


SUB_AGENT_NAME_RE = re.compile(r"^[a-z0-9_]+$")
RESERVED_SUB_AGENT_NAMES = frozenset({"main"})


class Agent(BaseModel):
    # extra='allow' tolerates fields owned by other platform tools (e.g.
    # 'cert:' for dprox certificate issuance, 'local_user:' for samba/shell
    # provisioning by apply_rbac_plan.yml, 'cloud_sync:' for sync-compile,
    # 'app:' / 'secret_manifest:' for the agent-container workstream).
    # The compiler does not validate these. To add validation, define the
    # field here.
    model_config = ConfigDict(extra="allow")

    name: str
    description: str | None = None
    # v0.4: access[] is optional. An agent with only share_class still gets
    # the implicit self-grant (see compiler.groups_for_agent).
    access: list[AccessGrant] = Field(default_factory=list)
    # v0.4: share_class is the agent's home classification. Required for any
    # agent that wants classified surfaces (memory/sessions/scratch); agents
    # without it are valid but get no auto-emitted classifications.
    share_class: ShareClass | None = None
    # v0.4: sub_agents is informational for rbac-compile — sub-agents are
    # spawned ad-hoc by the parent agent at runtime and inherit RBAC via
    # setgid + default ACL on the parent surface. We validate the names
    # but emit nothing per sub-agent.
    sub_agents: list[str] = Field(default_factory=list)
    # v0.4: shares is optional per-surface path overrides. When absent the
    # convention paths apply (<org>/agents/<name>/<surface>/).
    shares: Shares | None = None

    @field_validator("name")
    @classmethod
    def valid_linux_username(cls, v: str) -> str:
        if not LINUX_USERNAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid Linux username "
                "(lowercase, alphanumeric + underscores, ≤ 32 chars, must start with a letter)"
            )
        return v

    @field_validator("sub_agents")
    @classmethod
    def valid_sub_agent_names(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in v:
            if not SUB_AGENT_NAME_RE.match(name):
                raise ValueError(
                    f"sub-agent '{name}' is not a valid identifier "
                    "(lowercase alphanumeric + underscores only)"
                )
            if name in RESERVED_SUB_AGENT_NAMES:
                raise ValueError(
                    f"sub-agent name '{name}' is reserved "
                    "(collides with the implicit 'main' subdirectory)"
                )
            if name in seen:
                raise ValueError(f"duplicate sub-agent name '{name}' within agent")
            seen.add(name)
        return v


SEAT_UID_MIN = 15000
SEAT_UID_MAX = 15999


class SeatLocalUser(BaseModel):
    """v0.10 (compiled-rbac-plan): the identity block 07agentdata creates the
    Linux user from — same shape as an agent's `local_user`, but typed and
    validated here because a seat without one gets no user on beaver and the
    apply fails closed (hub #13002). Extra keys (e.g. samba flags) are
    tolerated like an agent's, and consumed by Ansible, not here.
    """

    model_config = ConfigDict(extra="allow")

    uid: int
    primary_gid: int

    @field_validator("uid")
    @classmethod
    def uid_in_seat_range(cls, v: int) -> int:
        if not (SEAT_UID_MIN <= v <= SEAT_UID_MAX):
            raise ValueError(
                f"seat uid {v} outside the seat range "
                f"[{SEAT_UID_MIN}, {SEAT_UID_MAX}] (agreed with estate-manage)"
            )
        return v


class Seat(BaseModel):
    """v0.9 (compiled-rbac-plan): a seat principal — a Linux user plus access
    grants. Seats live in their own top-level `seats:` list so agent tools,
    which treat every record under `agents:` as a target, never see them
    (arch ruling, hub #12944). rbac-compile is the only reader.

    A seat deliberately cannot carry `share_class` (extra fields are
    forbidden): a seat has no home classification, no surfaces and no private
    dir, and a silently-accepted share_class would emit surfaces for a
    principal that has none — the wrong answer succeeding.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    access: list[AccessGrant] = Field(default_factory=list)
    # v0.10: optional identity block; without it 07agentdata creates no user.
    local_user: SeatLocalUser | None = None

    @field_validator("name")
    @classmethod
    def valid_linux_username(cls, v: str) -> str:
        if not LINUX_USERNAME_RE.match(v):
            raise ValueError(
                f"'{v}' is not a valid Linux username "
                "(lowercase, alphanumeric + underscores, ≤ 32 chars, must start with a letter)"
            )
        return v


class AgentRegistry(BaseModel):
    meta: Meta
    agents: list[Agent] = Field(default_factory=list)
    # v0.9: seat principals, separate from agents on purpose (see Seat).
    seats: list[Seat] = Field(default_factory=list)
