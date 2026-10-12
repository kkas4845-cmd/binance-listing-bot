@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
:loop
python -m listing_bot run
echo Boten stoppet. Starter paa nytt om 10 sekunder (lukk vinduet for aa avslutte)...
timeout /t 10
goto loop
