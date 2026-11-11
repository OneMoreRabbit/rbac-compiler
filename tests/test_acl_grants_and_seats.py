"""Tests for v0.7.1 — acl_grants (compiled-rbac-plan 0.9) and seat principals.

Written before the implementation (ADR-0007/0008: new unit tests must fail
against the old code).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from rbac_compiler.compiler import collect_used_groups, compile_plan
from rbac_compiler.emitter import emit
from rbac_compiler.models import (
    AgentRegistry,
    Constants,
    OrgDataFile,
)
from rbac_compiler.validator import validate_org_file, validate_agent_registry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_constants(admins: list[str] | None = None) -> Constants:
    data: dict = {"meta": {"version": "0.4"}}
    if admins is not None:
        data["admins"] = admins
    return Constants.model_validate(data)


def _make_org(
    org_key: str = "arc",
    data: list[dict] | None = None,
    acl_grants: list[dict] | None = None,
) -> OrgDataFile:
    payload: dict = {
        "meta": {"version": "0.4"},
        "org_definition": {
            "key": org_key,
            "name": org_key.upper(),
            "verticals": ["any", "tech", "gis"],
            "scopes": ["global", "uk", "mz", "zambia"],
            "grades": {i: "" for i in range(5)},
        },
        "data": data or [],
    }
    if acl_grants is not None:
        payload["acl_grants"] = acl_grants
    return OrgDataFile.model_validate(payload)


ZAMBIA = {
    "path": "arc/drive/zambia_data",
    "grade": 2,
    "vertical": "gis",
    "scope": "zambia",
    "access": "read",
    "description": "Zambia Data for the ARC GIS seat",
}


def _registry(agents: list[dict] | None = None, seats: list[dict] | None = None) -> AgentRegistry:
    payload: dict = {"meta": {"version": "0.4"}, "agents": agents or []}
    if seats is not None:
        payload["seats"] = seats
    return AgentRegistry.model_validate(payload)


def _compile(org_files, registry):
    return compile_plan(
        constants=_make_constants(),
        org_files=org_files,
        agent_registry=registry,
        source_paths={},
        source_hashes={},
    )


# ── Models ────────────────────────────────────────────────────────────────────

class TestAclGrantModel:
    def test_minimal_entry_parses_with_default_acl_false(self):
        org = _make_org(acl_grants=[ZAMBIA])
        g = org.acl_grants[0]
        assert g.access == "read"
        assert g.default_acl is False

    def test_access_must_be_read_or_rw(self):
        with pytest.raises(ValidationError):
            _make_org(acl_grants=[{**ZAMBIA, "access": "write"}])

    def test_path_rules_match_data_entries(self):
        with pytest.raises(ValidationError):
            _make_org(acl_grants=[{**ZAMBIA, "path": "/absolute/path"}])
        with pytest.raises(ValidationError):
            _make_org(acl_grants=[{**ZAMBIA, "path": "a/../b"}])

    def test_absent_list_is_empty(self):
        assert _make_org().acl_grants == []


class TestSeatModel:
    def test_seat_is_name_plus_access(self):
        reg = _registry(seats=[{
            "name": "arc_gis_seat",
            "access": [{"org": "arc", "grade": 2, "vertical": "gis", "scope": "zambia"}],
        }])
        assert reg.seats[0].name == "arc_gis_seat"
        assert len(reg.seats[0].access) == 1

    def test_seat_rejects_share_class(self):
        # A seat has no home classification — the wrong answer would succeed
        # silently (surfaces emitted for a principal that has none).
        with pytest.raises(ValidationError):
            _registry(seats=[{
                "name": "arc_gis_seat",
                "access": [],
                "share_class": {"org": "arc", "grade": 2, "vertical": "gis", "scope": "zambia"},
            }])

    def test_seat_name_is_a_linux_username(self):
        with pytest.raises(ValidationError):
            _registry(seats=[{"name": "Not-Valid", "access": []}])

    def test_absent_list_is_empty(self):
        assert _registry().seats == []


# ── Compiler ──────────────────────────────────────────────────────────────────

class TestAclGrantsCompile:
    def test_grant_group_joins_required_groups_without_classification(self):
        org = _make_org(acl_grants=[ZAMBIA])
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        assert "arc_g2_gis_zambia" in plan.required_groups
        # No classification for the path — that is the whole point.
        assert all(
            "zambia_data" not in dc.path for dc in plan.directory_classifications
        )

    def test_emitted_entry_shape(self):
        org = _make_org(acl_grants=[ZAMBIA])
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        [g] = plan.acl_grants
        assert g.path == "arc/drive/zambia_data/"   # canonical: one trailing slash
        assert g.group == "arc_g2_gis_zambia"
        assert g.access == "read"
        assert g.default_acl is False
        assert g.source_file == "arc.yml"

    def test_no_owner_and_no_mode_fields(self):
        # The section cannot express an ownership or mode change, by construction.
        org = _make_org(acl_grants=[ZAMBIA])
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        [g] = plan.acl_grants
        assert not hasattr(g, "owner")
        assert not hasattr(g, "mode")

    def test_seat_joins_share_group_through_matching_grant(self):
        org = _make_org(acl_grants=[ZAMBIA])
        reg = _registry(seats=[{
            "name": "arc_gis_seat",
            "access": [{"org": "arc", "grade": 2, "vertical": "gis", "scope": "zambia"}],
        }])
        plan, _ = _compile([(org, Path("arc.yml"))], reg)
        [user] = [u for u in plan.agent_users if u.name == "arc_gis_seat"]
        assert user.groups == ["arc_g2_gis_zambia"]

    def test_seat_emits_no_surfaces_and_no_private_dirs(self):
        org = _make_org(acl_grants=[ZAMBIA])
        reg = _registry(seats=[{
            "name": "arc_gis_seat",
            "access": [{"org": "arc", "grade": 2, "vertical": "gis", "scope": "zambia"}],
        }])
        plan, _ = _compile([(org, Path("arc.yml"))], reg)
        assert plan.directory_classifications == []
        assert plan.agent_private_dirs == []

    def test_classified_path_may_also_carry_a_grant(self):
        org = _make_org(
            data=[{"path": "arc/dirs/a", "grade": 1, "vertical": "tech", "scope": "uk"}],
            acl_grants=[{**ZAMBIA, "path": "arc/dirs/a"}],
        )
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        assert len(plan.directory_classifications) == 1
        assert len(plan.acl_grants) == 1

    def test_acl_path_root_declared(self):
        org = _make_org(acl_grants=[ZAMBIA])
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        acl_root = plan.path_roots["acl"]
        assert acl_root["root"] == "/mnt/raid/"
        assert acl_root["host"] == "beaver"
        assert acl_root["applies_to"] == "acl_grants"

    def test_used_groups_include_acl_grant_tuples(self):
        org = _make_org(acl_grants=[ZAMBIA])
        groups = collect_used_groups([(org, Path("arc.yml"))], agents=[])
        assert [g.name for g in groups] == ["arc_g2_gis_zambia"]


class TestEmitterAclGrants:
    def test_acl_grants_key_always_present(self, tmp_path):
        org = _make_org()
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        out = tmp_path / "plan.yml"
        emit(plan, out)
        data = YAML().load(out.read_text())
        assert data["acl_grants"] == []

    def test_acl_grants_emitted_fields(self, tmp_path):
        org = _make_org(acl_grants=[{**ZAMBIA, "default_acl": True, "access": "rw"}])
        plan, _ = _compile([(org, Path("arc.yml"))], _registry())
        out = tmp_path / "plan.yml"
        emit(plan, out)
        data = YAML().load(out.read_text())
        [g] = data["acl_grants"]
        assert set(g.keys()) == {
            "path", "group", "access", "default_acl", "description", "source_file"
        }
        assert g["access"] == "rw"
        assert g["default_acl"] is True


# ── Validator ─────────────────────────────────────────────────────────────────

class TestValidatorAclGrants:
    def test_tuple_must_fit_org_vocabulary(self):
        org = _make_org(acl_grants=[{**ZAMBIA, "vertical": "nosuch"}])
        result = validate_org_file(org, _make_constants(), {}, Path("arc.yml"))
        assert not result.ok
        assert any("nosuch" in str(e) for e in result.errors)

    def test_grade_must_be_declared(self):
        org = _make_org(acl_grants=[{**ZAMBIA, "grade": 99}])
        result = validate_org_file(org, _make_constants(), {}, Path("arc.yml"))
        assert not result.ok

    def test_valid_grant_passes(self):
        org = _make_org(acl_grants=[ZAMBIA])
        result = validate_org_file(org, _make_constants(), {}, Path("arc.yml"))
        assert result.ok


class TestValidatorSeats:
    def test_duplicate_name_across_agents_and_seats_is_an_error(self):
        reg = _registry(
            agents=[{"name": "arc_gis_seat", "access": []}],
            seats=[{"name": "arc_gis_seat", "access": []}],
        )
        orgs = {"arc": _make_org()}
        result = validate_agent_registry(reg, _make_constants(), orgs, Path("agent_registry.yml"))
        assert not result.ok
        assert any("arc_gis_seat" in str(e) for e in result.errors)

    def test_seat_grant_tuple_checked_against_orgs(self):
        reg = _registry(seats=[{
            "name": "arc_gis_seat",
            "access": [{"org": "nosuchorg", "grade": 2, "vertical": "gis", "scope": "zambia"}],
        }])
        orgs = {"arc": _make_org()}
        result = validate_agent_registry(reg, _make_constants(), orgs, Path("agent_registry.yml"))
        assert not result.ok
