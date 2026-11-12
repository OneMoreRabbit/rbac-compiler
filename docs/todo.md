# rbac-compile — ongoing work

Items decided in principle but deferred, or known follow-ups that don't block a
release. Each entry lists context, current status, and what would change it.

---

## Self-grant visibility in the compiled plan

**Decided 2026-05-13. Status: invisible (option a).**

When an agent has a `share_class`, it gets an implicit self-grant — its user is
automatically added to the share_class group. This happens inside
`compiler.groups_for_agent` via `_effective_grants(agent)` and is **not**
surfaced in the compiled plan output. The operator's source of truth is
`agent_registry.yml`'s `share_class` + `access[]` blocks.

If a debugging surface ever needs an explicit "why is agent X in group Y?"
breakdown — most likely driven by a GUI or audit tool — the lightest options
are:

1. **Echo `share_class` on each `agent_users[]` entry.** One field per agent.
   Operator looks at the entry, sees the home class plus the resolved group
   list. Implicit but discoverable.
2. **Add a `--explain` CLI flag** that emits a per-agent breakdown to stderr
   or a side-file. Keeps the canonical plan clean.
3. **Add a `grants_resolved[]` field** to `agent_users[]` with each grant
   tagged by source (`access` vs `share_class`). Most verbose; most complete.

Revisit when a real consumer asks. Trigger to act: a GUI mocks this question
or an operator complains they can't trace a membership.

---

## Cross-tool path fixture coordination

**Status: rbac-compile ships its own copy. Push to sync-compile pending.**

The fixture at `tests/fixtures/cross_tool/agent_paths.yml` is the rbac-side
copy of a contract shared with sync-compile. Since ADR-0010 §7 the two tools
agree on the `<org>/<name>/<surface>` shape only — not byte-identical
absolute paths, because the classified surfaces live under the agent host's
root while sync addresses beaver's view of them.

**Action**: push this fixture to the sync-compile maintainer. Their test
should assert their `resolve_surface_path()` matches the `absolute` column
for every case. Ours asserts both `absolute` and `relative` columns.

Regressions the fixture catches:
- trailing-slash divergence (`/foo/bar` vs `/foo/bar/`)
- canonicalisation differences in `shares:` overrides
- prefix-handling differences (rbac strips `/mnt/raid/`, sync doesn't)
- accidental special-casing of `top` org

When sync-compile adopts it, both tools should run it in CI on every push so
schema drift fails loud.

---

## Open items inherited from agent-shares architecture v0.2.1

These are tracked in `RBAC_Registry/integrations/agent-shares-architecture-v0_2_1.md`
under §"Open items" and don't need immediate compiler changes. Logged here so
they're visible from this project.

- **rclone.conf readability for agent users** — sync-compile / Ansible concern,
  not rbac-compile.
- **Sub-agent runtime model** — agent-container concern.
- **Sessions compression** — ingestion concern.
- **Memory ingestion granularity** — ingstr concern.
- **Finer sub-classification within `scratch/`** — future schema extension.
  Likely a per-subdirectory `classifications:` block on agents. Not needed
  for MVP.
- **Explicit supervisor relationships** — would require schema work if/when
  grade-based supervision turns out to be too coarse.
- **Shared-space RBAC schema** — if `agents/shared/` ever needs per-subdirectory
  classifications, declare a `shared_spaces:` block in `agent_registry.yml` or
  similar. Currently the `agents/shared/` directory is owned by the org
  platform playbook with default ownership and rbac-compile emits nothing
  for it.

---

*Append new items as they come up — keep entries short, dated, and pointed at
the artifact (test, fixture, schema field) they affect.*
