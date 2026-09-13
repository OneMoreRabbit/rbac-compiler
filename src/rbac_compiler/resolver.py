"""
Agent surface path resolution.

Both rbac-compile and sync-compile must produce byte-identical paths for the
same (agent, surface) pair — sync-compile uses the path as bisync's --local
target; rbac-compile uses it as a directory_classification. Divergence means
sync writes to one place while RBAC classifies another. Silent breakage.

The reference implementation lives in `sync_compiler.registry.resolve_surface_path()`.
This module replicates the contract. A cross-tool fixture
(tests/fixtures/cross_tool/agent_paths.yml) pins both implementations together.

Surfaces:
  - configs   (agent-private, mode 0700; classified=No)
  - memory    (classified)
  - sessions  (classified)
  - scratch   (classified)

rbac-compile emits relative paths (Ansible prepends the root at apply time).
Since ADR-0010 there are TWO roots on two different hosts, so the plan's
`meta.path_roots` states which root each section is relative to — a bare
relative path can no longer say by itself.

  classified surfaces  memory/sessions/scratch  ->  /srv/agents/<org>/<name>/<surface>/
                                                    on the agent host (it exports)
  private surface       configs                 ->  /mnt/raid/<org>/agents/<name>/configs/
                                                    on beaver (unchanged)

Note the shapes differ, not just the prefix: the host layout has no `agents/`
segment. Do not treat this as a prefix swap.

Cross-tool note: the byte-identical guarantee with sync-compile now holds over
the `<org>/<name>/<surface>` STEM, not the absolute path — sync reads the same
files through beaver's mount and ingstr through /mnt/agent-hosts/<host>/, so
three tools legitimately resolve three different roots over one tree.
"""

from __future__ import annotations

from .models import Agent

# Root for the three classified surfaces: the agent host's local disk, which the
# host exports and beaver mounts (ADR-0010). Layout: <org>/<name>/<surface>/
CLASSIFIED_ROOT = "/srv/agents/"

# Root for the private surface (configs). Unchanged by ADR-0010 — still beaver,
# still unclassified. Layout: <org>/agents/<name>/<surface>/
PRIVATE_ROOT = "/mnt/raid/"

# Retained as the beaver data root under its historical name. Pre-ADR-0010 this
# was the only root and served all four surfaces; it is now PRIVATE_ROOT's alias
# and nothing should reach for it to build a classified path.
DATA_ROOT = PRIVATE_ROOT

# All four surfaces an agent may expose. configs/ is private and not classified,
# but the resolver still gives a path for it (Ansible uses it for ownership
# setup outside the classification mechanism).
ALL_SURFACES = ("configs", "memory", "sessions", "scratch")

# Surfaces that rbac-compile emits directory_classifications for. configs is
# excluded — it's mode 0700, owned by the agent's user, not group-classified.
CLASSIFIED_SURFACES = ("memory", "sessions", "scratch")

# Surfaces emitted as agent_private_dirs — mode 0700, owned by the agent user,
# no RBAC group. The apply playbook still materialises them so the agent stack
# can assume all four surfaces exist on entry.
PRIVATE_SURFACES = ("configs",)

# Mode for private (configs) surfaces.
PRIVATE_DIR_MODE = "0700"


def _canonicalise(path: str) -> str:
    """Normalise a user-supplied path: trim whitespace, collapse repeated
    slashes, ensure a single trailing slash. No path resolution (.. is
    left alone — Pydantic-level validation rejects it earlier for data
    entries; shares overrides should be trusted/checked at validation time).
    """
    path = path.strip()
    while "//" in path:
        path = path.replace("//", "/")
    if not path.endswith("/"):
        path = path + "/"
    return path


def root_for(surface: str) -> str:
    """The root a surface's paths are relative to.

    Classified surfaces live on the agent host; configs stays on beaver
    (ADR-0010). Callers emitting paths must state the root alongside them —
    see `meta.path_roots` in the compiled plan.
    """
    if surface not in ALL_SURFACES:
        raise ValueError(
            f"unknown surface '{surface}' (valid: {', '.join(ALL_SURFACES)})"
        )
    return PRIVATE_ROOT if surface in PRIVATE_SURFACES else CLASSIFIED_ROOT


def resolve_surface_path(agent: Agent, surface: str) -> str | None:
    """Return the absolute path for an agent's surface.

    Resolution rules:
      1. If `agent.shares.<surface>` is set, that override wins (canonicalised).
      2. Otherwise, if `agent.share_class` is set, return the convention path
         for that surface's root (ADR-0010 — the two differ in shape, not just
         in prefix):
           classified  /srv/agents/<org>/<name>/<surface>/        (agent host)
           private     /mnt/raid/<org>/agents/<name>/configs/     (beaver)
      3. Otherwise return None — the agent has no path for this surface.

    Cross-tool equivalence with sync-compile now holds over the
    <org>/<name>/<surface> stem rather than the absolute path; see the module
    docstring.
    """
    if surface not in ALL_SURFACES:
        raise ValueError(
            f"unknown surface '{surface}' (valid: {', '.join(ALL_SURFACES)})"
        )

    if agent.shares is not None:
        override = getattr(agent.shares, surface, None)
        if override:
            if surface not in PRIVATE_SURFACES:
                raise ValueError(
                    f"agent '{agent.name}': `shares.{surface}` override "
                    f"'{override}' is not permitted — ADR-0010 §8 rejects "
                    f"overrides on the classified surfaces "
                    f"({', '.join(s for s in ALL_SURFACES if s not in PRIVATE_SURFACES)}). "
                    f"They live at the declared root '{CLASSIFIED_ROOT}"
                    f"<org>/<name>/{surface}/' on the agent host; a per-agent "
                    f"override would make the root advisory rather than "
                    f"authoritative (§7), and an override back to beaver would "
                    f"silently keep this agent on the slow path the ADR exists "
                    f"to remove. Remove the override; "
                    f"`shares.configs` remains permitted."
                )
            return _canonicalise(override)

    if agent.share_class is None:
        return None

    org = agent.share_class.org
    if surface in PRIVATE_SURFACES:
        return f"{PRIVATE_ROOT}{org}/agents/{agent.name}/{surface}/"
    return f"{CLASSIFIED_ROOT}{org}/{agent.name}/{surface}/"


def resolve_surface_path_relative(agent: Agent, surface: str) -> str | None:
    """Return the path relative to its surface's root — the form emitted in
    directory_classifications and agent_private_dirs.

    Raises ValueError if the path is not under the root for that surface. A
    `shares:` override on a classified surface must sit under CLASSIFIED_ROOT,
    and one on configs under PRIVATE_ROOT: since ADR-0010 those are different
    machines, so an override on the wrong side is not a classifiable path —
    it would be applied on a host where the file does not exist.
    """
    abs_path = resolve_surface_path(agent, surface)
    if abs_path is None:
        return None
    root = root_for(surface)
    if not abs_path.startswith(root):
        other = PRIVATE_ROOT if root == CLASSIFIED_ROOT else CLASSIFIED_ROOT
        hint = (
            f" — it is under '{other}', which since ADR-0010 is a different "
            f"host; a {surface} path must be under '{root}'"
            if abs_path.startswith(other) else
            " — rbac-compile cannot classify paths outside the declared roots"
        )
        raise ValueError(
            f"agent '{agent.name}' surface '{surface}': path '{abs_path}' "
            f"is not under the '{surface}' root '{root}'{hint}"
        )
    return abs_path[len(root):]
