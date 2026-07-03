@echo off
setlocal

cd /d "F:\Git Repos\Carvera_Controller"
py -3.12 -m poetry run python -m carveracontroller

if errorlevel 1 (
  echo.
  echo Controller exited with an error.
)

pause
