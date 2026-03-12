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
username = DONALD TRUMP
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

## Reverse engineering helpers

```bash
xpctl debug list
xpctl mem dump 1234 ./target.dmp
xpctl dll list 1234
xpctl reg export HKLM\\Software\\Microsoft ./software.reg
```

Run `xpctl <group> --help` or `xpctl <group> <command> --help` for the full
surface area.
