"""
Core compilation logic — pure functions, no I/O, no side effects.

v0.3 model: `required_groups` is *data-driven*. Only groups referenced by a
directory classification exist. Agents are matched lazily against that set.
Admin users (from `constants.admins`) are added to every group in the set.

v0.4 additions: agent share surfaces. Every agent with a `share_class`
contributes three directory_classifications (memory, sessions, scratch) at
the share_class group, owned by the agent's Linux user. The share_class
group joins `used_groups` automatically, and the agent gets a synthetic
self-grant during matching so it's a member of its own home group.

See RBAC Compiler Architecture v0.4.md for the full specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .matching import grade_match, scope_match, vertical_match
from .models import AccessGrant, Agent, AgentRegistry, Constants, OrgDataFile
from .resolver import (
    CLASSIFIED_SURFACES,
    CLASSIFIED_ROOT,
    PRIVATE_DIR_MODE,
    PRIVATE_ROOT,
    PRIVATE_SURFACES,
    resolve_surface_path_relative,
)

__version__ = "0.5.0"


# ── Group name construction ───────────────────────────────────────────────────

def group_name(org: str, grade: int, vertical: str, scope: str) -> str:
    return f"{org}_g{grade}_{vertical}_{scope}"


# ── Used group (a group that at least one directory classifies to) ────────────

@dataclass(frozen=True)
class UsedGroup:
    name: str
    org: str
    grade: int
    vertical: str
    scope: str


def _used_groups_from_org_data(
    org_files: list[tuple[OrgDataFile, Path]],
) -> dict[str, UsedGroup]:
    seen: dict[str, UsedGroup] = {}
    for org_file, _ in org_files:
        for entry in org_file.data:
            name = group_name(org_file.org, entry.grade, entry.vertical, entry.scope)
            if name not in seen:
                seen[name] = UsedGroup(
                    name=name,
                    org=org_file.org,
                    grade=entry.grade,
                    vertical=entry.vertical,
                    scope=entry.scope,
                )
    return seen


def _used_groups_from_agents(agents: list[Agent]) -> dict[str, UsedGroup]:
    """Each agent with a share_class contributes its home group — that's the
    classification of its memory/sessions/scratch surfaces."""
    seen: dict[str, UsedGroup] = {}
    for agent in agents:
        if agent.share_class is None:
            continue
        sc = agent.share_class
        name = group_name(sc.org, sc.grade, sc.vertical, sc.scope)
        if name not in seen:
            seen[name] = UsedGroup(
                name=name,
                org=sc.org,
                grade=sc.grade,
                vertical=sc.vertical,
                scope=sc.scope,
            )
    return seen


def collect_used_groups(
    org_files: list[tuple[OrgDataFile, Path]],
    agents: list[Agent],
) -> list[UsedGroup]:
    """The unique set of (org, grade, vertical, scope) tuples that any
    directory in the compiled plan will be classified to. Sources: org data
    entries + agent share_class home groups.
    """
    seen = _used_groups_from_org_data(org_files)
    for name, ug in _used_groups_from_agents(agents).items():
        seen.setdefault(name, ug)
    return sorted(seen.values(), key=lambda g: g.name)


# ── Agent → group matching ────────────────────────────────────────────────────

def grant_matches_group(grant: AccessGrant, group: UsedGroup) -> bool:
    """All three dimensions must agree for an agent grant to gain access."""
    return (
        grant.org == group.org
        and grade_match(grant.grade, group.grade)
        and vertical_match(grant.vertical, group.vertical)
        and scope_match(grant.scope, group.scope)
    )


def _effective_grants(agent: Agent) -> list[AccessGrant]:
    """An agent's effective access = declared access[] + an implicit self-grant
    derived from share_class (if set). The self-grant guarantees the agent is
    a member of its own home group without redundant operator config.

    Invisible to the compiled plan output (see decision log: self-grant
    visibility is option (a) — track via docs/todo.md if needs change).
    """
    grants = list(agent.access)
    if agent.share_class is not None:
        sc = agent.share_class
        grants.append(AccessGrant(
            org=sc.org, grade=sc.grade, vertical=sc.vertical, scope=sc.scope
        ))
    return grants


def groups_for_agent(
    agent: Agent,
    used_groups: list[UsedGroup],
) -> list[str]:
    """Return the sorted set of group names the agent matches at least once
    (including via the implicit self-grant from share_class)."""
    matched: set[str] = set()
    for grant in _effective_grants(agent):
        for group in used_groups:
            if grant_matches_group(grant, group):
                matched.add(group.name)
    return sorted(matched)


# ── Output data structures ────────────────────────────────────────────────────

@dataclass
class DirectoryClassification:
    path: str
    group: str
    mode: str
    apply_default_acl: bool
    description: str | None
    source_file: str
    owner: str = "root"   # v0.4: agent surfaces use the agent's Linux user


@dataclass
class AgentUser:
    name: str
    description: str | None
    groups: list[str]


@dataclass
class AdminUser:
    """A pre-existing Linux user (human or system account) that should be
    added to every required group. Ansible ensures the account exists and
    manages its group memberships; the compiler only specifies intent.
    """

    name: str
    groups: list[str]


@dataclass
class AgentPrivateDir:
    """An agent's private directory (configs/) — mode 0700, owned by the
    agent's own user, NOT group-classified and never ingested.

    These do not belong in directory_classifications (they have no RBAC
    group), but the apply playbook still has to materialise them so the
    agent stack can assume all four surfaces exist on entry. Emitted as a
    separate section so a consumer cross-referencing directory_classifications
    against required_groups never trips over an agent's own primary group.
    """

    path: str
    owner: str
    mode: str


@dataclass
class CompiledPlan:
    compiled_at: str
    compiler_version: str
    schema_version: str
    source_files: dict[str, object]
    source_hashes: dict[str, object]
    required_groups: list[str]
    agent_users: list[AgentUser]
    admin_users: list[AdminUser]
    directory_classifications: list[DirectoryClassification]
    agent_private_dirs: list[AgentPrivateDir]
    path_roots: dict[str, dict[str, str]]
    identity_parity_required: dict[str, object]


def _identity_parity_required(
    surface_classifications: list[DirectoryClassification],
) -> dict[str, object]:
    """Declare every principal whose NUMERIC id must be identical on the agent
    host and on beaver (ADR-0010 §5).

    The compiler cannot check this — it has no uid/gid knowledge and never sees
    either host — so it states the requirement and ansible-platform verifies it.

    The wording of `assert` below is deliberate. The tempting check is "does
    this name resolve on both hosts", which is an *adjacent* invariant: a name
    resolving on both sides says nothing about the two numbers agreeing, and it
    is the numbers that travel on the NFS wire. A check that passes while uid
    1001 on the host faces uid 1002 on beaver is worse than no check, because
    the classification then describes a principal the filesystem does not
    enforce.

    Scope is deliberately narrow: ONLY the agent-surface classifications, which
    are the paths that moved to the host. The org-data classifications in the
    same list (`arc/dropbox/...`, `agents/_shared/...`) stay on beaver and are
    owned by `root`, so they have no second host to disagree with — and
    `configs/` never leaves beaver either. Declaring those too would be the same
    error this block exists to avoid: a set that looks thorough while the
    distinction that matters (which side of the export a principal lives on) is
    the one it has dropped.
    """
    users = sorted({dc.owner for dc in surface_classifications})
    groups = sorted({dc.group for dc in surface_classifications})
    return {
        "reason": (
            "ADR-0010 §5 — the agent host exports these paths and beaver mounts "
            "them. NFS carries numeric ids, so a uid/gid that differs between "
            "the two hosts makes this plan describe a principal the filesystem "
            "does not enforce."
        ),
        "assert": (
            "for every name below, the NUMERIC uid/gid resolved on the agent "
            "host EQUALS the numeric uid/gid resolved on beaver — not merely "
            "that the name resolves on both"
        ),
        "on_mismatch": "fail closed; do not apply the plan",
        "users": users,
        "groups": groups,
    }


# ── Directory classifications ─────────────────────────────────────────────────

def _classifications_from_org_data(
    org_files: list[tuple[OrgDataFile, Path]],
) -> list[DirectoryClassification]:
    result: list[DirectoryClassification] = []
    for org_file, path in org_files:
        org_key = org_file.org
        for entry in org_file.data:
            result.append(DirectoryClassification(
                path=entry.path,
                group=group_name(org_key, entry.grade, entry.vertical, entry.scope),
                mode="02770",
                apply_default_acl=True,
                description=entry.description,
                source_file=path.name,
                owner="root",
            ))
    return result


def _classifications_from_agent_surfaces(
    agents: list[Agent],
    agents_source_file: str,
) -> tuple[list[DirectoryClassification], list[str]]:
    """Emit memory/sessions/scratch classifications for each agent with a
    share_class. Returns (classifications, warnings).

    Sub-agent directories are NOT emitted — they're spawned ad-hoc by the
    parent agent at runtime and inherit the share_class group via setgid +
    default ACL on the parent surface.
    """
    classifications: list[DirectoryClassification] = []
    warnings: list[str] = []

    for agent in agents:
        if agent.share_class is None:
            if agent.access or agent.sub_agents or agent.shares:
                warnings.append(
                    f"Agent '{agent.name}' has no share_class — no surface "
                    f"classifications will be emitted. The agent user will exist "
                    f"with its declared access[] grants but has no home directory "
                    f"on the fileserver."
                )
            continue

        sc = agent.share_class
        grp = group_name(sc.org, sc.grade, sc.vertical, sc.scope)

        for surface in CLASSIFIED_SURFACES:
            try:
                path = resolve_surface_path_relative(agent, surface)
            except ValueError as exc:
                warnings.append(
                    f"Agent '{agent.name}' {surface} surface: {exc} — skipped."
                )
                continue
            if path is None:
                continue
            classifications.append(DirectoryClassification(
                path=path,
                group=grp,
                mode="02770",
                apply_default_acl=True,
                description=f"agent {agent.name} {surface} surface",
                source_file=agents_source_file,
                owner=agent.name,
            ))

    return classifications, warnings


def _private_dirs_from_agents(
    agents: list[Agent],
) -> tuple[list[AgentPrivateDir], list[str]]:
    """Emit a private-directory entry (configs/) for each agent with a
    share_class. Returns (private_dirs, warnings).

    configs/ has no RBAC group — mode 0700, owned by the agent's own user.
    It is NOT a directory_classification (no group, no ACL) but the apply
    playbook still materialises it so the agent stack finds all four
    surfaces present on entry.
    """
    private_dirs: list[AgentPrivateDir] = []
    warnings: list[str] = []

    for agent in agents:
        if agent.share_class is None:
            continue
        for surface in PRIVATE_SURFACES:
            try:
                path = resolve_surface_path_relative(agent, surface)
            except ValueError as exc:
                warnings.append(
                    f"Agent '{agent.name}' {surface} surface: {exc} — skipped."
                )
                continue
            if path is None:
                continue
            private_dirs.append(AgentPrivateDir(
                path=path,
                owner=agent.name,
                mode=PRIVATE_DIR_MODE,
            ))

    return private_dirs, warnings


# ── Main compilation entry point ──────────────────────────────────────────────

def compile_plan(
    constants: Constants,
    org_files: list[tuple[OrgDataFile, Path]],
    agent_registry: AgentRegistry,
    source_paths: dict[str, object],
    source_hashes: dict[str, object],
) -> tuple[CompiledPlan, list[str]]:
    """Compile registry inputs into a concrete plan.

    Returns (plan, warnings). Warnings are compile-time observations (empty
    data, unmatched agent, surface-path issues) that callers typically merge
    into the pipeline's ValidationResult so the GUI/CLI see them alongside
    validation warnings.

    Output is deterministic: same input -> same output byte-for-byte.
    """
    warnings: list[str] = []
    agents = agent_registry.agents

    # ── Phase 3: collect used_groups from data + agent share_classes ──────────
    used_groups = collect_used_groups(org_files, agents)
    required_group_names = [g.name for g in used_groups]

    if not used_groups:
        warnings.append(
            "Registry has no directory classifications — "
            "required_groups will be empty and no agent will be a member of any group"
        )

    # ── Phase 4: match agents against used_groups ─────────────────────────────
    agent_users: list[AgentUser] = []
    for agent in agents:
        matched = groups_for_agent(agent, used_groups)
        # Warn only if the agent has *any* basis for being in groups (declared
        # access or a share_class) yet matches none. Agents with neither are
        # already warned about during validation.
        has_basis = bool(agent.access) or agent.share_class is not None
        if has_basis and not matched:
            warnings.append(
                f"Agent '{agent.name}' matches no directory groups — "
                "registry may be incomplete or grants miscalibrated. "
                "Agent user will be created with no group memberships."
            )
        agent_users.append(AgentUser(
            name=agent.name,
            description=agent.description,
            groups=matched,
        ))

    # ── Admin users: membership of every required group ──────────────────────
    admin_users: list[AdminUser] = [
        AdminUser(name=name, groups=list(required_group_names))
        for name in constants.admins
    ]

    # ── Phase 5: directory classifications (org data + agent surfaces) ───────
    dir_classifications = _classifications_from_org_data(org_files)
    surface_classifications, surface_warnings = _classifications_from_agent_surfaces(
        agents, agents_source_file="agent_registry.yml"
    )
    dir_classifications.extend(surface_classifications)
    warnings.extend(surface_warnings)

    # Sort by path so parents apply before children (Ansible applies top-down)
    dir_classifications.sort(key=lambda d: d.path)

    # ── Agent private dirs (configs/) ─────────────────────────────────────────
    private_dirs, private_warnings = _private_dirs_from_agents(agents)
    private_dirs.sort(key=lambda d: d.path)
    warnings.extend(private_warnings)

    plan = CompiledPlan(
        compiled_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        compiler_version=__version__,
        schema_version=constants.compiler.schema_version,
        source_files=source_paths,
        source_hashes=source_hashes,
        required_groups=required_group_names,
        agent_users=agent_users,
        admin_users=admin_users,
        directory_classifications=dir_classifications,
        agent_private_dirs=private_dirs,
        path_roots={
            "classified": {
                "root": CLASSIFIED_ROOT,
                "host": "agent-host",
                "applies_to": "directory_classifications",
                "note": "local disk on the agent host, which exports it (ADR-0010 §7)",
            },
            "private": {
                "root": PRIVATE_ROOT,
                "host": "beaver",
                "applies_to": "agent_private_dirs",
                "note": "unchanged by ADR-0010; configs/ does not move (§7)",
            },
        },
        identity_parity_required=_identity_parity_required(surface_classifications),
    )
    return plan, warnings
