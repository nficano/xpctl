import os

from click.testing import CliRunner

from xpctl.cli import main
from xpctl.config import config_path, load_profile, save_profile


def test_save_profile_round_trip_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    path = save_profile(
        "lab",
        {
            "hostname": "10.0.0.5",
            "port": 22,
            "transport": "ssh",
            "username": "root",
            "password": "hunter2",
        },
    )

    assert path == config_path()
    assert load_profile("lab") == {
        "hostname": "10.0.0.5",
        "port": "22",
        "transport": "ssh",
        "username": "root",
        "password": "hunter2",
    }
    assert path.read_text(encoding="utf-8") == (
        "[lab]\n"
        "hostname = 10.0.0.5\n"
        "port = 22\n"
        "transport = ssh\n"
        "username = root\n"
        "password = hunter2\n"
        "\n"
    )
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_configure_retries_until_connection_succeeds(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    attempts: list[dict[str, str]] = []

    def fake_attempt(values):
        attempts.append(dict(values))
        if len(attempts) == 1:
            raise ConnectionError("bad credentials")

    monkeypatch.setattr("xpctl.cli._attempt_profile_connection", fake_attempt)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["configure", "--profile", "lab"],
        input=(
            "172.16.20.173\n"
            "22\n"
            "DONALD TRUMP\n"
            "wrongpass\n"
            "auto\n"
            "\n"
            "\n"
            "\n"
            "mywinxp!\n"
            "\n"
        ),
    )

    assert result.exit_code == 0
    assert "Connection failed: bad credentials" in result.output
    assert "Saved profile 'lab'" in result.output
    assert attempts[0]["password"] == "wrongpass"
    assert attempts[1]["password"] == "mywinxp!"
    assert load_profile("lab") == {
        "hostname": "172.16.20.173",
        "port": "22",
        "transport": "auto",
        "username": "DONALD TRUMP",
        "password": "mywinxp!",
    }


def test_configure_prefills_existing_password_and_ping_uses_named_profile(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    save_profile(
        "lab",
        {
            "hostname": "172.16.20.173",
            "port": 22,
            "transport": "ssh",
            "username": "DONALD TRUMP",
            "password": "mywinxp!",
        },
    )

    seen: dict[str, str | int] = {}

    class DummyClient:
        def __init__(self, host, port, transport, user, password):
            seen.update(
                host=host,
                port=port,
                transport=transport,
                user=user,
                password=password,
            )

        def connect(self):
            return None

        def ping(self):
            return True

        def disconnect(self):
            return None

    monkeypatch.setattr("xpctl.cli.XPClient", DummyClient)
    monkeypatch.setattr("xpctl.cli._attempt_profile_connection", lambda values: None)

    runner = CliRunner()
    configure_result = runner.invoke(
        main,
        ["configure", "--profile", "lab"],
        input="\n\n\n\n\n",
    )
    ping_result = runner.invoke(main, ["--profile", "lab", "ping"])

    assert configure_result.exit_code == 0
    assert "Password [****]" in configure_result.output
    assert ping_result.exit_code == 0
    assert seen == {
        "host": "172.16.20.173",
        "port": 22,
        "transport": "ssh",
        "user": "DONALD TRUMP",
        "password": "mywinxp!",
    }
