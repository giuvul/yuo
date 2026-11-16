@echo off
rem Yuo for Windows: double-click. Installs uv (pinned, hash-checked), then Python and Yuo, then opens Yuo
rem in your browser. Keep this window open while you use Yuo; closing it stops Yuo.
setlocal EnableExtensions EnableDelayedExpansion
title Yuo
set "UV_VERSION=0.13.1"
set "YUO_HOME=%LOCALAPPDATA%\Yuo"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
  set "UV_ASSET=uv-aarch64-pc-windows-msvc.zip"
  set "UV_SHA=ec7846a5939b4654afee24f2d82bf6fde71bd7a6952d7748f1135ab301dd0a49"
) else (
  set "UV_ASSET=uv-x86_64-pc-windows-msvc.zip"
  set "UV_SHA=3b2661a463a5baea7f5076ea2b25ab71d77f36a6c0d809e5350651792f80a672"
)
set "UV_DIR=%YUO_HOME%\uv\%UV_VERSION%"
set "UV=%UV_DIR%\uv.exe"
set "ZIP=%TEMP%\yuo-%UV_ASSET%"

rem Smart App Control blocks programs without a signature, including the Python that Yuo installs (04 4.1).
for /f "tokens=3" %%s in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy" /v VerifiedAndReputablePolicyState 2^>nul ^| find "0x"') do set "SAC=%%s"
if "%SAC%"=="0x1" (
  echo.
  echo   Smart App Control is on. It may block Yuo's Python with no way to allow it.
  echo   The guide explains what you can do: guide\index.html, section "Smart App Control".
  echo.
  start "" "%~dp0guide\index.html"
)

if not exist "%UV%" (
  echo   Getting uv %UV_VERSION% ^(the tool that installs Python and Yuo^)...
  if not exist "%UV_DIR%" mkdir "%UV_DIR%"
  curl.exe -fsSL --proto =https -o "%ZIP%" "https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_ASSET%"
  if errorlevel 1 (
    set "WHY=Could not download uv. Check the internet connection and start Yuo again."
    goto :failed
  )
  set "GOT="
  for /f "skip=1 delims=" %%h in ('certutil -hashfile "%ZIP%" SHA256') do if not defined GOT set "GOT=%%h"
  set "GOT=!GOT: =!"
  if /i not "!GOT!"=="%UV_SHA%" (
    del "%ZIP%" >nul 2>&1
    set "WHY=The uv download did not match its checksum; nothing was installed."
    goto :failed
  )
  tar.exe -xf "%ZIP%" -C "%UV_DIR%"
  del "%ZIP%" >nul 2>&1
  if not exist "%UV%" (
    set "WHY=uv could not be unpacked."
    goto :failed
  )
)

set "YUO_UV=%UV%"
set "UV_PYTHON_INSTALL_DIR=%YUO_HOME%\python"
set "UV_CACHE_DIR=%YUO_HOME%\cache"
set "UV_NO_CONFIG=1"
if not exist "%YUO_HOME%\python\cpython-3.14*" echo   Getting Python 3.14 ^(first start only, about 30 MB^)...
"%UV%" run --no-project --quiet --python 3.14 --python-preference only-managed "%~dp0app\launcher.py"
if errorlevel 1 (
  set "WHY=Yuo stopped with an error."
  goto :failed
)
pause
exit /b 0

:failed
echo.
echo   !WHY!
echo   Details: %YUO_HOME%\logs\launcher.log
echo.
pause
exit /b 1
