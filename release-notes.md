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

## v0.7.1 — 2026-11-11

**TL;DR:** ACL-only grants (`acl_grants`) and seat principals — folders shared into seats without touching ownership.

- New compiled-plan section `acl_grants[]`: path, group, `read|rw`, `default_acl` — applied as an added ACL (`setfacl`); owner, group and mode are never changed. Declared in `orgs/<org>.yml` under `acl_grants:`; the tuple creates the share group, not a classification.
- New `seats:` top-level list in `agent_registry.yml`: a seat is a user plus `access[]`, no surfaces, no private dir; separate from `agents:` so agent tools never see it.
- Third `meta.path_roots` entry: `acl` (beaver, `/mnt/raid/`).
- First use: Zambia Data — one read grant, unclassified on purpose (classification rewrote ownership and broke the one-way copy).
- Contract: compiled-rbac-plan 0.9 (additive; 0.8's `kind: seat` marker replaced by `seats:` before anything built against it).

**Action:** estate-fileserver pins compiled-rbac-plan 0.9 and installs from this tag; other consumers re-pin when convenient (additive).

(Starts from v0.7.1; v0.7.0 and earlier predate this file.)
