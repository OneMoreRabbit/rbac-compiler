---
title: Release notes — rbac-compiler
status: active
updated: 2026-10-08
owner: agent-eco.component.rbac-compile
about: one short entry per release, newest first — what changed and what anyone must do about it
---

# Release notes — rbac-compiler

Newest first. One entry per release tag, written in the same commit that cuts the
tag. Plain English: a reader skimming this page should know what changed and
whether they have to act. Detail lives in commits, contracts and troubleshooting
reports — link them, don't repeat them.

## v0.7.3 — 2026-11-13

**TL;DR:** the plan now declares each group's tuple (`groups[]`) and each classified folder's root (`path_root`) — nothing is parsed from names any more.

- New `groups[]` section: {name, org, grade, vertical, scope}, one row per required group — a consumer reads the org instead of parsing the group name (asked for one-dprox-per-org and ingstr's per-org filtering).
- Every `directory_classifications[]` entry carries `path_root: classified|org_data`, and `meta.path_roots` gains `org_data` (beaver, `/mnt/raid/`) — org folders no longer read as if they lived on the agent host ([[agenteco-plan-path-root-ruling-v0_1]]).
- Contract also states acl_grants multiplicity (one path may carry several grants) and ordering (sorted by path, then group).
- All additive: a reader that ignores the new keys behaves as on 0.10.

**Action:** consumers re-pin compiled-rbac-plan 0.11 when they take the new fields; no playbook edit required.

## v0.7.2 — 2026-11-11

**TL;DR:** seats carry `local_user {uid, primary_gid}` so Ansible actually creates the seat's user; version string fixed.

- `seats:` entries accept an optional `local_user` (same shape as an agent's, typed and validated): without it 07agentdata creates no user on beaver and the apply fails closed — found by estate-fileserver testing v0.7.1 against the live registry.
- Seat uids are validated into the 15xxx range (agreed with estate-manage); a duplicate uid across agents and seats is an error, as names already are.
- Plan output unchanged — uids are not emitted, same as agents.
- `rbac-compile --version` no longer prints 0.7.0 on a newer build: one version home (`compiler.__version__`).
- Contract: compiled-rbac-plan 0.10 (additive, registry-source text only).

**Action:** estate-fileserver installs from this tag; re-pin compiled-rbac-plan 0.10.

## v0.7.1 — 2026-11-11

**TL;DR:** ACL-only grants (`acl_grants`) and seat principals — folders shared into seats without touching ownership.

- New compiled-plan section `acl_grants[]`: path, group, `read|rw`, `default_acl` — applied as an added ACL (`setfacl`); owner, group and mode are never changed. Declared in `orgs/<org>.yml` under `acl_grants:`; the tuple creates the share group, not a classification.
- New `seats:` top-level list in `agent_registry.yml`: a seat is a user plus `access[]`, no surfaces, no private dir; separate from `agents:` so agent tools never see it.
- Third `meta.path_roots` entry: `acl` (beaver, `/mnt/raid/`).
- First use: Zambia Data — one read grant, unclassified on purpose (classification rewrote ownership and broke the one-way copy).
- Contract: compiled-rbac-plan 0.9 (additive; 0.8's `kind: seat` marker replaced by `seats:` before anything built against it).

**Action:** estate-fileserver pins compiled-rbac-plan 0.9 and installs from this tag; other consumers re-pin when convenient (additive).

(Starts from v0.7.1; v0.7.0 and earlier predate this file.)
