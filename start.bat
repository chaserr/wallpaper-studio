@echo off
chcp 65001 >nul
title 壁纸工坊
cd /d "%~dp0"
rem 优先用装了 pywebview 的 Python，这样才能弹出原生窗口（而不是浏览器标签页）
set "PYW=C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe"
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0app.py"
  exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%~dp0app.py"
  exit /b 0
)
where py >nul 2>nul
if %errorlevel%==0 (
  start "" pyw "%~dp0app.py"
  exit /b 0
)
start "" python "%~dp0app.py"
