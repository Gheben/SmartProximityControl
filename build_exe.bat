@echo off
REM Script per creare l'eseguibile Smart Proximity Control

echo ========================================
echo  Creazione Eseguibile Smart Proximity Control
echo ========================================
echo.

REM Verifica e attiva virtual environment
if exist ".venv\Scripts\activate.bat" (
    echo Attivazione virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo ATTENZIONE: Virtual environment non trovato in .venv
    echo Verifica di essere nella cartella corretta del progetto
    pause
    exit /b 1
)

REM Verifica installazione PyInstaller
.venv\Scripts\python.exe -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo PyInstaller non trovato nel virtual environment. Installazione in corso...
    .venv\Scripts\pip.exe install pyinstaller
    if %errorlevel% neq 0 (
        echo ERRORE: Installazione PyInstaller fallita
        pause
        exit /b 1
    )
)

echo PyInstaller trovato. Creazione eseguibile in corso...
echo.

REM Crea l'eseguibile usando il Python del venv
.venv\Scripts\pyinstaller.exe --onefile --windowed --name "SmartProximityControl" --icon=Smart_Proximity_Control.ico --add-data "config.ini;." --add-data "ble_entity.json;." --add-data "Smart_Proximity_Control.ico;." smart_proximity_control.py

if %errorlevel% neq 0 (
    echo.
    echo ERRORE: Creazione eseguibile fallita
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Eseguibile creato con successo!
echo ========================================
echo.
echo L'eseguibile si trova in: dist\SmartProximityControl.exe
echo.
echo PROSSIMI PASSI:
echo 1. Crea una cartella di installazione (es: C:\en\scripts\Smart Proximity Control\)
echo 2. Copia questi file nella cartella:
echo    - dist\SmartProximityControl.exe
echo    - Smart_Proximity_Control.ico
echo    - config.ini
echo    - ble_entity.json
echo 3. Per l'avvio automatico, leggi BUILD_EXE.md
echo.
pause
