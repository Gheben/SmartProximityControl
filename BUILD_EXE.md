# Creazione Eseguibile Smart Proximity Control

## Prerequisiti
1. Python 3.8+ installato
2. Tutti i pacchetti necessari installati

## Installazione PyInstaller
```bash
pip install pyinstaller
```

## Creazione dell'Eseguibile

### Opzione 1: Comando Singolo (Semplice)
```bash
pyinstaller --onefile --windowed --name "SmartProximityControl" --icon=logo_gb.ico smart_proximity_control.py
```

### Opzione 2: File Spec (Avanzato)
Crea un file `smartproximitycontrol.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['smart_proximity_control.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'bleak', 'keyboard'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SmartProximityControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Nessuna console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo_gb.ico'
)
```

Poi esegui:
```bash
pyinstaller smartproximitycontrol.spec
```

## Struttura File Finale

Dopo la creazione, l'eseguibile sarà in `dist/SmartProximityControl.exe`

Crea una cartella di installazione (es: `C:\en\scripts\Smart Proximity Control\`) con:
```
C:\en\scripts\Smart Proximity Control\
├── SmartProximityControl.exe    (eseguibile)
├── logo_gb.ico                  (icona dell'applicazione)
├── config.ini                   (configurazione)
├── ble_entity.json              (mappatura BLE)
└── smart_proximity_control.log  (creato automaticamente)
```

## Configurazione Avvio Automatico

### Metodo 1: Cartella Esecuzione Automatica (Utente Corrente)
1. Premi `Win+R`
2. Digita: `shell:startup` e premi Invio
3. Crea un collegamento a `SmartProximityControl.exe` in questa cartella
4. Proprietà → Destinazione: `"C:\en\scripts\Smart Proximity Control\SmartProximityControl.exe" --agent`
5. **IMPORTANTE**: Proprietà → Avanzate → Esegui come amministratore ✓ (necessario per gli hotkey globali)
6. Proprietà → Esegui: Ridotto a icona (opzionale)
5. Proprietà → Esegui: Ridotto a icona (opzionale)

### Metodo 2: Utilità di Pianificazione (Tutti gli Utenti)
1. Apri "Utilità di pianificazione" (Task Scheduler)
2. Azione → Crea attività
3. Generale:
   - Nome: `Smart Proximity Control Agent`
   - Esegui con i privilegi più elevati ✓
4. Trigger:
   - Nuovo → All'accesso
   - Utente specifico o qualsiasi utente
5. Azioni:
   - Nuova → Avvia programma
   - Programma: `C:\en\scripts\Smart Proximity Control\SmartProximityControl.exe`
   - Argomenti: `--agent`
   - Inizia da: `C:\en\scripts\Smart Proximity Control\`
6. Condizioni:
   - Deseleziona tutto (per eseguire sempre)
7. Impostazioni:
   - Consenti esecuzione su richiesta ✓
   - Se l'attività è in esecuzione, non avviare una nuova istanza

### Metodo 3: File Batch (Con Ritardo)
Crea `start_smartproximitycontrol.bat`:
```batch
@echo off
timeout /t 10 /nobreak >nul
start "" "C:\en\scripts\Smart Proximity Control\SmartProximityControl.exe" --agent
```

Metti il collegamento a questo batch nella cartella di avvio automatico.

## Modalità di Esecuzione

### Modalità Agent (Background)
```bash
SmartProximityControl.exe --agent
```
- Parte in background senza finestra
- Risponde solo agli hotkey
- Ideale per avvio automatico

### Modalità Lista Aree
```bash
SmartProximityControl.exe --list-areas
```
- Mostra le aree disponibili in Home Assistant
- Utile per configurare `ble_entity.json`

### Modalità Normale
```bash
SmartProximityControl.exe
```
- Mostra subito la finestra e scansiona

## Hotkey Globali

- **Ctrl+Shift+Space**: Mostra finestra e scansiona BLE
- **Ctrl+Shift+Q**: Chiude l'applicazione
- **ESC**: Nascondi finestra (nella finestra)

## Verifica Funzionamento

1. Copia i file nella cartella di installazione
2. Verifica che `config.ini`, `ble_entity.json` e `logo_gb.ico` siano configurati
3. Esegui manualmente: `SmartProximityControl.exe --agent`
4. Prova gli hotkey: Ctrl+Shift+Space
5. Controlla il file `smart_proximity_control.log` per eventuali errori

## Risoluzione Problemi

### L'exe non parte
- Controlla `smart_proximity_control.log` per errori
- Verifica che `config.ini` e `logo_gb.ico` siano nella stessa cartella dell'exe
- Esegui da terminale per vedere eventuali errori: `SmartProximityControl.exe`

### Hotkey non funzionano
- Richiede privilegi amministrativi
- Click destro su exe → Esegui come amministratore
- Oppure imposta "Esegui come amministratore" nelle proprietà del collegamento

### BLE non trova dispositivi
- Verifica che Windows rilevi il Bluetooth
- Controlla che `ble_entity.json` contenga i MAC corretti
- Verifica permessi Bluetooth dell'applicazione

### File di log non viene creato
- Verifica permessi scrittura nella cartella
- L'applicazione deve avere accesso in scrittura su `C:\en\scripts\Smart Proximity Control\`

## Note Aggiuntive

- L'eseguibile è **standalone**, non richiede Python installato
- Tutti i file di configurazione devono essere nella stessa cartella dell'exe
- Il file `logo_gb.ico` viene usato come icona dell'applicazione
- Il file di log viene creato automaticamente al primo avvio
- La memoria dei dispositivi BLE persiste per 10 secondi dopo la chiusura della finestra
- La finestra si posiziona sempre in primo piano quando attivata
