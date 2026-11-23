@echo off
setlocal
title Clip Cut AI
cd /d "%~dp0"
echo.
echo  ===== Clip Cut AI =====
echo  Developed by Aditya and Anshik
echo.

rem --- Python: "py" launcher first, then "python" (skipping the Microsoft Store shortcut that isn't real Python)
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if defined PY goto have_python
echo  Python nahi mila. Install kar rahe hain...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo  Python install ho gaya. Ye window band karke START-WINDOWS.bat dobara chalao.
echo  Agar install nahi hua: python.org se Python 3.12 install karo aur "Add Python to PATH" tick karna.
goto stop

:have_python
echo  Python mil gaya: %PY%

where ffmpeg >nul 2>nul
if not errorlevel 1 goto have_ffmpeg
echo  ffmpeg nahi mila. Install kar rahe hain...
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
echo.
echo  ffmpeg install ho gaya. Ye window band karke START-WINDOWS.bat dobara chalao.
goto stop

:have_ffmpeg
echo  ffmpeg mil gaya.
if not exist ".installed" goto install
rem --- new libraries added by an update: install just once more
%PY% -c "import ngrok, pywebpush" >nul 2>nul
if not errorlevel 1 goto run
echo.
echo  Update ke naye libraries install ho rahe hain...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
goto run

:install
echo.
echo  Pehli baar: libraries install ho rahi hain, 5-10 minute lag sakte hain...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto pipfail
echo done> .installed

:run
echo.
echo  App chal raha hai. Browser apne aap khulega.
echo  Online ngrok on hai to online address khulega, warna http://127.0.0.1:8765
echo  Pehli baar speech model, lagbhag 480 MB, download hoga. Thoda ruko.
echo  App band karna ho to ye window band kar do.
echo.
if not defined CLIPCUT_OPEN_BROWSER set "CLIPCUT_OPEN_BROWSER=1"
%PY% -m studio.server
set "RC=%errorlevel%"
set "CLIPCUT_OPEN_BROWSER=0"
if "%RC%"=="42" set "CLIPCUT_RESTARTED=1"
if "%RC%"=="42" goto run
if "%RC%"=="2" goto stop
echo.
echo  App ruk gaya. Upar jo error likha hai uski photo bhej do.
goto stop

:pipfail
echo.
echo  Libraries install nahi ho payi. Internet check karke dobara chalao.
echo  Upar jo error likha hai uski photo bhej do.

:stop
echo.
pause
