"""Integration tests for the CLI."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from rbac_compiler.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
VALID = FIXTURES / "valid"


@pytest.fixture
def runner():
    return CliRunner()


class TestCheckMode:
    def test_valid_registry_check_exits_0(self, runner):
        result = runner.invoke(cli, ["--registry-dir", str(VALID), "--check"])
        assert result.exit_code == 0, result.output

    def test_valid_registry_check_reports_counts(self, runner):
        result = runner.invoke(cli, ["--registry-dir", str(VALID), "--check"])
        assert "org" in result.output

    def test_check_quiet_produces_no_output(self, runner):
        result = runner.invoke(cli, ["--registry-dir", str(VALID), "--check", "--quiet"])
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_bad_grade_check_exits_1(self, runner, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        shutil.copy(
            FIXTURES / "invalid" / "bad_grade" / "orgs" / "arc.yml",
            reg / "orgs" / "arc.yml",
        )
        result = runner.invoke(cli, ["--registry-dir", str(reg), "--check"])
        assert result.exit_code == 1

    def test_missing_file_exits_2(self, runner, tmp_path):
        result = runner.invoke(cli, ["--registry-dir", str(tmp_path / "nonexistent")])
        assert result.exit_code == 2


class TestCompileMode:
    def test_valid_registry_compiles(self, runner, tmp_path):
        output = tmp_path / "plan.yml"
        result = runner.invoke(cli, [
            "--registry-dir", str(VALID),
            "--output", str(output),
        ])
        assert result.exit_code == 0, result.output
        assert output.exists()

    def test_output_contains_data_defined_group(self, runner, tmp_path):
        output = tmp_path / "plan.yml"
        runner.invoke(cli, ["--registry-dir", str(VALID), "--output", str(output)])
        content = output.read_text()
        assert "arc_g2_finance_global" in content

    def test_output_does_not_contain_fileserver_admins(self, runner, tmp_path):
        """v0.3 dropped the implicit fileserver_admins group."""
        output = tmp_path / "plan.yml"
        runner.invoke(cli, ["--registry-dir", str(VALID), "--output", str(output)])
        content = output.read_text()
        assert "fileserver_admins" not in content

    def test_output_contains_admin_users_section(self, runner, tmp_path):
        output = tmp_path / "plan.yml"
        runner.invoke(cli, ["--registry-dir", str(VALID), "--output", str(output)])
        content = output.read_text()
        assert "admin_users:" in content
        assert "beaver" in content

    def test_json_format_output(self, runner, tmp_path):
        import json
        output = tmp_path / "plan.json"
        result = runner.invoke(cli, [
            "--registry-dir", str(VALID),
            "--output", str(output),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(output.read_text())
        assert "required_groups" in data
        assert "agent_users" in data
        assert "admin_users" in data
        assert "directory_classifications" in data
        assert "agent_private_dirs" in data

    def test_output_reports_counts(self, runner, tmp_path):
        output = tmp_path / "plan.yml"
        result = runner.invoke(cli, ["--registry-dir", str(VALID), "--output", str(output)])
        assert "groups" in result.output
        assert "agents" in result.output
        assert "admins" in result.output
        assert "directories" in result.output

    def test_default_output_path_in_compiled_dir(self, runner, tmp_path):
        import shutil
        reg = tmp_path / "registry"
        shutil.copytree(VALID, reg)
        result = runner.invoke(cli, ["--registry-dir", str(reg)])
        assert result.exit_code == 0
        assert (reg / ".compiled" / "compiled_plan.yml").exists()

    def test_verbose_flag_accepted(self, runner, tmp_path):
        output = tmp_path / "plan.yml"
        result = runner.invoke(cli, [
            "--registry-dir", str(VALID),
            "--output", str(output),
            "--verbose",
        ])
        assert result.exit_code == 0

    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.5.0" in result.output
