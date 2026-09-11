import asyncio
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import zipfile
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/imap-dashboard/src"))

from nexin_mail import diagnostics, install as installer
from nexin_mail.package import PackageError, contained, digest, registration, verify
from imap_plugin import windows_host
from scripts.release_check import inspect_archive


def seal(root):
    files = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
             for p in sorted(root.rglob("*")) if p.is_file() and p.name != "package-manifest.json"]
    (root / "package-manifest.json").write_text(json.dumps({"schema": 1, "product": "nexin-mail", "version": "0.2.0", "files": files}))


@pytest.fixture
def package(tmp_path):
    root = tmp_path / "download met spaties é"
    (root / "payload/runtime/python").mkdir(parents=True)
    (root / "payload/runtime/python/python.exe").write_bytes(b"synthetic runtime fixture")
    (root / "skills/nexin-mail").mkdir(parents=True)
    (root / "skills/nexin-mail/SKILL.md").write_text("fixture")
    (root / "plugin.json").write_text(json.dumps({"name": "nexin-mail", "version": "0.2.0"}))
    seal(root)
    return root


class CodexStub:
    def __init__(self, rows=None, fail_add=False):
        self.rows = rows or []
        self.calls = []
        self.fail_add = fail_add

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if "-c" in args:
            return "nexin-mail-runtime-ready\n"
        if args[1:4] == ["plugin", "marketplace", "list"]:
            return json.dumps({"marketplaces": self.rows})
        if args[1:4] == ["plugin", "marketplace", "add"]:
            self.rows.append({"name": "nexin-mail", "root": args[4]})
        if args[1:4] == ["plugin", "marketplace", "remove"]:
            self.rows[:] = [row for row in self.rows if row["name"] != args[4]]
        if args[1:3] == ["plugin", "remove"]:
            return "{}"
        if args[1:3] == ["plugin", "add"] and self.fail_add:
            raise installer.InstallError("codex_failed", "host")
        return "{}"


def test_installs_immutable_payload_and_one_plugin_without_mailbox_access(package, tmp_path):
    before = digest(package / "package-manifest.json")
    calls, events = CodexStub(), []
    dest = tmp_path / "Local AppData é/Nexin Mail"
    result = installer.install(package, dest, Path("codex.exe"), events, runner=calls)
    assert result["registration"] == "verified"
    assert result["installation_complete"] is False
    assert result["status"] == "registration_only"
    assert result["mailbox"] == result["dashboard"] == "not_checked"
    assert digest(package / "package-manifest.json") == before
    installed = dest / "packages" / before
    verify(installed)
    mcp = json.loads((dest / "registry/plugins/nexin-mail/.mcp.json").read_text(encoding="utf-8"))
    assert set(mcp["mcpServers"]) == {"mail"}
    config = mcp["mcpServers"]["mail"]
    assert Path(config["command"]).is_absolute()
    assert Path(config["command"]).is_file()
    assert config["command"].endswith("python.exe")
    assert config["args"][-2:] == ["-m", "nexin_mail.server"]
    assert not any(any(word in str(arg) for word in ("open_setup", "doctor", "pip", "smtp")) for call in calls.calls for arg in call)


def test_finder_metadata_is_ignored_but_payload_tampering_is_rejected(package, tmp_path):
    (package / ".DS_Store").write_bytes(b"Finder metadata")
    (package / "payload/.DS_Store").write_bytes(b"Finder metadata")
    assert verify(package)["product"] == "nexin-mail"

    (package / "payload/extra.bin").write_bytes(b"unlisted payload")
    with pytest.raises(PackageError, match="Unlisted or missing"):
        verify(package)


def test_install_ignores_finder_metadata_and_preserves_runtime_mode(package, tmp_path):
    (package / ".DS_Store").write_bytes(b"Finder metadata")
    (package / "payload/.DS_Store").write_bytes(b"Finder metadata")
    runtime = package / "payload/runtime/python/python.exe"
    runtime.chmod(0o755)
    source_mode = stat.S_IMODE(runtime.stat().st_mode)

    destination = tmp_path / "install"
    result = installer.install(package, destination, Path("codex.exe"), [], runner=CodexStub())
    installed = destination / "packages" / result["package_hash"]
    assert stat.S_IMODE((installed / "payload/runtime/python/python.exe").stat().st_mode) == source_mode
    assert not list(installed.rglob(".DS_Store"))


def test_registration_supports_private_macos_runtime_and_pins_source_path(tmp_path):
    payload = tmp_path / "packages/hash/payload"
    (payload / "runtime/python/bin").mkdir(parents=True)
    runtime = payload / "runtime/python/bin/python3"
    runtime.write_bytes(b"synthetic macOS runtime")
    value = registration(payload, "0.2.0")
    config = value["mcpServers"]["mail"]
    assert config["command"] == str(runtime)
    assert config["env"]["PYTHONPATH"] == str(payload / "src")
    assert config["args"][-2:] == ["-m", "nexin_mail.server"]


def test_same_package_resume_does_not_duplicate_marketplace(package, tmp_path):
    calls = CodexStub()
    for _ in range(2):
        installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls)
    assert sum(c[1:4] == ["plugin", "marketplace", "add"] for c in calls.calls) == 1


def test_registration_failure_is_not_success_and_resume_preserves_package(package, tmp_path):
    calls = CodexStub(fail_add=True)
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls)
    assert failed.value.code == "registration_failed"
    calls.fail_add = False
    assert installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls)["registration"] == "verified"


@pytest.mark.parametrize("rows", [[{"name": "nexin-mail", "root": "/unknown"}], [{"name": "imap-plugin-handoff", "root": "/legacy"}]])
def test_preserves_foreign_and_legacy_installations(package, tmp_path, rows):
    calls = CodexStub(rows)
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls)
    assert failed.value.code == "installation_conflict"
    assert not (tmp_path / "install").exists()
    assert not any("add" in c for c in calls.calls)


def test_tamper_rejected_before_execution(package, tmp_path):
    (package / "payload/runtime/python/python.exe").write_bytes(b"changed")
    calls = CodexStub()
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls)
    assert failed.value.code == "package_invalid"
    assert calls.calls == []


@pytest.mark.parametrize("bad", ["../outside", "/outside", "C:/outside", "a:stream", "a\\b", "a/../b", "./a", "a//b", "a. /b", "CON.txt", "a/NUL", "name?.py"])
def test_windows_manifest_paths_cannot_escape(tmp_path, bad):
    with pytest.raises(PackageError):
        contained(tmp_path, bad)


def test_unlisted_files_and_symlinks_rejected(package, tmp_path):
    (package / "extra.py").write_text("unlisted")
    with pytest.raises(PackageError):
        verify(package)
    (package / "extra.py").unlink()
    target = tmp_path / "secret"
    target.write_text("synthetic")
    (package / "link").symlink_to(target)
    with pytest.raises(PackageError):
        verify(package)


def test_duplicate_manifest_keys_are_rejected(package):
    manifest = (package / "package-manifest.json").read_text()
    (package / "package-manifest.json").write_text(manifest.replace('"schema": 1', '"schema": 1, "schema": 1', 1))
    with pytest.raises(PackageError):
        verify(package)


@pytest.mark.parametrize("unsafe_name", ["CON.txt", "folder/trailing.", "folder/name?.py"])
def test_release_archive_rejects_windows_unsafe_paths(tmp_path, unsafe_name):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(unsafe_name, b"synthetic")
        stream.writestr("package-manifest.json", b"{}")
    with pytest.raises(ValueError, match="unsafe path"):
        inspect_archive(archive)


def test_repair_reports_reject_free_text_and_extra_fields(tmp_path):
    item = diagnostics.event("runtime", "blocked", "runtime_failed")
    value = diagnostics.report("0.2.0", [item])
    file = diagnostics.save_report(tmp_path, value)
    assert json.loads(file.read_text()) == value
    with pytest.raises(ValueError):
        diagnostics.report("0.2.0", [{**item, "stderr": "synthetic confidential input"}])
    with pytest.raises(ValueError):
        diagnostics.report("0.2.0", [{**item, "code": "username@customer.test"}])
    with pytest.raises(ValueError):
        diagnostics.save_report(tmp_path, {**value, "logs": "private"})


def test_repair_report_does_not_follow_diagnostic_symlink(tmp_path):
    item = diagnostics.event("runtime", "blocked", "runtime_failed")
    value = diagnostics.report("0.2.0", [item])
    target = tmp_path / "foreign"
    target.mkdir()
    link = tmp_path / "diagnostics"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        diagnostics.save_report(link, value)
    assert not list(target.iterdir())


def test_unknown_codex_schema_is_not_assumed_compatible():
    for value in ("{}", "[]", '{"marketplaces":[{"name":"x"}]}', "not json"):
        with pytest.raises(installer.InstallError):
            installer.read_marketplaces(value)


def test_marketplace_vendor_metadata_is_accepted_but_not_trusted():
    output = json.dumps({"marketplaces": [
        {"name": "openai-bundled", "root": "/vendor", "marketplaceSource": {
            "sourceType": "local", "source": "/vendor/source",
        }},
        {"name": "git-marketplace", "root": "/git", "marketplaceSource": {
            "sourceType": "git", "source": "https://github.com/anthropics/claude-plugins-official.git",
        }},
        {"name": "personal", "root": "/local"},
    ]})
    assert installer.read_marketplaces(output) == [
        {"name": "openai-bundled", "root": "/vendor"},
        {"name": "git-marketplace", "root": "/git"},
        {"name": "personal", "root": "/local"},
    ]
    with pytest.raises(installer.InstallError):
        installer.read_marketplaces(json.dumps({"marketplaces": [
            {"name": "official", "root": "/vendor", "marketplaceSource": "vendor-registry"},
        ]}))
    with pytest.raises(installer.InstallError):
        installer.read_marketplaces(json.dumps({"marketplaces": [
            {"name": "official", "root": "/vendor", "marketplaceSource": {
                "sourceType": "local", "source": "/vendor/source", "extra": True,
            }},
        ]}))


@pytest.mark.parametrize("mode", ["ConstrainedLanguage", "RestrictedLanguage", "NoLanguage"])
def test_windows_restrictions_do_not_trigger_host_switch(monkeypatch, mode):
    monkeypatch.setenv("IMAP_PLUGIN_POWERSHELL", "pwsh.exe")
    monkeypatch.setattr(Path, "is_file", lambda _: True)
    calls = []
    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"effective": "RemoteSigned", "language": mode}))
    monkeypatch.setattr(windows_host.subprocess, "run", run)
    with pytest.raises(windows_host.PowerShellUnavailable, match="taalmodus"):
        windows_host.powershell_command(Path("enroll_gui.ps1"))
    assert len(calls) == 1


@pytest.mark.parametrize("tool,args", [
    ("update_pack_settings", {"phishing": True, "priority": False, "cleanup": False, "setup_confirmed": True}),
    ("set_priority_rules", {"rules": {"high_keywords": ["invoice"]}, "confirmed": True}),
])
def test_dashboard_caller_boolean_cannot_bypass_native_review(tool, args):
    from imap_dashboard.server import build_server
    from mcp.server.mcpserver.exceptions import ToolError
    writes, reviews = [], []
    operator = SimpleNamespace(update_pack_settings=lambda **kw: writes.append(kw) or kw,
                               set_priority_rules=lambda *a: writes.append(a) or {"saved": True})
    bridge = SimpleNamespace(profile="operator")
    def decline(*args):
        reviews.append(args)
        return False
    server = build_server(bridge=bridge, operator=operator, reviewer=decline)
    result = asyncio.run(server.call_tool(tool, args))
    assert json.loads(result.content[0].text)["status"] == "cancelled"
    assert len(reviews) == 1 and not writes
    server = build_server(bridge=SimpleNamespace(profile="read"), operator=operator, reviewer=lambda *a: True)
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool(tool, args))
    assert not writes
    server = build_server(bridge=bridge, operator=operator, reviewer=lambda *a: True)
    assert not asyncio.run(server.call_tool(tool, args)).is_error
    assert len(writes) == 1


def test_complete_bundle_includes_both_modules_and_one_manifest(tmp_path):
    from nexin_mail.build import assemble
    source = Path(__file__).resolve().parents[2]
    runtime = tmp_path / "runtime"
    for name in ("python.exe", "python312.dll", "python312.zip", "python312._pth", "Lib/site-packages/mcp/__init__.py"):
        file = runtime / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic build fixture - not a Windows binary")
    output = assemble(source, runtime, tmp_path / "bundle")
    assert verify(output)["product"] == "nexin-mail"
    assert (output / "payload/src/imap_plugin/server.py").is_file()
    assert (output / "payload/src/imap_dashboard/server.py").is_file()
    assert (output / "payload/src/nexin_mail/install.py").is_file()
    assert (output / "payload/src/imap_dashboard/ui/mail-app.html").is_file()
    with pytest.raises(ValueError, match="preserved"):
        assemble(source, runtime, output)


def test_update_stages_new_payload_and_rollback_restores_previous_registration(package, tmp_path):
    calls = CodexStub()
    destination = tmp_path / "install"
    first = installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    old_hash = first["package_hash"]
    (package / "new-release.txt").write_text("different package")
    seal(package)
    updated = installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    assert updated["update"] == "updated"
    assert updated["package_hash"] != old_hash
    assert (destination / "packages" / old_hash / "package-manifest.json").is_file()
    owner = json.loads((destination / "registry/nexin-mail-owner.json").read_text())
    assert owner["package_hash"] == updated["package_hash"]
    assert owner["previous_package_hash"] == old_hash
    rolled = installer.rollback(destination)
    assert rolled["status"] == "rolled_back"
    assert rolled["package_hash"] == old_hash
    assert installer.install(package, destination, Path("codex.exe"), [], runner=calls)["update"] == "updated"


def test_update_refuses_foreign_registry_state(package, tmp_path):
    calls = CodexStub()
    destination = tmp_path / "install"
    installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    (destination / "registry" / "foreign-state.json").write_text("synthetic foreign state")
    (package / "new-release.txt").write_text("different package")
    seal(package)
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    assert failed.value.code == "installation_conflict"
    assert (destination / "registry" / "foreign-state.json").read_text() == "synthetic foreign state"


def test_update_registration_failure_restores_previous_active_hash(package, tmp_path):
    calls = CodexStub()
    destination = tmp_path / "install"
    first = installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    old_hash = first["package_hash"]
    (package / "new-release.txt").write_text("different package")
    seal(package)
    calls.fail_add = True
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    assert failed.value.code == "registration_failed"
    owner = json.loads((destination / "registry/nexin-mail-owner.json").read_text())
    assert owner["package_hash"] == old_hash
    assert (destination / "packages" / first["package_hash"]).is_dir()


def test_uninstall_removes_only_owned_registry_and_preserves_payload(package, tmp_path):
    calls = CodexStub()
    destination = tmp_path / "install"
    result = installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    assert installer.uninstall(destination)["status"] == "unregistered"
    assert not (destination / "registry").exists()
    assert (destination / "packages" / result["package_hash"] / "package-manifest.json").is_file()


def test_uninstall_removes_codex_registration_and_keeps_packages(package, tmp_path):
    calls = CodexStub()
    destination = tmp_path / "install"
    result = installer.install(package, destination, Path("codex.exe"), [], runner=calls)
    assert installer.uninstall(destination, Path("codex.exe"), runner=calls)["registration"] == "verified"
    assert calls.rows == []
    assert (destination / "packages" / result["package_hash"]).is_dir()


def test_uninstall_refuses_unexpected_registry_file(package, tmp_path):
    destination = tmp_path / "install"
    installer.install(package, destination, Path("codex.exe"), [], runner=CodexStub())
    (destination / "registry" / "foreign-state.json").write_text("owned by another tool")
    with pytest.raises(installer.InstallError) as failed:
        installer.uninstall(destination)
    assert failed.value.code == "installation_conflict"
    assert (destination / "registry" / "foreign-state.json").is_file()


def test_legacy_migration_requires_confirmation_and_removes_only_exact_owner(package, tmp_path):
    legacy_root = tmp_path / "legacy"
    (legacy_root / "plugins/imap-plugin/.codex-plugin").mkdir(parents=True)
    (legacy_root / "release.json").write_text(json.dumps({"product": "imap-plugin-windows-handoff"}))
    (legacy_root / "plugins/imap-plugin/.codex-plugin/plugin.json").write_text(json.dumps({"name": "imap-plugin"}))
    rows = [{"name": "imap-plugin-handoff", "root": str(legacy_root)}]
    calls = CodexStub(rows)
    with pytest.raises(installer.InstallError) as failed:
        installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls, migrate_legacy=True)
    assert failed.value.code == "migration_confirmation_required"
    result = installer.install(package, tmp_path / "install", Path("codex.exe"), [], runner=calls, migrate_legacy=True, migration_confirmed=True)
    assert result["migration"] == "completed"
    assert [row["name"] for row in calls.rows] == ["nexin-mail"]
    assert legacy_root.exists()


def test_codex_identity_rejects_wsl_config(monkeypatch):
    monkeypatch.setenv("CODEX_CONFIG_DIR", "/mnt/c/Users/example/.codex")
    with pytest.raises(installer.InstallError) as failed:
        installer.codex_identity("C:/Program Files/Codex/codex.exe")
    assert failed.value.code == "codex_config_mismatch"


def test_deterministic_archive_is_repeatable(tmp_path):
    from nexin_mail.build import assemble, create_archive
    import zipfile
    source = Path(__file__).resolve().parents[2]
    runtime = tmp_path / "runtime"
    for name in ("python.exe", "python312.dll", "python312.zip", "python312._pth", "Lib/site-packages/mcp/__init__.py"):
        file = runtime / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic build fixture - not a Windows binary")
    first = assemble(source, runtime, tmp_path / "one")
    second = assemble(source, runtime, tmp_path / "two")
    first_zip = create_archive(first)
    second_zip = create_archive(second)
    assert first_zip.read_bytes() == second_zip.read_bytes()
    with zipfile.ZipFile(first_zip) as archive:
        mode = archive.getinfo("install_macos.sh").external_attr >> 16
        assert mode & 0o111
    from scripts.release_check import inspect_archive
    assert inspect_archive(first_zip)["integrity"] == "manifest_verified"


def test_arm_is_unverified_and_codex_shims_are_not_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "win32")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "ARM64")
    with pytest.raises(installer.InstallError) as failed:
        installer.preflight()
    assert failed.value.code == "architecture_unverified"
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "AMD64")
    shim = tmp_path / "codex.cmd"
    shim.write_text("synthetic shim")
    with pytest.raises(installer.InstallError) as failed:
        installer.preflight(str(shim))
    assert failed.value.code == "codex_unsupported"


@pytest.mark.parametrize("session,complete,status", [
    ({"status": "starting", "next_action": "wait_setup"}, False, "setup_pending"),
    ({"status": "waiting_for_input", "next_action": "wait_setup"}, False, "setup_pending"),
    ({"status": "checking_connection", "next_action": "wait_setup"}, False, "setup_pending"),
    ({"status": "cancelled", "next_action": "stop"}, False, "setup_incomplete"),
    ({"status": "failed", "next_action": "follow_recovery"}, False, "setup_incomplete"),
    ({"status": "unconfirmed", "next_action": "inspect_setup_owner"}, False, "setup_incomplete"),
    ({"status": "ready"}, False, "setup_incomplete"),
    ({"status": "ready", "mail_connection": "verified", "next_action": "render_mail_view"}, True, "ready"),
])
def test_cli_install_includes_setup_and_never_confuses_registration_with_completion(
    monkeypatch, tmp_path, capsys, session, complete, status
):
    calls = []
    monkeypatch.setattr(sys, "argv", ["install", "--package", str(tmp_path), "--install-root", str(tmp_path)])
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(installer, "preflight_macos", lambda _: Path("codex"))
    monkeypatch.setattr(installer, "install", lambda *a, **kw: {"package_hash": "fixture", "registration": "verified"})
    monkeypatch.setattr(installer, "_begin_setup", lambda *a: calls.append(a) or session)
    monkeypatch.setattr(installer, "save_report", lambda *a: True)
    assert installer.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert len(calls) == 1
    assert result["installation_complete"] is complete
    assert result["status"] == status
    assert result["setup_session"] == session
    assert result["mailbox"] == ("verified" if complete else "not_verified")


def test_cli_explicit_skip_setup_is_registration_only(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["install", "--package", str(tmp_path), "--install-root", str(tmp_path), "--skip-setup"])
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(installer, "preflight_macos", lambda _: Path("codex"))
    monkeypatch.setattr(installer, "install", lambda *a, **kw: {
        "status": "registration_only", "installation_complete": False, "registration": "verified"})
    monkeypatch.setattr(installer, "_begin_setup", lambda *a: pytest.fail("explicit skip must not open setup"))
    monkeypatch.setattr(installer, "save_report", lambda *a: True)
    assert installer.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "registration_only"
    assert result["installation_complete"] is False
    assert "setup_session" not in result
