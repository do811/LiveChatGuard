@echo off
setlocal EnableExtensions
pushd "%~dp0"
if errorlevel 1 (
    echo [ERROR] Cannot open project directory.
    exit /b 1
)

rem Usage: build_release.bat [onefile] [debug]
set "LCG_ONEFILE=0"
set "LCG_CONSOLE=0"
for %%A in (%*) do (
    if /I "%%~A"=="onefile" set "LCG_ONEFILE=1"
    if /I "%%~A"=="debug" set "LCG_CONSOLE=1"
)
set "RELEASE_VERSION=0.5.0"
set "PY=%CD%\.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [ERROR] Missing .venv\Scripts\python.exe
    echo Create the virtual environment first: py -3.12 -m venv .venv
    popd
    exit /b 1
)
if not exist "src\livechat_guard\gui.py" (
    echo [ERROR] Place this script in the LiveChatGuard project root.
    popd
    exit /b 1
)

echo [1/4] Installing project and PyInstaller...
"%PY%" -m pip install -e .
if errorlevel 1 goto :fail
"%PY%" -m pip install "pyinstaller>=6,<7"
if errorlevel 1 goto :fail

echo [2/4] Building Windows executable...
"%PY%" -m PyInstaller --noconfirm --clean "LiveChatGuard.spec"
if errorlevel 1 goto :fail

if "%LCG_ONEFILE%"=="1" goto :onefile
:onedir
echo [3/4] Copying release documents...
copy /Y "README.md" "dist\LiveChatGuard\README.md" >nul
if errorlevel 1 goto :fail
copy /Y "LICENSE" "dist\LiveChatGuard\LICENSE" >nul
if errorlevel 1 goto :fail
set "ZIPNAME=LiveChatGuard_v%RELEASE_VERSION%_Windows_onedir.zip"
if "%LCG_CONSOLE%"=="1" set "ZIPNAME=LiveChatGuard_v%RELEASE_VERSION%_Windows_onedir_DEBUG.zip"
echo [4/4] Creating release ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -LiteralPath 'dist\LiveChatGuard' -DestinationPath ('dist\' + $env:ZIPNAME) -Force"
if errorlevel 1 goto :fail
set "EXEPATH=dist\LiveChatGuard\LiveChatGuard.exe"
goto :ok

:onefile
echo [3/4] Staging release documents...
if exist "dist\release_stage" rmdir /S /Q "dist\release_stage"
mkdir "dist\release_stage\LiveChatGuard"
if errorlevel 1 goto :fail
copy /Y "dist\LiveChatGuard.exe" "dist\release_stage\LiveChatGuard\LiveChatGuard.exe" >nul
if errorlevel 1 goto :fail
copy /Y "README.md" "dist\release_stage\LiveChatGuard\README.md" >nul
if errorlevel 1 goto :fail
copy /Y "LICENSE" "dist\release_stage\LiveChatGuard\LICENSE" >nul
if errorlevel 1 goto :fail
set "ZIPNAME=LiveChatGuard_v%RELEASE_VERSION%_Windows_onefile.zip"
if "%LCG_CONSOLE%"=="1" set "ZIPNAME=LiveChatGuard_v%RELEASE_VERSION%_Windows_onefile_DEBUG.zip"
echo [4/4] Creating release ZIP...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -LiteralPath 'dist\release_stage\LiveChatGuard' -DestinationPath ('dist\' + $env:ZIPNAME) -Force"
if errorlevel 1 goto :fail
set "EXEPATH=dist\LiveChatGuard.exe"

:ok
echo.
echo [OK] Executable: %EXEPATH%
echo [OK] Release ZIP: dist\%ZIPNAME%
echo [INFO] Test on another Windows PC before publishing.
popd
exit /b 0

:fail
echo.
echo [ERROR] Build failed. See output above.
popd
exit /b 1
