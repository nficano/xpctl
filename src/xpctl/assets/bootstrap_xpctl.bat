@echo off
setlocal enableextensions enabledelayedexpansion

set "ROOT=%~dp0"
set "CYGWIN_SETUP=%ROOT%setup-x86-2.874.exe"
set "CYGWIN_ROOT=C:\cygwin"
set "CYGWIN_PACKAGES=%TEMP%\xpctl-cygwin-packages"
set "CYGWIN_MIRROR=http://ctm.crouchingtigerhiddenfruitbat.org/pub/cygwin/circa/2016/08/30/104223/"
set "PYTHON_ARCHIVE=%ROOT%python-3.4.10.zip"
set "PYTHON_STAGE=C:\xpctl\bootstrap\python"
set "PYTHON_EXE=C:\Python34\python.exe"
set "AGENT_SOURCE=%ROOT%agent.py"
set "AGENT_TARGET=C:\xpctl\agent.py"
set "SSHD_PASSWORD=xpctl-sshd"
set "PACKAGES=bash,openssh,unzip,curl"

echo [xpctl] Bootstrap starting...

if not exist "%CYGWIN_SETUP%" (
  echo [xpctl] Missing Cygwin setup: %CYGWIN_SETUP%
  exit /b 1
)

if not exist "%PYTHON_ARCHIVE%" (
  echo [xpctl] Missing Python archive: %PYTHON_ARCHIVE%
  exit /b 1
)

if not exist "%AGENT_SOURCE%" (
  echo [xpctl] Missing agent source: %AGENT_SOURCE%
  exit /b 1
)

if not exist "C:\xpctl" mkdir "C:\xpctl"
if not exist "C:\xpctl\bootstrap" mkdir "C:\xpctl\bootstrap"
if not exist "%CYGWIN_PACKAGES%" mkdir "%CYGWIN_PACKAGES%"

echo [xpctl] Installing Cygwin packages from %CYGWIN_MIRROR%
"%CYGWIN_SETUP%" -q -B -n -N -d -R "%CYGWIN_ROOT%" -l "%CYGWIN_PACKAGES%" -s "%CYGWIN_MIRROR%" -P %PACKAGES%
if errorlevel 1 (
  echo [xpctl] Cygwin install failed.
  exit /b 1
)

if not exist "%CYGWIN_ROOT%\bin\unzip.exe" (
  echo [xpctl] unzip.exe not found after Cygwin install.
  exit /b 1
)

if exist "%PYTHON_STAGE%" rmdir /s /q "%PYTHON_STAGE%"
mkdir "%PYTHON_STAGE%"

echo [xpctl] Unpacking bundled Python installer...
"%CYGWIN_ROOT%\bin\unzip.exe" -qo "%PYTHON_ARCHIVE%" -d "%PYTHON_STAGE%"
if errorlevel 1 (
  echo [xpctl] Failed to unpack Python archive.
  exit /b 1
)

if exist "%PYTHON_STAGE%\vcredist_x86.exe" (
  echo [xpctl] Installing Visual C++ runtime...
  "%PYTHON_STAGE%\vcredist_x86.exe" /q
)

if not exist "%PYTHON_STAGE%\python-3.4.10.msi" (
  echo [xpctl] python-3.4.10.msi missing from archive.
  exit /b 1
)

echo [xpctl] Installing Python 3.4.10 to C:\Python34
msiexec /i "%PYTHON_STAGE%\python-3.4.10.msi" TARGETDIR="C:\Python34" ALLUSERS=1 /qn /norestart
if errorlevel 1 (
  echo [xpctl] Python MSI install failed.
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo [xpctl] Python was not installed to %PYTHON_EXE%
  exit /b 1
)

echo [xpctl] Configuring sshd service
set "SSHD_READY=0"
"%CYGWIN_ROOT%\bin\bash.exe" --login -c "/usr/bin/ssh-host-config --yes --port 22 --privileged --user cyg_server --pwd %SSHD_PASSWORD%"
if errorlevel 1 (
  echo [xpctl] Warning: ssh-host-config failed. Continuing with the TCP agent bootstrap.
) else (
  "%CYGWIN_ROOT%\bin\bash.exe" --login -c "/usr/bin/cygrunsrv -S sshd || /usr/bin/cygrunsrv -S cygsshd"
  if not errorlevel 1 set "SSHD_READY=1"
)

echo [xpctl] Installing packaged agent...
copy /Y "%AGENT_SOURCE%" "%AGENT_TARGET%" >nul
if errorlevel 1 (
  echo [xpctl] Failed to copy agent.py
  exit /b 1
)

echo [xpctl] Starting agent on port 9578
start "" /b "%PYTHON_EXE%" "%AGENT_TARGET%" --port 9578

set /a WAIT_COUNT=0
:wait_for_agent
netstat -an | find ":9578" | find "LISTENING" >nul
if not errorlevel 1 goto agent_ready
if %WAIT_COUNT% GEQ 30 (
  echo [xpctl] Agent did not start within 30 seconds.
  exit /b 1
)
set /a WAIT_COUNT+=1
ping -n 2 127.0.0.1 >nul
goto wait_for_agent

:agent_ready
if "%SSHD_READY%"=="1" netsh firewall add portopening TCP 22 "Cygwin SSHD" >nul 2>&1
netsh firewall add portopening TCP 9578 "xpctl Agent" >nul 2>&1
echo [xpctl] Agent is listening on port 9578.
echo [xpctl] Cygwin and OpenSSH packages were installed under %CYGWIN_ROOT%.
echo [xpctl] sshd was configured with service user cyg_server and password %SSHD_PASSWORD%.
exit /b 0
