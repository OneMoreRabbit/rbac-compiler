"""Tests for core compilation logic — v0.4 lazy data-driven groups + agent shares."""

from pathlib import Path

from rbac_compiler.compiler import (
    UsedGroup,
    collect_used_groups,
    compile_plan,
    grant_matches_group,
    group_name,
    groups_for_agent,
)
from rbac_compiler.models import (
    AccessGrant,
    Agent,
    AgentRegistry,
    Constants,
    DataEntry,
    Meta,
    OrgDataFile,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_constants(admins: list[str] | None = None) -> Constants:
    data: dict = {"meta": {"version": "0.4"}}
    if admins is not None:
        data["admins"] = admins
    return Constants.model_validate(data)


def _make_org(
    org_key: str = "arc",
    max_grade: int = 4,
    verticals: list[str] | None = None,
    scopes: list[str] | None = None,
    data: list[dict] | None = None,
) -> OrgDataFile:
    return OrgDataFile.model_validate({
        "meta": {"version": "0.4"},
        "org_definition": {
            "key": org_key,
            "name": org_key.upper(),
            "verticals": verticals or ["any", "tech", "finance"],
            "scopes": scopes or ["global", "uk", "mz", "rw"],
            "grades": {i: "" for i in range(max_grade + 1)},
        },
        "data": data or [],
    })


def _grant(org: str = "arc", grade: int = 0, vertical: str = "tech", scope: str = "mz") -> AccessGrant:
    return AccessGrant(org=org, grade=grade, vertical=vertical, scope=scope)


def _agent(
    name: str = "agent_test",
    access: list[dict] | None = None,
    share_class: dict | None = None,
    sub_agents: list[str] | None = None,
    shares: dict | None = None,
) -> Agent:
    data: dict = {"name": name, "access": access or []}
    if share_class is not None:
        data["share_class"] = share_class
    if sub_agents is not None:
        data["sub_agents"] = sub_agents
    if shares is not None:
        data["shares"] = shares
    return Agent.model_validate(data)


# ── group_name ────────────────────────────────────────────────────────────────

class TestGroupName:
    def test_format(self):
        assert group_name("arc", 2, "finance", "global") == "arc_g2_finance_global"

    def test_wildcard_tokens(self):
        assert group_name("arc", 5, "any", "global") == "arc_g5_any_global"

    def test_top_org_no_special_case(self):
        assert group_name("top", 0, "any", "global") == "top_g0_any_global"


# ── collect_used_groups (org data + agent share_classes) ──────────────────────

class TestCollectUsedGroups:
    def test_empty_when_no_data_and_no_agents(self):
        org = _make_org("arc", data=[])
        result = collect_used_groups([(org, Path("arc.yml"))], agents=[])
        assert result == []

    def test_one_group_per_data_entry(self):
        org = _make_org("arc", data=[
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
            {"path": "arc/dirs/b", "grade": 3, "vertical": "finance", "scope": "mz"},
        ])
        result = collect_used_groups([(org, Path("arc.yml"))], agents=[])
        names = {g.name for g in result}
        assert names == {"arc_g2_tech_uk", "arc_g3_finance_mz"}

    def test_duplicate_classification_dedupes(self):
        org = _make_org("arc", data=[
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
            {"path": "arc/dirs/b", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        result = collect_used_groups([(org, Path("arc.yml"))], agents=[])
        assert len(result) == 1

    def test_share_class_joins_used_groups(self):
        """v0.4: agent share_class contributes its home group even without
        any org-data classification at that (grade, vertical, scope)."""
        org = _make_org("arc", data=[])
        agent = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        result = collect_used_groups([(org, Path("arc.yml"))], agents=[agent])
        names = {g.name for g in result}
        assert "arc_g3_tech_mz" in names

    def test_share_class_dedupes_with_org_data(self):
        """If both an org data entry and an agent share_class point at the
        same group, only one used_group is emitted."""
        org = _make_org("arc", data=[
            {"path": "arc/dirs/x", "grade": 3, "vertical": "tech", "scope": "mz"},
        ])
        agent = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        result = collect_used_groups([(org, Path("arc.yml"))], agents=[agent])
        names = [g.name for g in result]
        assert names.count("arc_g3_tech_mz") == 1


# ── grant_matches_group ───────────────────────────────────────────────────────

class TestGrantMatchesGroup:
    def _g(self, **kw) -> UsedGroup:
        defaults = {"name": "arc_g3_tech_uk", "org": "arc", "grade": 3, "vertical": "tech", "scope": "uk"}
        defaults.update(kw)
        return UsedGroup(**defaults)

    def test_direct_match(self):
        assert grant_matches_group(_grant(grade=3, vertical="tech", scope="uk"), self._g())

    def test_more_privileged_grade_matches(self):
        assert grant_matches_group(_grant(grade=1, vertical="tech", scope="uk"), self._g())

    def test_less_privileged_grade_does_not_match(self):
        assert not grant_matches_group(_grant(grade=4, vertical="tech", scope="uk"), self._g())

    def test_wrong_org_does_not_match(self):
        assert not grant_matches_group(
            _grant(org="cpf", grade=1, vertical="tech", scope="uk"), self._g()
        )

    def test_agent_any_matches_specific_vertical(self):
        assert grant_matches_group(_grant(grade=1, vertical="any", scope="uk"), self._g())

    def test_dir_any_matches_specific_agent_vertical(self):
        dir_any = self._g(vertical="any", name="arc_g3_any_uk")
        assert grant_matches_group(_grant(grade=1, vertical="tech", scope="uk"), dir_any)

    def test_vertical_mismatch(self):
        assert not grant_matches_group(_grant(grade=1, vertical="finance", scope="uk"), self._g())

    def test_agent_global_matches_specific_scope(self):
        assert grant_matches_group(_grant(grade=1, vertical="tech", scope="global"), self._g())

    def test_dir_global_matches_specific_agent_scope(self):
        dir_global = self._g(scope="global", name="arc_g3_tech_global")
        assert grant_matches_group(_grant(grade=1, vertical="tech", scope="uk"), dir_global)

    def test_scope_mismatch(self):
        assert not grant_matches_group(_grant(grade=1, vertical="tech", scope="mz"), self._g())


# ── groups_for_agent (with v0.4 self-grant) ───────────────────────────────────

class TestGroupsForAgent:
    def test_no_used_groups_no_memberships(self):
        agent = _agent(access=[_grant().model_dump()])
        assert groups_for_agent(agent, []) == []

    def test_sorted_output(self):
        used = [
            UsedGroup(name="arc_g3_tech_uk", org="arc", grade=3, vertical="tech", scope="uk"),
            UsedGroup(name="arc_g2_tech_uk", org="arc", grade=2, vertical="tech", scope="uk"),
        ]
        agent = _agent(access=[{"org": "arc", "grade": 1, "vertical": "any", "scope": "global"}])
        result = groups_for_agent(agent, used)
        assert result == sorted(result)
        assert result == ["arc_g2_tech_uk", "arc_g3_tech_uk"]

    def test_self_grant_makes_agent_member_of_own_home_group(self):
        """v0.4: an agent with share_class is automatically in that group,
        even with no access[] grants."""
        used = [
            UsedGroup(
                name="arc_g3_tech_mz", org="arc", grade=3, vertical="tech", scope="mz"
            ),
        ]
        agent = _agent(
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        result = groups_for_agent(agent, used)
        assert result == ["arc_g3_tech_mz"]

    def test_self_grant_works_with_explicit_access(self):
        """Effective access = declared access[] + implicit self-grant."""
        used = [
            UsedGroup(name="arc_g3_tech_mz", org="arc", grade=3, vertical="tech", scope="mz"),
            UsedGroup(name="cpf_g2_advisory_uk", org="cpf", grade=2, vertical="advisory", scope="uk"),
        ]
        agent = _agent(
            access=[{"org": "cpf", "grade": 2, "vertical": "advisory", "scope": "uk"}],
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        result = groups_for_agent(agent, used)
        assert set(result) == {"arc_g3_tech_mz", "cpf_g2_advisory_uk"}


# ── compile_plan (worked example from the v0.3 brief, validated under v0.4) ──

class TestCompilePlanWorkedExample:
    """Reference scenario from RBAC_Compiler_v0_3_Brief.md §Tests. Carried
    through v0.4 unchanged — agents in this scenario have no share_class,
    so no surfaces are emitted, only data-defined classifications matter."""

    def setup_method(self):
        self.constants = _make_constants()
        self.org = _make_org(
            "arc",
            max_grade=4,
            verticals=["any", "tech", "commercial", "engineering", "finance", "ops"],
            scopes=["global", "uk", "mz", "rw", "za", "zm"],
            data=[
                {"path": "arc/dirs/t_uk", "grade": 2, "vertical": "tech", "scope": "uk"},
                {"path": "arc/dirs/t_mz", "grade": 2, "vertical": "tech", "scope": "mz"},
                {"path": "arc/dirs/t_rw", "grade": 4, "vertical": "tech", "scope": "rw"},
                {"path": "arc/dirs/any_uk", "grade": 3, "vertical": "any", "scope": "uk"},
                {"path": "arc/dirs/any_global", "grade": 3, "vertical": "any", "scope": "global"},
            ],
        )
        self.agents = AgentRegistry(meta=Meta(version="0.4"), agents=[
            Agent(name="agent_1", access=[_grant(org="arc", grade=1, vertical="any", scope="global")]),
            Agent(name="agent_2", access=[_grant(org="arc", grade=2, vertical="any", scope="mz")]),
            Agent(name="agent_3", access=[_grant(org="arc", grade=3, vertical="tech", scope="global")]),
        ])
        self.org_files = [(self.org, Path("arc.yml"))]

    def test_required_groups_is_exactly_data_defined(self):
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        assert set(plan.required_groups) == {
            "arc_g2_tech_uk", "arc_g2_tech_mz", "arc_g4_tech_rw",
            "arc_g3_any_uk", "arc_g3_any_global",
        }

    def test_agent_1_matches_all_five(self):
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        agent_1 = next(au for au in plan.agent_users if au.name == "agent_1")
        assert len(agent_1.groups) == 5

    def test_agent_2_matches_grade_le_2_scope_mz_or_global(self):
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        agent_2 = next(au for au in plan.agent_users if au.name == "agent_2")
        assert set(agent_2.groups) == {"arc_g2_tech_mz", "arc_g3_any_global"}

    def test_agent_3_matches_grade_le_3_tech_or_any_scope_global(self):
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        agent_3 = next(au for au in plan.agent_users if au.name == "agent_3")
        assert set(agent_3.groups) == {"arc_g3_any_global", "arc_g3_any_uk", "arc_g4_tech_rw"}


# ── v0.4 agent share surfaces ─────────────────────────────────────────────────

class TestAgentSurfaceClassifications:
    def setup_method(self):
        self.constants = _make_constants()
        self.org = _make_org("arc")
        self.agent = _agent(
            name="agent_arc_research_mz",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
        )
        self.agents = AgentRegistry(meta=Meta(version="0.4"), agents=[self.agent])
        self.org_files = [(self.org, Path("arc.yml"))]

    def test_three_classifications_per_agent_with_share_class(self):
        """One per classified surface (memory, sessions, scratch). No configs.
        No per-sub-agent multiplication."""
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        agent_paths = [
            dc.path for dc in plan.directory_classifications
            if "agents/agent_arc_research_mz" in dc.path
        ]
        assert set(agent_paths) == {
            "arc/agents/agent_arc_research_mz/memory/",
            "arc/agents/agent_arc_research_mz/sessions/",
            "arc/agents/agent_arc_research_mz/scratch/",
        }

    def test_configs_surface_not_in_directory_classifications(self):
        """configs/ has no RBAC group — it must NOT appear in
        directory_classifications (would pollute group cross-referencing)."""
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        configs_entries = [
            dc for dc in plan.directory_classifications
            if "/configs/" in dc.path
        ]
        assert configs_entries == []

    def test_configs_surface_in_agent_private_dirs(self):
        """v0.4.1: configs/ is emitted as an agent_private_dir so the apply
        playbook materialises it (mode 0700, owned by the agent user)."""
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        assert len(plan.agent_private_dirs) == 1
        pd = plan.agent_private_dirs[0]
        assert pd.path == "arc/agents/agent_arc_research_mz/configs/"
        assert pd.owner == "agent_arc_research_mz"
        assert pd.mode == "0700"

    def test_no_private_dir_without_share_class(self):
        agent = _agent(name="agent_orphan", access=[
            {"org": "arc", "grade": 5, "vertical": "tech", "scope": "uk"},
        ])
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, _ = compile_plan(self.constants, self.org_files, agents, {}, {})
        assert plan.agent_private_dirs == []

    def test_private_dirs_sorted_by_path(self):
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[
            _agent(name="agent_zzz", share_class={
                "org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"}),
            _agent(name="agent_aaa", share_class={
                "org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"}),
        ])
        plan, _ = compile_plan(self.constants, self.org_files, agents, {}, {})
        paths = [pd.path for pd in plan.agent_private_dirs]
        assert paths == sorted(paths)

    def test_configs_shares_override_honoured(self):
        agent = _agent(
            name="agent_x",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            shares={"configs": "/mnt/raid/arc/custom/cfg/"},
        )
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, _ = compile_plan(self.constants, self.org_files, agents, {}, {})
        assert plan.agent_private_dirs[0].path == "arc/custom/cfg/"

    def test_surface_classifications_owned_by_agent_user(self):
        plan, _ = compile_plan(self.constants, self.org_files, self.agents, {}, {})
        agent_entries = [
            dc for dc in plan.directory_classifications
            if "agents/agent_arc_research_mz" in dc.path
        ]
        for dc in agent_entries:
            assert dc.owner == "agent_arc_research_mz"

    def test_org_data_classifications_owned_by_root(self):
        """v0.4 introduces the owner field; existing org data classifications
        default to root."""
        org = _make_org("arc", data=[
            {"path": "arc/dropbox/x", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        plan, _ = compile_plan(
            self.constants, [(org, Path("arc.yml"))],
            AgentRegistry(meta=Meta(version="0.4"), agents=[]),
            {}, {},
        )
        for dc in plan.directory_classifications:
            assert dc.owner == "root"

    def test_no_surface_emission_without_share_class(self):
        agent = _agent(name="agent_orphan", access=[
            {"org": "arc", "grade": 5, "vertical": "tech", "scope": "uk"},
        ])
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, warnings = compile_plan(
            self.constants, self.org_files, agents, {}, {},
        )
        agent_entries = [
            dc for dc in plan.directory_classifications
            if "agent_orphan" in dc.path
        ]
        assert agent_entries == []
        # Warns because the agent has access[] but no share_class — likely
        # not what the operator intended.
        assert any("agent_orphan" in w and "share_class" in w for w in warnings)

    def test_sub_agents_do_not_multiply_classifications(self):
        """v0.4: sub-agents are runtime artefacts; rbac-compile emits 3 (not
        3*(1+N)) classifications per agent regardless of sub_agents."""
        agent = _agent(
            name="agent_with_subs",
            share_class={"org": "arc", "grade": 3, "vertical": "tech", "scope": "mz"},
            sub_agents=["literature_review", "fact_check", "summarise"],
        )
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, _ = compile_plan(self.constants, self.org_files, agents, {}, {})
        agent_entries = [
            dc for dc in plan.directory_classifications
            if "agent_with_subs" in dc.path
        ]
        assert len(agent_entries) == 3  # one per classified surface

    def test_shares_override_emits_overridden_path(self):
        agent = _agent(
            name="agent_arc_finance",
            share_class={"org": "arc", "grade": 5, "vertical": "finance", "scope": "global"},
            shares={"scratch": "/mnt/raid/shared_drives/pa_scratch/"},
        )
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, _ = compile_plan(self.constants, self.org_files, agents, {}, {})
        # Filter by description (path no longer ends in "/scratch/" since it
        # was overridden to /mnt/raid/shared_drives/pa_scratch/).
        scratch = next(
            dc for dc in plan.directory_classifications
            if (dc.description or "").endswith("agent_arc_finance scratch surface")
        )
        assert scratch.path == "shared_drives/pa_scratch/"

    def test_top_org_agent_no_special_case(self):
        """A top-org agent emits classifications under top/agents/<name>/..."""
        top_org = _make_org("top", verticals=["any"], scopes=["global"], max_grade=0)
        agent = _agent(
            name="agent_oversight",
            share_class={"org": "top", "grade": 0, "vertical": "any", "scope": "global"},
        )
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[agent])
        plan, _ = compile_plan(
            self.constants,
            [(top_org, Path("top.yml"))],
            agents, {}, {},
        )
        agent_paths = [
            dc.path for dc in plan.directory_classifications
            if "agent_oversight" in dc.path
        ]
        assert set(agent_paths) == {
            "top/agents/agent_oversight/memory/",
            "top/agents/agent_oversight/sessions/",
            "top/agents/agent_oversight/scratch/",
        }


# ── compile_plan — admins, warnings, structure ────────────────────────────────

class TestAdminUsers:
    def test_admin_user_in_every_required_group(self):
        constants = _make_constants(admins=["beaver"])
        org = _make_org("arc", data=[
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        plan, _ = compile_plan(
            constants, [(org, Path("arc.yml"))],
            AgentRegistry(meta=Meta(version="0.4"), agents=[]), {}, {},
        )
        assert plan.admin_users[0].name == "beaver"
        assert set(plan.admin_users[0].groups) == set(plan.required_groups)


class TestCompileWarnings:
    def test_empty_data_warns(self):
        _, warnings = compile_plan(
            _make_constants(),
            [(_make_org("arc", data=[]), Path("arc.yml"))],
            AgentRegistry(meta=Meta(version="0.4"), agents=[]), {}, {},
        )
        assert any("no directory classifications" in w for w in warnings)

    def test_unmatched_agent_warns(self):
        constants = _make_constants()
        org = _make_org("arc", data=[
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[
            Agent(name="agent_niche", access=[
                _grant(grade=3, vertical="finance", scope="mz"),
            ]),
        ])
        _, warnings = compile_plan(constants, [(org, Path("arc.yml"))], agents, {}, {})
        assert any("agent_niche" in w and "matches no" in w for w in warnings)


class TestCompilePlanStructure:
    def test_directory_classifications_sorted_by_path(self):
        constants = _make_constants()
        org = _make_org("arc", data=[
            {"path": "arc/dirs/z", "grade": 2, "vertical": "tech", "scope": "uk"},
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        plan, _ = compile_plan(
            constants, [(org, Path("arc.yml"))],
            AgentRegistry(meta=Meta(version="0.4"), agents=[]), {}, {},
        )
        paths = [dc.path for dc in plan.directory_classifications]
        assert paths == sorted(paths)

    def test_version_bumped(self):
        constants = _make_constants()
        org = _make_org("arc", data=[
            {"path": "arc/dirs/a", "grade": 2, "vertical": "tech", "scope": "uk"},
        ])
        plan, _ = compile_plan(
            constants, [(org, Path("arc.yml"))],
            AgentRegistry(meta=Meta(version="0.4"), agents=[]), {}, {},
        )
        assert plan.compiler_version == "0.5.0"
        assert plan.schema_version == "0.4"


class TestContractGuarantees:
    """Tests for the guarantees `compiled-rbac-plan` v0.5 states to consumers.

    Added 2026-09-13 after auditing the contract against the suite. The
    cross-reference guarantee below was **published to ansible-platform and
    ingstr with nothing asserting it** — the same shape as the determinism
    clause: a promise in `provides/` that no test would have caught the breaking
    of. A contract guarantee is worse to leave untested than a docstring,
    because a consumer builds against it.

    Instance of `checks-that-pass-for-the-wrong-reason`: the remedy that
    document prescribes is a test asserting the shipped behaviour, carrying the
    incident in its docstring. This is that test.
    """

    def _plan(self):
        constants = _make_constants()
        agents = AgentRegistry(meta=Meta(version="0.4"), agents=[
            _agent(name="agent_arc_x",
                   share_class={"org": "arc", "grade": 3,
                                "vertical": "tech", "scope": "mz"}),
        ])
        plan, _ = compile_plan(
            constants, [(_make_org("arc"), Path("arc.yml"))], agents, {}, {})
        return plan

    def test_every_classification_group_is_in_required_groups(self):
        """The v0.5 guarantee, verbatim: "Every `directory_classifications[].group`
        is a member of `required_groups`." It is also the stated *reason*
        `configs/` is carried in `agent_private_dirs` instead, so a consumer
        cross-referencing the two lists depends on it.
        """
        plan = self._plan()
        required = set(plan.required_groups)
        for dc in plan.directory_classifications:
            assert dc.group in required, (
                f"classification '{dc.path}' names group '{dc.group}', which is "
                f"not in required_groups — this breaks the cross-reference "
                f"guarantee published in compiled-rbac-plan v0.5"
            )

    def test_agent_private_dirs_carry_no_group_at_all(self):
        """The other half of the same guarantee: `configs/` is kept out of
        directory_classifications precisely because it has no RBAC group. If an
        AgentPrivateDir ever gained one, the separation would be pointless and
        the cross-reference above would start failing instead.
        """
        for pd in self._plan().agent_private_dirs:
            assert not hasattr(pd, "group"), (
                "agent_private_dirs must carry no group — that is why they are "
                "a separate section"
            )

    def test_every_user_group_is_in_required_groups(self):
        """Not stated as a guarantee in v0.5, but a consumer creating users from
        the plan and groups from required_groups would fail on any group named
        only in agent_users. Asserted so that if it ever stops holding it is a
        deliberate contract change rather than a surprise at apply time.
        """
        plan = self._plan()
        required = set(plan.required_groups)
        for au in plan.agent_users:
            for g in au.groups:
                assert g in required, f"agent_users[{au.name}] names '{g}'"
        for ad in plan.admin_users:
            for g in ad.groups:
                assert g in required, f"admin_users[{ad.name}] names '{g}'"
