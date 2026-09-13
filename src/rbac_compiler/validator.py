"""
Cross-reference validation across all registry files.

Collects all errors and warnings — does not stop at the first failure.
Schema validation (types, required fields) is handled by Pydantic in models.py.
This module handles cross-file consistency and semantic checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import RegistryError, RegistryWarning
from .resolver import CLASSIFIED_ROOT, CLASSIFIED_SURFACES
from .models import AgentRegistry, Constants, OrgDataFile


@dataclass
class ValidationResult:
    errors: list[RegistryError] = field(default_factory=list)
    warnings: list[RegistryWarning] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def error(self, message: str, file: Path | None = None, line: int | None = None) -> None:
        self.errors.append(RegistryError(message=message, file=file, line=line))

    def warn(self, message: str, file: Path | None = None, line: int | None = None) -> None:
        self.warnings.append(RegistryWarning(message=message, file=file, line=line))

    def merge(self, other: "ValidationResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


# rbac-compile v0.4.x accepts only this schema version on input files.
SUPPORTED_SCHEMA_VERSION = "0.4"


def _migration_message_to_v04(detected_version: str) -> str:
    return (
        f"detected legacy rbac-compile input layout (meta.version='{detected_version}'). "
        f"This rbac-compile is v0.4.\n\n"
        f"To migrate:\n"
        f"  1. Bump `meta.version` to \"0.4\" in:\n"
        f"       - classification_constants.yml\n"
        f"       - agent_registry.yml\n"
        f"       - orgs/<org>.yml  (each)\n"
        f"  2. In classification_constants.yml also update:\n"
        f"       compiler:\n"
        f"         schema_version: \"0.4\"\n"
        f"  3. Add `share_class: {{org, grade, vertical, scope}}` to every agent\n"
        f"     in agent_registry.yml that needs classified surfaces\n"
        f"     (memory/sessions/scratch directories on the fileserver).\n"
        f"  4. If you have cross-org or platform-administrative agents, create\n"
        f"     orgs/top.yml (verticals: [any], scopes: [global]) and set\n"
        f"     share_class.org: top on those agents.\n"
        f"  5. Re-run rbac-compile.\n\n"
        f"See 'RBAC Compiler Architecture v0.4.md' for the full schema."
    )


def validate_constants(constants: Constants, path: Path) -> ValidationResult:
    result = ValidationResult()
    if constants.grade_range.min > constants.grade_range.max:
        result.error("grade_range.min must be ≤ grade_range.max", file=path)

    # Fail-fast on legacy (v0.2 / v0.3) layouts.
    if constants.meta.version != SUPPORTED_SCHEMA_VERSION:
        result.error(_migration_message_to_v04(constants.meta.version), file=path)

    return result


def validate_org_file(
    org_file: OrgDataFile,
    constants: Constants,
    known_orgs: dict[str, OrgDataFile],
    path: Path,
) -> ValidationResult:
    """Cross-reference checks for a single org data file."""
    result = ValidationResult()
    org_def = org_file.org_definition
    org_key = org_def.key
    grade_min = constants.grade_range.min
    grade_max = constants.grade_range.max

    # Filename stem should match declared org key
    if path.stem != org_key:
        result.warn(
            f"File basename '{path.stem}.yml' doesn't match declared org key '{org_key}' — "
            "consider renaming the file",
            file=path,
        )

    # Duplicate org key
    if org_key in known_orgs:
        result.error(f"Org key '{org_key}' already defined in another file", file=path)
        return result

    # Org grades must be within the platform grade_range
    for g in org_def.grades:
        if not (grade_min <= g <= grade_max):
            result.error(
                f"Org '{org_key}': grade {g} out of platform range [{grade_min}, {grade_max}]",
                file=path,
            )

    # Validate each data entry
    seen_paths: set[str] = set()
    for entry in org_file.data:

        if entry.path in seen_paths:
            result.error(f"Duplicate path '{entry.path}' in org '{org_key}'", file=path)
        seen_paths.add(entry.path)

        # Grade must be declared in this org's grade scale
        if entry.grade not in org_def.grades:
            valid = sorted(org_def.grades.keys())
            result.error(
                f"Path '{entry.path}': grade {entry.grade} not defined for org '{org_key}'. "
                f"Valid grades: {valid}",
                file=path,
            )

        # Vertical must be in this org's verticals (which includes 'any' by construction)
        if entry.vertical not in org_def.verticals:
            result.error(
                f"Path '{entry.path}': vertical '{entry.vertical}' not in org '{org_key}' "
                f"verticals ({org_def.verticals})",
                file=path,
            )

        # Scope must be in this org's scopes (which includes 'global' by construction)
        if entry.scope not in org_def.scopes:
            result.error(
                f"Path '{entry.path}': scope '{entry.scope}' not in org '{org_key}' "
                f"scopes ({org_def.scopes})",
                file=path,
            )

        if " " in entry.path:
            result.warn(
                f"Path '{entry.path}' contains spaces — valid but may cause issues with some tools",
                file=path,
            )

    return result


def _validate_classification_tuple(
    org_key: str,
    grade: int,
    vertical: str,
    scope: str,
    known_orgs: dict[str, OrgDataFile],
    context: str,
    path: Path,
    result: "ValidationResult",
) -> None:
    """Shared check: an (org, grade, vertical, scope) tuple is consistent with
    the named org's declared vocabulary. Used for both AccessGrant entries
    and ShareClass blocks. `context` prefixes each error (e.g. "Agent 'X'
    access grant" or "Agent 'X' share_class")."""
    if org_key not in known_orgs:
        result.error(
            f"{context}: org '{org_key}' has no org file in registry. "
            f"Known orgs: {sorted(known_orgs.keys())}",
            file=path,
        )
        return

    org_def = known_orgs[org_key].org_definition

    if grade not in org_def.grades:
        result.error(
            f"{context}: grade {grade} not defined for org '{org_key}'. "
            f"Valid grades: {sorted(org_def.grades.keys())}",
            file=path,
        )

    if vertical not in org_def.verticals:
        result.error(
            f"{context}: vertical '{vertical}' not in org '{org_key}' "
            f"verticals ({org_def.verticals})",
            file=path,
        )

    if scope not in org_def.scopes:
        result.error(
            f"{context}: scope '{scope}' not in org '{org_key}' "
            f"scopes ({org_def.scopes})",
            file=path,
        )


def validate_agent_registry(
    registry: AgentRegistry,
    constants: Constants,
    known_orgs: dict[str, OrgDataFile],
    path: Path,
) -> ValidationResult:
    """Cross-reference checks for the agent registry."""
    result = ValidationResult()

    seen_names: set[str] = set()
    for agent in registry.agents:

        if agent.name in seen_names:
            result.error(f"Duplicate agent name '{agent.name}'", file=path)
        seen_names.add(agent.name)

        # An agent must have *something* — either declared access or a
        # share_class. An agent with neither would be created with no group
        # memberships and no home directory.
        if not agent.access and agent.share_class is None:
            result.warn(
                f"Agent '{agent.name}' has neither access grants nor share_class — "
                f"the agent user will be created with no group memberships and "
                f"no home directory on the fileserver",
                file=path,
            )

        # Validate share_class against the declared org's vocabulary.
        if agent.share_class is not None:
            sc = agent.share_class
            _validate_classification_tuple(
                org_key=sc.org,
                grade=sc.grade,
                vertical=sc.vertical,
                scope=sc.scope,
                known_orgs=known_orgs,
                context=f"Agent '{agent.name}' share_class",
                path=path,
                result=result,
            )

        # ADR-0010 §8 — `shares:` overrides are rejected on the classified
        # surfaces. This is a hard error, not a warning: the compiler's surface
        # builders turn a resolver ValueError into a warn-and-skip, which would
        # drop the classification and emit a plan where a hot surface has no
        # group and no ACL — a plan true of neither state, the §6 hazard on the
        # write side. The registry must be corrected first, which is the ADR's
        # declared rollout order (registry rewritten -> compiler change -> apply).
        if agent.shares is not None:
            for surface in CLASSIFIED_SURFACES:
                override = getattr(agent.shares, surface, None)
                if override:
                    result.error(
                        f"Agent '{agent.name}' declares `shares.{surface}: "
                        f"{override}` — ADR-0010 §8 rejects overrides on the "
                        f"classified surfaces ({', '.join(CLASSIFIED_SURFACES)}). "
                        f"They resolve under '{CLASSIFIED_ROOT}<org>/<name>/"
                        f"{surface}/' on the agent host, and a per-agent "
                        f"override makes that root advisory rather than "
                        f"authoritative. Remove the override; a path pointing "
                        f"back at beaver would also keep this agent on the slow "
                        f"path the ADR exists to remove. `shares.configs` is "
                        f"still permitted.",
                        file=path,
                    )

        # Validate access grants.
        for grant in agent.access:
            _validate_classification_tuple(
                org_key=grant.org,
                grade=grant.grade,
                vertical=grant.vertical,
                scope=grant.scope,
                known_orgs=known_orgs,
                context=f"Agent '{agent.name}' access grant",
                path=path,
                result=result,
            )

    return result


def validate_all(
    constants: Constants,
    constants_path: Path,
    org_files: list[tuple[OrgDataFile, Path]],
    agent_registry: AgentRegistry,
    agents_path: Path,
) -> ValidationResult:
    """Run all validation passes and return a combined result."""
    combined = ValidationResult()
    schema_version = constants.compiler.schema_version

    combined.merge(validate_constants(constants, constants_path))

    # Schema version check across all registry files
    for org_file, path in org_files:
        if org_file.meta.version != schema_version:
            combined.error(
                f"Schema version mismatch: expected '{schema_version}', "
                f"got '{org_file.meta.version}'",
                file=path,
            )

    if agent_registry.meta.version != schema_version:
        combined.error(
            f"Schema version mismatch: expected '{schema_version}', "
            f"got '{agent_registry.meta.version}'",
            file=agents_path,
        )

    known_orgs: dict[str, OrgDataFile] = {}
    for org_file, path in org_files:
        combined.merge(validate_org_file(org_file, constants, known_orgs, path))
        if org_file.org not in known_orgs:
            known_orgs[org_file.org] = org_file

    combined.merge(validate_agent_registry(agent_registry, constants, known_orgs, agents_path))

    return combined
