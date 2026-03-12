from pathlib import Path


def test_write_bootstrap_batch(tmp_path):
    from xpctl.resources import write_bootstrap_batch

    target = tmp_path / "bootstrap_xpctl.bat"
    write_bootstrap_batch(target)

    text = target.read_text(encoding="utf-8")
    assert "setup-x86-2.874.exe" in text
    assert "python-3.4.10.zip" in text
    assert "agent.py" in text
    assert "http://ctm.crouchingtigerhiddenfruitbat.org/pub/cygwin/circa/2016/08/30/104223/" in text
    assert "ssh-host-config --yes" in text
    assert 'netsh firewall add portopening TCP 9578 "xpctl Agent"' in text


def test_setup_bootstrap_generates_bundle(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from xpctl.cli import main

    runner = CliRunner()

    def fake_copy_installer(name, destination):
        payload = b"python" if name == "python-3.4.10.zip" else b"cygwin"
        Path(destination).write_bytes(payload)
        return Path(destination)

    def fake_write_agent(destination):
        Path(destination).write_text("agent", encoding="utf-8")
        return Path(destination)

    def fake_write_bootstrap(destination):
        Path(destination).write_text("bootstrap", encoding="utf-8")
        return Path(destination)

    monkeypatch.setattr("xpctl.cli.copy_installer_asset", fake_copy_installer)
    monkeypatch.setattr("xpctl.cli.write_agent_source", fake_write_agent)
    monkeypatch.setattr("xpctl.cli.write_bootstrap_batch", fake_write_bootstrap)

    output_dir = tmp_path / "bundle"
    result = runner.invoke(main, ["setup", "bootstrap", "--output-dir", str(output_dir)])

    assert result.exit_code == 0
    assert (output_dir / "python-3.4.10.zip").read_bytes() == b"python"
    assert (output_dir / "setup-x86-2.874.exe").read_bytes() == b"cygwin"
    assert (output_dir / "agent.py").read_text(encoding="utf-8") == "agent"
    assert (output_dir / "bootstrap_xpctl.bat").read_text(encoding="utf-8") == "bootstrap"
