"""
rbac_compiler — public API for programmatic use (CLI and future web GUI).

Example:
    from pathlib import Path
    from rbac_compiler import compile_registry

    result = compile_registry(Path("~/registry").expanduser())
    if not result.validation.ok:
        for err in result.validation.errors:
            print(f"ERROR: {err}")
    else:
        print(f"Wrote plan to {result.output_path}")
"""

from .compiler import (
    AdminUser,
    AgentPrivateDir,
    AgentUser,
    CompiledPlan,
    DirectoryClassification,
    UsedGroup,
    collect_used_groups,
    compile_plan,
    grant_matches_group,
    groups_for_agent,
)
from .matching import grade_match, scope_match, vertical_match
from .errors import CompilerInternalError, RegistryError, RegistryLoadError, RegistryWarning
from .loader import (
    discover_org_files,
    load_agent_registry,
    load_constants,
    load_org_file,
)
from .models import (
    AccessGrant,
    Agent,
    AgentRegistry,
    Constants,
    DataEntry,
    OrgDataFile,
    OrgDefinition,
    ShareClass,
    Shares,
)
from .resolver import (
    ALL_SURFACES,
    CLASSIFIED_SURFACES,
    DATA_ROOT,
    resolve_surface_path,
    resolve_surface_path_relative,
)
from .operations import (
    CompileResult,
    LoadedRegistry,
    ValidateResult,
    compile_registry,
    load_registry,
    validate,
)
from .validator import ValidationResult, validate_all

__version__ = "0.5.0"

__all__ = [
    "__version__",
    # Operations (high-level API)
    "compile_registry",
    "validate",
    "load_registry",
    "CompileResult",
    "ValidateResult",
    "LoadedRegistry",
    # Core compilation
    "CompiledPlan",
    "compile_plan",
    "collect_used_groups",
    "groups_for_agent",
    "grant_matches_group",
    "UsedGroup",
    "AgentUser",
    "AdminUser",
    "AgentPrivateDir",
    "DirectoryClassification",
    "ValidationResult",
    "validate_all",
    # Match primitives
    "grade_match",
    "vertical_match",
    "scope_match",
    # Loaders
    "load_constants",
    "load_org_file",
    "load_agent_registry",
    "discover_org_files",
    # Models
    "Constants",
    "OrgDataFile",
    "OrgDefinition",
    "DataEntry",
    "AgentRegistry",
    "Agent",
    "AccessGrant",
    "ShareClass",
    "Shares",
    # Path resolver (shared contract with sync-compile)
    "DATA_ROOT",
    "ALL_SURFACES",
    "CLASSIFIED_SURFACES",
    "resolve_surface_path",
    "resolve_surface_path_relative",
    # Errors
    "RegistryError",
    "RegistryWarning",
    "RegistryLoadError",
    "CompilerInternalError",
]
