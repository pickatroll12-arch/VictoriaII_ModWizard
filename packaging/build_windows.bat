@echo off
rem Construye Victoria II Mod Studio para Windows (PyInstaller, one-folder) y lo comprime en .zip.
rem
rem Uso: packaging\build_windows.bat [--system]
rem   --system  usa el Python actual (con PyInstaller y las dependencias) en vez de
rem             crear el entorno virtual build\venv-windows (requiere red).
rem Variable PYTHON: interprete base (por defecto "py -3", o "python" si no existe el lanzador py).
rem Archivo solo ASCII: cmd.exe lo lee con la pagina de codigos OEM.
setlocal EnableExtensions

pushd "%~dp0.." || exit /b 1
set "ROOT=%CD%"

set "USE_SYSTEM=0"
if /i "%~1"=="--system" set "USE_SYSTEM=1"
if /i "%~1"=="-h" goto :usage
if /i "%~1"=="--help" goto :usage

if defined PYTHON goto :have_python
set "PYTHON=python"
where py >nul 2>nul
if not errorlevel 1 set "PYTHON=py -3"
:have_python

if "%USE_SYSTEM%"=="1" goto :use_system

set "VENV=%ROOT%\build\venv-windows"
if not exist "%VENV%\Scripts\python.exe" (
    %PYTHON% -m venv "%VENV%"
    if errorlevel 1 goto :error
)
rem Las comillas forman parte del valor para que la ruta admita espacios.
set PY="%VENV%\Scripts\python.exe"
%PY% -m pip install --upgrade pip
if errorlevel 1 goto :error
%PY% -m pip install -r "%ROOT%\requirements.txt" "pyinstaller>=6.0"
if errorlevel 1 goto :error
goto :build

:use_system
set "PY=%PYTHON%"

:build
%PY% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller no esta disponible. Instalalo o ejecuta sin --system. 1>&2
    goto :error
)

set "PYTHONPATH=%ROOT%\src"
%PY% -m PyInstaller --noconfirm --clean --distpath "%ROOT%\dist" --workpath "%ROOT%\build\pyinstaller" "%ROOT%\packaging\vic2studio.spec"
if errorlevel 1 goto :error

rem El nombre del .zip lleva la version de vic2studio.__version__.
%PY% -c "import platform, shutil, vic2studio as v; print('Archivo:', shutil.make_archive('dist/vic2studio-' + v.__version__ + '-windows-' + platform.machine().lower(), 'zip', 'dist', v.APP_NAME))"
if errorlevel 1 goto :error

echo Aplicacion: %ROOT%\dist\Victoria II Mod Studio
popd
exit /b 0

:usage
echo Uso: packaging\build_windows.bat [--system]
popd
exit /b 0

:error
echo Error durante la construccion. 1>&2
popd
exit /b 1
