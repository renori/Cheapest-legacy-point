@echo off
rem Double-click to open the Cheapest Skill-up GUI in your browser.
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m cheapest_skillup.gui) || (python -m cheapest_skillup.gui)
if errorlevel 1 pause
