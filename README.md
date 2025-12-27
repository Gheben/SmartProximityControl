# Smart Proximity Control

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-lightgrey.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-brightgreen.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-blue.svg)

**A modern BLE proximity-based control system for Home Assistant**

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Support%20-yellow.svg?logo=buy-me-a-coffee&logoColor=white)](https://buymeacoffee.com/guidoballau)

</div>

---

## 📖 Overview

Sistema di controllo automatico delle entità di Home Assistant basato su rilevamento BLE (Bluetooth Low Energy).

## Caratteristiche

- 🎯 **Rilevamento automatico** della posizione tramite dispositivi BLE
- 🏠 **Integrazione Home Assistant** per controllo entità
- ⌨️ **Hotkey globali** - Ctrl+Shift+Space (mostra), Ctrl+Shift+Q (quit)
- 🖼️ **Interfaccia moderna** con icone MDI, gradiente e logo personalizzato
- 💾 **Memoria dispositivi** (10 secondi) per riapertura veloce
- 🚀 **Modalità Agent** per avvio automatico in background
- 📦 **Eseguibile standalone** senza dipendenze Python
- 🎨 **Icona personalizzata** (logo_gb.ico) nella finestra e barra applicazioni

## Modalità di utilizzo

### Modalità Normale
Esegue l'applicazione mostrando subito la finestra:
```bash
python smart_proximity_control.py
# Oppure (eseguibile):
SmartProximityControl.exe
```

### Modalità Agent (Consigliata per avvio automatico)
Resta in background e si attiva con **Ctrl+Shift+Space**:
```bash
python smart_proximity_control.py --agent
# Oppure (eseguibile):
SmartProximityControl.exe --agent
```

**Funzionamento Agent:**
- Premi **Ctrl+Shift+Space** per mostrare la finestra e avviare la scansione BLE
- Premi **Ctrl+Shift+Q** per chiudere completamente l'applicazione
- Premi **ESC** per nascondere la finestra manualmente
- **Memoria dispositivi**: Le entità rimangono in memoria per 10 secondi dopo la chiusura
- Ogni scansione rileva l'area corrente in base al dispositivo BLE più vicino

### Utility - Lista Aree
Mostra tutte le aree configurate in Home Assistant:
```bash
python smart_proximity_control.py --list-areas
# Oppure (eseguibile):
SmartProximityControl.exe --list-areas
```

## Installazione

1. Crea un virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Installa le dipendenze:
```bash
pip install -r requirements.txt
```

3. Configura `config.ini`:
```ini
[home_assistant]
url = http://homeassistant.local:8123
api_token = your_long_lived_access_token

[gui]
title = Hapy
icon_size = 48
show_tooltips = true

[filters]
# Domini da mostrare (separati da virgola)
entity_domains = light
```

4. Configura `ble_entity.json`:
```json
{
    "ble_mapping": {
        "AA:BB:CC:DD:EE:FF": "soggiorno",
        "11:22:33:44:55:66": "camera"
    }
}
```

**IMPORTANTE:** Gli `area_id` devono corrispondere esattamente a quelli di Home Assistant. Usa `python hapy.py --list-areas` per vederli.

## Creazione file .exe

Per creare un eseguibile Windows standalone:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "config.ini;." --add-data "ble_entity.json;." hapy.py
```

L'eseguibile sarà in `dist/hapy.exe`. 

**Per avviarlo in modalità Agent all'avvio di Windows:**

1. Crea un collegamento a `hapy.exe`
2. Proprietà → Target: `C:\path\to\hapy.exe --agent`
3. Proprietà → Esegui: Ridotto a icona
4. Copia il collegamento in: `C:\Users\TUONOME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`

## Requisiti

- Python 3.8+
- Windows 10/11 (per hotkey globali)
- Bluetooth LE supportato
- Home Assistant con API REST abilitata

## Configurazione Domini

Nel file `config.ini`, sezione `[filters]`, puoi specificare quali tipi di entità mostrare:

- `entity_domains = light` - Solo luci
- `entity_domains = light,switch` - Luci e interruttori
- `entity_domains = light,switch,fan` - Luci, interruttori e ventilatori

## Note

- **RSSI più forte:** Il sistema rileva automaticamente il beacon BLE con segnale migliore
- **Scansione singola:** Ogni attivazione effettua una nuova scansione per rilevare la posizione attuale
- **Privilegi:** Eseguire come amministratore per registrare hotkey globali su Windows
- **Finestra frameless:** Design moderno senza bordi, con sfondo opaco visibile
- **File unico:** `get_area_id.py` è stato integrato in `hapy.py` (usa `--list-areas`)

## Licenza

MIT
