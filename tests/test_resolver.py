"""Unit tests for the agent surface path resolver."""

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from rbac_compiler.models import Agent
from rbac_compiler.resolver import (
    ALL_SURFACES,
    CLASSIFIED_ROOT,
    CLASSIFIED_SURFACES,
    DATA_ROOT,
    PRIVATE_ROOT,
    PRIVATE_SURFACES,
    resolve_surface_path,
    root_for,
    resolve_surface_path_relative,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agent(**kw) -> Agent:
    return Agent.model_validate({
        "name": kw.pop("name", "agent_test"),
        "access": [],
        **kw,
    })


# ── Surface constants ─────────────────────────────────────────────────────────

class TestSurfaceConstants:
    def test_all_surfaces_includes_four(self):
        assert set(ALL_SURFACES) == {"configs", "memory", "sessions", "scratch"}

    def test_classified_surfaces_excludes_configs(self):
        # configs is private (mode 0700), never group-classified
        assert "configs" not in CLASSIFIED_SURFACES
        assert set(CLASSIFIED_SURFACES) == {"memory", "sessions", "scratch"}


# ── resolve_surface_path (absolute) ───────────────────────────────────────────

class TestResolveAbsolute:
    def test_convention_path_classified_is_on_the_host(self):
        a = _agent(
            name="agent_arc_research_mz",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        assert resolve_surface_path(a, "memory") == (
            "/srv/agents/arc/agent_arc_research_mz/memory/"
        )

    def test_convention_path_configs_stays_on_beaver(self):
        """ADR-0010 §7 — and the shape differs, not just the prefix: the beaver
        layout keeps its `agents/` segment, the host layout does not.
        """
        a = _agent(
            name="agent_arc_research_mz",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        assert resolve_surface_path(a, "configs") == (
            "/mnt/raid/arc/agents/agent_arc_research_mz/configs/"
        )

    def test_the_two_roots_are_not_a_prefix_swap(self):
        """Guards the asymmetry directly: swapping only the root would give
        /srv/agents/arc/agents/<name>/, which is not the declared layout.
        """
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        classified = resolve_surface_path(a, "memory")
        private = resolve_surface_path(a, "configs")
        assert classified == CLASSIFIED_ROOT + "arc/agent_x/memory/"
        assert private == PRIVATE_ROOT + "arc/agents/agent_x/configs/"
        assert "/agents/" not in classified[len(CLASSIFIED_ROOT):]

    def test_top_org_no_special_case(self):
        a = _agent(
            name="agent_oversight",
            share_class={"org": "top", "grade": 0, "vertical": "any", "scope": "global"},
        )
        assert resolve_surface_path(a, "scratch") == (
            "/srv/agents/top/agent_oversight/scratch/"
        )

    def test_configs_override_wins(self):
        """configs is the one surface that may still be overridden (§8)."""
        a = _agent(
            name="agent_arc_finance",
            share_class={"org": "arc", "grade": 5, "vertical": "finance", "scope": "global"},
            shares={"configs": "/mnt/raid/elsewhere/cfg/"},
        )
        assert resolve_surface_path(a, "configs") == "/mnt/raid/elsewhere/cfg/"

    def test_configs_override_leaves_classified_on_convention(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/mnt/raid/custom/cfg/"},
        )
        assert resolve_surface_path(a, "configs") == "/mnt/raid/custom/cfg/"
        assert resolve_surface_path(a, "sessions") == (
            "/srv/agents/arc/agent_x/sessions/"
        )

    def test_no_share_class_no_path(self):
        a = _agent(name="agent_orphan")
        for surface in ALL_SURFACES:
            assert resolve_surface_path(a, surface) is None

    def test_trailing_slash_added_to_permitted_override(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/mnt/raid/foo/bar"},   # no trailing slash
        )
        assert resolve_surface_path(a, "configs") == "/mnt/raid/foo/bar/"

    def test_unknown_surface_rejected(self):
        a = _agent(name="agent_x")
        with pytest.raises(ValueError, match="unknown surface"):
            resolve_surface_path(a, "garbage")

    def test_root_for_maps_surfaces_to_declared_roots(self):
        for surface in CLASSIFIED_SURFACES:
            assert root_for(surface) == CLASSIFIED_ROOT
        for surface in PRIVATE_SURFACES:
            assert root_for(surface) == PRIVATE_ROOT

    def test_root_for_rejects_unknown_surface(self):
        with pytest.raises(ValueError, match="unknown surface"):
            root_for("garbage")


# ── resolve_surface_path_relative ─────────────────────────────────────────────

class TestResolveRelative:
    def test_classified_strips_the_host_root(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        assert resolve_surface_path_relative(a, "memory") == "arc/agent_x/memory/"

    def test_configs_strips_the_beaver_root(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        assert resolve_surface_path_relative(a, "configs") == (
            "arc/agents/agent_x/configs/"
        )

    def test_configs_override_under_its_own_root(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/mnt/raid/shared/pa_cfg/"},
        )
        assert resolve_surface_path_relative(a, "configs") == "shared/pa_cfg/"

    def test_configs_override_on_the_host_root_rejected(self):
        """The wrong-side check. Since ADR-0010 the two roots are different
        machines, so a configs path under the host root would be applied where
        the file does not exist.
        """
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/srv/agents/arc/agent_x/configs/"},
        )
        with pytest.raises(ValueError) as exc:
            resolve_surface_path_relative(a, "configs")
        msg = str(exc.value)
        assert "is not under" in msg
        assert "different host" in msg, "the error should say why, not just that"

    def test_configs_override_outside_every_root_rejected(self):
        a = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/var/lib/elsewhere/cfg/"},
        )
        with pytest.raises(ValueError, match="outside the declared roots"):
            resolve_surface_path_relative(a, "configs")

    def test_no_share_class_returns_none(self):
        a = _agent(name="agent_orphan")
        assert resolve_surface_path_relative(a, "memory") is None


# ── Cross-tool fixture (the shared contract with sync-compile) ────────────────

CROSS_TOOL_FIXTURE = Path(__file__).parent / "fixtures" / "cross_tool" / "agent_paths.yml"


def _load_cross_tool_cases():
    yaml = YAML()
    with CROSS_TOOL_FIXTURE.open(encoding="utf-8") as f:
        data = yaml.load(f)
    return data["cases"]


class TestCrossToolFixture:
    """The shared cross-tool fixture.

    ADR-0010 §7 re-scoped this contract from byte-identical ABSOLUTE paths to a
    shared STEM — rbac-compile resolves the host root, sync-compile and ingstr
    the beaver mount, over one tree. So `stem` is the cross-tool column and the
    `rbac_*` columns are ours. When sync-compile adopts the fixture, their test
    asserts `stem` with their own root stripped.
    """

    @pytest.mark.parametrize("case", _load_cross_tool_cases(), ids=lambda c: c["name"])
    def test_case_paths_match_fixture(self, case):
        agent = Agent.model_validate({
            "name": case["agent"]["name"],
            "access": [],
            **{k: v for k, v in case["agent"].items() if k != "name"},
        })
        for surface in ALL_SURFACES:
            expected = case["expected"][surface]

            if expected is None:
                assert resolve_surface_path(agent, surface) is None
                assert resolve_surface_path_relative(agent, surface) is None
                continue

            # ADR-0010 §8 — an override on a classified surface is refused
            if expected.get("rejected"):
                with pytest.raises(ValueError, match=r"ADR-0010 §8"):
                    resolve_surface_path(agent, surface)
                with pytest.raises(ValueError, match=r"ADR-0010 §8"):
                    resolve_surface_path_relative(agent, surface)
                continue

            assert resolve_surface_path(agent, surface) == expected["rbac_absolute"], (
                f"absolute mismatch for {case['name']}/{surface}"
            )

            # A permitted override on the wrong side of the root is not
            # classifiable, so the relative form raises rather than returning.
            if expected.get("rbac_relative_raises"):
                with pytest.raises(ValueError, match="is not under"):
                    resolve_surface_path_relative(agent, surface)
            else:
                assert (
                    resolve_surface_path_relative(agent, surface)
                    == expected["rbac_relative"]
                ), f"relative mismatch for {case['name']}/{surface}"

    @pytest.mark.parametrize("case", _load_cross_tool_cases(), ids=lambda c: c["name"])
    def test_stem_is_the_shared_contract(self, case):
        """The stem is what sync-compile and ingstr assert against. For a
        classified surface it must equal the rbac relative path — that identity
        is the whole content of the narrowed guarantee. configs carries a null
        stem: it never leaves beaver, so no other tool resolves it.
        """
        for surface, expected in case["expected"].items():
            if expected is None or expected.get("rejected"):
                continue
            stem = expected.get("stem")
            if surface in PRIVATE_SURFACES:
                assert stem is None, (
                    f"{case['name']}/{surface}: configs is not a shared surface, "
                    "its stem must be null"
                )
                continue
            assert stem is not None, f"{case['name']}/{surface}: missing stem"
            assert stem == expected["rbac_relative"], (
                f"{case['name']}/{surface}: stem must equal the rbac relative "
                "path for a classified surface"
            )
            assert expected["rbac_absolute"] == CLASSIFIED_ROOT + stem, (
                f"{case['name']}/{surface}: absolute must be the classified "
                "root plus the stem"
            )


class TestAdr0010Section8:
    """§8 — `shares:` overrides are rejected on the classified surfaces."""

    @staticmethod
    def _agent(**shares):
        return Agent.model_validate({
            "name": "agent_arc_x", "access": [],
            "share_class": {"org": "arc", "grade": 3,
                            "vertical": "tech", "scope": "mz"},
            "shares": shares,
        })

    @pytest.mark.parametrize("surface", ["memory", "sessions", "scratch"])
    def test_classified_override_rejected(self, surface):
        agent = self._agent(**{surface: f"/srv/agents/arc/agent_arc_x/{surface}/"})
        with pytest.raises(ValueError) as exc:
            resolve_surface_path(agent, surface)
        msg = str(exc.value)
        assert "ADR-0010 §8" in msg
        assert surface in msg, "the error must name the offending surface"

    def test_rejected_even_when_it_matches_the_convention(self):
        """An override identical to the path the convention would produce is
        still refused. The objection is to the mechanism, not the value: a
        per-agent override makes §7's root advisory wherever it is allowed.
        """
        agent = self._agent(memory="/srv/agents/arc/agent_arc_x/memory/")
        with pytest.raises(ValueError, match=r"ADR-0010 §8"):
            resolve_surface_path(agent, "memory")

    def test_configs_override_still_permitted(self):
        agent = self._agent(configs="/mnt/raid/arc/agents/agent_arc_x/elsewhere/")
        assert resolve_surface_path(agent, "configs") == (
            "/mnt/raid/arc/agents/agent_arc_x/elsewhere/"
        )

    def test_other_surfaces_unaffected_by_a_rejected_one(self):
        """A bad scratch override must not poison memory/sessions."""
        agent = self._agent(scratch="/mnt/raid/shared_drives/x/")
        assert resolve_surface_path(agent, "memory") == (
            "/srv/agents/arc/agent_arc_x/memory/"
        )
        with pytest.raises(ValueError, match=r"ADR-0010 §8"):
            resolve_surface_path(agent, "scratch")
