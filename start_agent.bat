@echo off
REM Smart Proximity Control Agent Launcher
REM Questo script avvia l'applicazione in modalità agent con privilegi amministrativi

REM Attendi 10 secondi dopo l'avvio di Windows per evitare conflitti
timeout /t 10 /nobreak >nul

REM Avvia l'applicazione in modalità agent
REM Modifica il percorso se hai installato l'app in un'altra cartella
start "" "C:\en\scripts\Smart Proximity Control\SmartProximityControl.exe" --agent

REM Lo script termina immediatamente, l'applicazione continua in background
