"""Tests for the high-level operations layer (consumed by CLI and future GUI)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from rbac_compiler.operations import (
    CompileResult,
    ValidateResult,
    compile_registry,
    load_registry,
    validate,
)

FIXTURES = Path(__file__).parent / "fixtures"
VALID = FIXTURES / "valid"
INVALID = FIXTURES / "invalid"


class TestLoadRegistry:
    def test_loads_everything(self):
        loaded = load_registry(VALID)
        assert loaded.constants is not None
        assert len(loaded.org_files) == 3
        assert {of.org for of, _ in loaded.org_files} == {"arc", "cpf", "top"}
        assert loaded.agent_registry is not None
        assert loaded.constants_hash
        assert loaded.agents_hash
        assert set(loaded.org_hashes.keys()) == {"arc", "cpf", "top"}


class TestValidate:
    def test_valid_registry_ok(self):
        result: ValidateResult = validate(VALID)
        assert result.validation.ok
        assert result.loaded is not None

    def test_bad_grade_not_ok(self, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        shutil.copy(
            INVALID / "bad_grade" / "orgs" / "arc.yml",
            reg / "orgs" / "arc.yml",
        )
        result = validate(reg)
        assert not result.validation.ok


class TestCompileRegistry:
    def test_check_only_does_not_write(self, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        result: CompileResult = compile_registry(reg, check_only=True)
        assert result.validation.ok
        assert result.plan is not None
        assert result.output_path is None
        assert not (reg / ".compiled").exists()

    def test_writes_default_path(self, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        result = compile_registry(reg)
        assert result.validation.ok
        assert result.output_path == reg / ".compiled" / "compiled_plan.yml"
        assert result.output_path.exists()

    def test_writes_explicit_output(self, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        out = tmp_path / "plan.yml"
        result = compile_registry(reg, output=out)
        assert result.output_path == out
        assert out.exists()

    def test_validation_failure_returns_no_plan(self, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        shutil.copy(
            INVALID / "bad_grade" / "orgs" / "arc.yml",
            reg / "orgs" / "arc.yml",
        )
        result = compile_registry(reg)
        assert not result.validation.ok
        assert result.plan is None
        assert result.output_path is None


class TestDeterminism:
    """Same registry state -> same plan, byte for byte.

    ansible-platform's second ask in `ansible-needs-plan-contracts-v0_1`, and
    answered in `rbac-compile-plan-contracts-response-v0_1` with the gap stated
    plainly: the property held by construction, but nothing failed if someone
    broke it. This is that test.

    The form is compile-twice-compare-bytes rather than a property assertion on
    the dataclass, deliberately: what the consumer reads is the emitted file, so
    that is what must be identical. A test over the in-memory plan would pass
    while the emitter introduced ordering of its own.
    """

    REGISTRY = Path(__file__).parent / "fixtures" / "valid"

    def _emit(self, tmp_path: Path, name: str) -> Path:
        out = tmp_path / name / "compiled_plan.yml"
        compile_registry(registry_dir=self.REGISTRY, output=out)
        return out

    def test_two_compiles_differ_only_in_compiled_at(self, tmp_path):
        """The honest form: rather than excluding `compiled_at` and comparing the
        rest, assert that it is the ONLY line that differs. Excluding a field
        proves nothing about the fields you forgot to exclude.
        """
        a = self._emit(tmp_path, "a").read_text(encoding="utf-8").splitlines()
        b = self._emit(tmp_path, "b").read_text(encoding="utf-8").splitlines()

        assert len(a) == len(b), "plans differ in line count"
        differing = [
            (i, x, y) for i, (x, y) in enumerate(zip(a, b), start=1) if x != y
        ]
        for _, x, _ in differing:
            assert x.strip().startswith("compiled_at:"), (
                f"a non-timestamp line differs between two compiles of the same "
                f"registry: {x!r}"
            )
        assert len(differing) <= 1, differing

    def test_bytes_identical_with_the_clock_frozen(self, tmp_path, monkeypatch):
        """With `compiled_at` pinned there must be no difference at all — this is
        the assertion that actually catches set iteration, dict ordering and an
        unsorted append.
        """
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)

        class _Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        monkeypatch.setattr("rbac_compiler.compiler.datetime", _Frozen)

        first = self._emit(tmp_path, "one").read_bytes()
        second = self._emit(tmp_path, "two").read_bytes()
        assert first == second, "two compiles of one registry produced different bytes"

    def test_source_hashes_are_stable_across_compiles(self, tmp_path):
        """`source_hashes` is what the contract offers consumers as the statement
        of provenance, so it must not itself vary run to run.
        """
        r1 = compile_registry(
            registry_dir=self.REGISTRY, output=tmp_path / "h1" / "p.yml")
        r2 = compile_registry(
            registry_dir=self.REGISTRY, output=tmp_path / "h2" / "p.yml")
        assert r1.plan.source_hashes == r2.plan.source_hashes

    def test_ordering_is_explicit_not_incidental(self, tmp_path):
        """Every emitted list the consumer iterates must come out sorted. A dict
        or set upstream can produce a stable order within one process and a
        different one in the next, so equality between two compiles in the SAME
        process is not sufficient evidence on its own.
        """
        r = compile_registry(
            registry_dir=self.REGISTRY, output=tmp_path / "o" / "p.yml")
        plan = r.plan
        assert plan.required_groups == sorted(plan.required_groups)
        assert [d.path for d in plan.directory_classifications] == sorted(
            d.path for d in plan.directory_classifications)
        assert [d.path for d in plan.agent_private_dirs] == sorted(
            d.path for d in plan.agent_private_dirs)
        for au in plan.agent_users:
            assert au.groups == sorted(au.groups), au.name
        for ad in plan.admin_users:
            assert ad.groups == sorted(ad.groups), ad.name
