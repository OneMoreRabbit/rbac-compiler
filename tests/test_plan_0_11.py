"""Tests for compiled-rbac-plan 0.11 — groups[], path_root, acl_grants lines.

Written before the implementation (fail-first, ADR-0007/0008).
Per agenteco-plan-path-root-ruling-v0_1 and hub #13771.
"""

from pathlib import Path

from ruamel.yaml import YAML

from rbac_compiler.compiler import compile_plan
from rbac_compiler.emitter import emit
from rbac_compiler.models import AgentRegistry, Constants, OrgDataFile


def _constants() -> Constants:
    return Constants.model_validate({"meta": {"version": "0.4"}})


def _org(org_key="arc", data=None, acl_grants=None) -> OrgDataFile:
    payload = {
        "meta": {"version": "0.4"},
        "org_definition": {
            "key": org_key,
            "name": org_key.upper(),
            "verticals": ["any", "tech", "gis"],
            "scopes": ["global", "uk", "zambia"],
            "grades": {i: "" for i in range(5)},
        },
        "data": data or [],
    }
    if acl_grants is not None:
        payload["acl_grants"] = acl_grants
    return OrgDataFile.model_validate(payload)


def _registry(agents=None) -> AgentRegistry:
    return AgentRegistry.model_validate(
        {"meta": {"version": "0.4"}, "agents": agents or []}
    )


AGENT = {
    "name": "sam",
    "share_class": {"org": "arc", "grade": 1, "vertical": "tech", "scope": "uk"},
}
DATA = {"path": "arc/global", "grade": 2, "vertical": "gis", "scope": "zambia"}


def _compile(org, registry):
    return compile_plan(_constants(), [(org, Path("arc.yml"))], registry, {}, {})


class TestGroupsSection:
    def test_one_row_per_required_group_with_full_tuple(self):
        plan, _ = _compile(_org(data=[DATA]), _registry(agents=[AGENT]))
        assert [g.name for g in plan.groups] == plan.required_groups
        by_name = {g.name: g for g in plan.groups}
        zam = by_name["arc_g2_gis_zambia"]
        assert (zam.org, zam.grade, zam.vertical, zam.scope) == ("arc", 2, "gis", "zambia")
        home = by_name["arc_g1_tech_uk"]
        assert (home.org, home.grade, home.vertical, home.scope) == ("arc", 1, "tech", "uk")

    def test_acl_grant_groups_included(self):
        grant = {**DATA, "path": "arc/drive/zambia_data", "access": "read"}
        plan, _ = _compile(_org(acl_grants=[grant]), _registry())
        assert [g.name for g in plan.groups] == ["arc_g2_gis_zambia"]


class TestPathRoot:
    def test_org_data_entries_carry_org_data(self):
        plan, _ = _compile(_org(data=[DATA]), _registry())
        [dc] = plan.directory_classifications
        assert dc.path_root == "org_data"

    def test_agent_surfaces_carry_classified(self):
        plan, _ = _compile(_org(), _registry(agents=[AGENT]))
        assert plan.directory_classifications
        assert all(dc.path_root == "classified" for dc in plan.directory_classifications)

    def test_every_path_root_is_a_path_roots_key(self):
        plan, _ = _compile(_org(data=[DATA]), _registry(agents=[AGENT]))
        for dc in plan.directory_classifications:
            assert dc.path_root in plan.path_roots

    def test_org_data_root_declared(self):
        plan, _ = _compile(_org(), _registry())
        od = plan.path_roots["org_data"]
        assert od["root"] == "/mnt/raid/"
        assert od["host"] == "beaver"


class TestEmitter0_11:
    def test_groups_key_present_and_shaped(self, tmp_path):
        plan, _ = _compile(_org(data=[DATA]), _registry())
        out = tmp_path / "p.yml"
        emit(plan, out)
        d = YAML().load(out.read_text())
        [g] = d["groups"]
        assert set(g.keys()) == {"name", "org", "grade", "vertical", "scope"}

    def test_groups_key_present_when_empty(self, tmp_path):
        plan, _ = _compile(_org(), _registry())
        out = tmp_path / "p.yml"
        emit(plan, out)
        assert YAML().load(out.read_text())["groups"] == []

    def test_dc_entries_emit_path_root(self, tmp_path):
        plan, _ = _compile(_org(data=[DATA]), _registry())
        out = tmp_path / "p.yml"
        emit(plan, out)
        [dc] = YAML().load(out.read_text())["directory_classifications"]
        assert dc["path_root"] == "org_data"

    def test_acl_grants_sorted_by_path_then_group(self, tmp_path):
        grants = [
            {"path": "arc/b", "grade": 2, "vertical": "gis", "scope": "zambia", "access": "read"},
            {"path": "arc/a", "grade": 2, "vertical": "gis", "scope": "zambia", "access": "read"},
            {"path": "arc/a", "grade": 1, "vertical": "tech", "scope": "uk", "access": "rw"},
        ]
        plan, _ = _compile(_org(acl_grants=grants), _registry())
        keys = [(g.path, g.group) for g in plan.acl_grants]
        assert keys == sorted(keys)
