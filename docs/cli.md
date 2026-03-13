# CLI

The CLI groups functionality by domain. The root command is `xpctl`.

## Configuration and profiles

```bash
xpctl configure
xpctl configure --profile lab
xpctl --profile lab ping
xpctl --profile lab --transport ssh exec ver
```

Profiles are stored in `~/.xpcli/config` using a simple INI format:

```ini
[default]
hostname = 172.16.20.173
port = 22
transport = auto
username = user
password = mywinxp!

[lab]
hostname = 10.0.0.5
port = 22
transport = ssh
username = root
password = hunter2
```

`xpctl configure` validates the connection before saving. When a profile exists,
the wizard shows the current values as defaults and masks the password prompt.

## Core

```bash
xpctl ping
xpctl --profile lab ping
xpctl exec ipconfig /all
xpctl sysinfo
xpctl ps
```

## File transfer

```bash
xpctl upload ./sample.exe "C:\\xpctl\\tmp\\sample.exe"
xpctl --profile lab upload ./sample.exe "C:\\xpctl\\tmp\\sample.exe"
xpctl download "C:\\xpctl\\tmp\\sample.exe" ./sample.exe
xpctl ls "C:\\xpctl\\tmp"
```

## Agent lifecycle

```bash
xpctl agent deploy
xpctl agent start
xpctl agent status
xpctl agent reboot --wait
```

## Bootstrap a fresh XP VM

```bash
xpctl setup bootstrap
xpctl setup bootstrap --output-dir ./artifacts/xp-bootstrap
```

`xpctl setup bootstrap` creates a portable bootstrap directory containing the
packaged XP agent, the pinned Python 3.4.10 archive, the pinned
`setup-x86-2.874.exe` Cygwin installer, and `bootstrap_xpctl.bat`.

Run the batch file on the XP host as an administrator. It installs Python,
installs Cygwin and OpenSSH from
`http://ctm.crouchingtigerhiddenfruitbat.org/pub/cygwin/circa/2016/08/30/104223/`,
attempts to configure `sshd`, starts the packaged agent on TCP port `9578`,
and waits until that listener is up before returning.

## Reverse engineering helpers

```bash
xpctl debug list
xpctl mem dump 1234 ./target.dmp
xpctl dll list 1234
xpctl reg export HKLM\\Software\\Microsoft ./software.reg
```

Run `xpctl <group> --help` or `xpctl <group> <command> --help` for the full
surface area.
