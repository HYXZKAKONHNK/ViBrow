@echo off
cd /d "%~dp0"
color 2
echo starting Viengine...
start "" pythonw "%~dp0viengine.py"
exit