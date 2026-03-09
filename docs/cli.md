# CLI

The CLI groups functionality by domain. The root command is `xpctl`.

## Core

```bash
xpctl ping
xpctl exec ipconfig /all
xpctl sysinfo
xpctl ps
```

## File transfer

```bash
xpctl upload ./sample.exe "C:\\xpctl\\tmp\\sample.exe"
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
