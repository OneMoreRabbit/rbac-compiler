"""Tests for compiled-rbac-plan 0.12 — agent_folders[], seats with share_class.

Written before the implementation (fail-first, ADR-0007/0008).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from rbac_compiler.compiler import compile_plan
from rbac_compiler.emitter import emit
from rbac_compiler.models import AgentRegistry, Constants, OrgDataFile


def _constants():
    return Constants.model_validate({"meta": {"version": "0.4"}})


def _org(org_key="arc"):
    return OrgDataFile.model_validate({
        "meta": {"version": "0.4"},
        "org_definition": {
            "key": org_key,
            "name": org_key.upper(),
            "verticals": ["any", "tech"],
            "scopes": ["global", "uk"],
            "grades": {i: "" for i in range(5)},
        },
        "data": [],
    })


SC = {"org": "arc", "grade": 1, "vertical": "tech", "scope": "uk"}

SEAT = {
    "name": "seat_test_claude",
    "access": [],
    "share_class": SC,
    "host": "otter",
    "folders": ["sessions", "memory", "configs"],
    "local_user": {"uid": 15002, "primary_gid": 15002},
}

AGENT = {
    "name": "sam",
    "share_class": SC,
    "host": "otter",
    "folders": ["sessions", "memory", "scratch", "configs"],
}


def _registry(agents=None, seats=None):
    payload = {"meta": {"version": "0.4"}, "agents": agents or []}
    if seats is not None:
        payload["seats"] = seats
    return AgentRegistry.model_validate(payload)


def _compile(org, registry):
    return compile_plan(_constants(), [(org, Path("arc.yml"))], registry, {}, {})


class TestModels0_12:
    def test_seat_accepts_share_class_now(self):
        reg = _registry(seats=[SEAT])
        assert reg.seats[0].share_class.org == "arc"

    def test_folders_outside_the_four_is_an_error(self):
        with pytest.raises(ValidationError):
            _registry(seats=[{**SEAT, "folders": ["sessions", "downloads"]}])
        with pytest.raises(ValidationError):
            _registry(agents=[{**AGENT, "folders": ["cache"]}])

    def test_folders_without_host_is_an_error(self):
        with pytest.raises(ValidationError):
            _registry(seats=[{k: v for k, v in SEAT.items() if k != "host"}])
        with pytest.raises(ValidationError):
            _registry(agents=[{k: v for k, v in AGENT.items() if k != "host"}])

    def test_folders_without_share_class_is_an_error(self):
        with pytest.raises(ValidationError):
            _registry(seats=[{k: v for k, v in SEAT.items() if k != "share_class"}])
        with pytest.raises(ValidationError):
            _registry(agents=[{k: v for k, v in AGENT.items() if k != "share_class"}])

    def test_host_alone_is_fine_and_opts_nothing_in(self):
        reg = _registry(agents=[{"name": "sam", "share_class": SC, "host": "otter"}])
        assert reg.agents[0].folders == []


class TestAgentFoldersCompile:
    def test_seat_share_class_group_joins_required_groups_and_user(self):
        plan, _ = _compile(_org(), _registry(seats=[SEAT]))
        assert "arc_g1_tech_uk" in plan.required_groups
        [u] = [u for u in plan.agent_users if u.name == "seat_test_claude"]
        assert "arc_g1_tech_uk" in u.groups

    def test_seat_still_emits_no_surfaces_or_private_dirs(self):
        plan, _ = _compile(_org(), _registry(seats=[SEAT]))
        assert plan.directory_classifications == []
        assert plan.agent_private_dirs == []

    def test_seat_folder_entries(self):
        plan, _ = _compile(_org(), _registry(seats=[SEAT]))
        rows = [f for f in plan.agent_folders if f.name == "seat_test_claude"]
        assert [f.folder for f in rows] == ["configs", "memory", "sessions"]
        r = rows[1]
        assert r.kind == "seat"
        assert r.host == "otter"
        assert r.org == "arc"
        assert r.path == "otter/arc/seat_test_claude/memory/"
        assert r.group == "arc_g1_tech_uk"

    def test_agent_folder_entries_all_four(self):
        plan, _ = _compile(_org(), _registry(agents=[AGENT]))
        rows = [f for f in plan.agent_folders if f.name == "sam"]
        assert len(rows) == 4
        assert all(r.kind == "agent" for r in rows)

    def test_indexed_false_only_for_configs(self):
        plan, _ = _compile(_org(), _registry(agents=[AGENT]))
        by_folder = {f.folder: f.indexed for f in plan.agent_folders}
        assert by_folder == {
            "sessions": True, "memory": True, "scratch": True, "configs": False
        }

    def test_no_folders_means_no_rows_even_with_host(self):
        reg = _registry(agents=[{"name": "sam", "share_class": SC, "host": "otter"}])
        plan, _ = _compile(_org(), reg)
        assert plan.agent_folders == []

    def test_every_group_in_required_groups(self):
        plan, _ = _compile(_org(), _registry(agents=[AGENT], seats=[SEAT]))
        for f in plan.agent_folders:
            assert f.group in plan.required_groups

    def test_agent_hosts_root_declared(self):
        plan, _ = _compile(_org(), _registry())
        ah = plan.path_roots["agent_hosts"]
        assert ah["root"] == "/mnt/agent-hosts/"
        assert ah["host"] == "beaver"


class TestEmitter0_12:
    def test_section_present_and_shaped(self, tmp_path):
        plan, _ = _compile(_org(), _registry(seats=[SEAT]))
        out = tmp_path / "p.yml"
        emit(plan, out)
        d = YAML().load(out.read_text())
        row = d["agent_folders"][0]
        assert set(row.keys()) == {
            "name", "kind", "host", "org", "folder", "path", "group", "indexed"
        }
        assert not row["path"].startswith("/")
        assert row["path"].endswith("/")
        assert isinstance(row["indexed"], bool)

    def test_section_present_when_empty(self, tmp_path):
        plan, _ = _compile(_org(), _registry())
        out = tmp_path / "p.yml"
        emit(plan, out)
        assert YAML().load(out.read_text())["agent_folders"] == []
