# Smart Proximity Control

<div align="center">

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20|%20Linux%20|%20macOS-lightgrey.svg)
![PyQt6](https://img.shields.io/badge/PyQt6-6.0+-brightgreen.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-blue.svg)

**A modern BLE proximity-based control system for Home Assistant**

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-Support%20-yellow.svg?logo=buy-me-a-coffee&logoColor=white)](https://buymeacoffee.com/guidoballau)
[![PayPal](https://img.shields.io/badge/PayPal-Donate-blue.svg?logo=paypal)](https://www.paypal.com/donate/?hosted_button_id=8RF28JBPLYASN)

</div>

---


## � Screenshots

<div align="center">

### Main Window
![Main Window](screenshot/main_window.png?v=2)

### Entities View with Multiple Types
![Entities View](screenshot/entities_view.png?v=2)

</div>

---

## �📖 Overview

Automatic control system for Home Assistant entities based on BLE (Bluetooth Low Energy) proximity detection.

## Features

- 🎯 **Automatic detection** of location via BLE devices
- 🏠 **Home Assistant integration** for entity control
- 🎤 **Voice control** with Google Speech Recognition (Italian language)
- ⌨️ **Configurable global hotkeys** via config.ini
- 🖼️ **Modern interface** with MDI icons, gradient, and custom logo
- 💾 **Device memory** (10 seconds) for fast reopening
- 🚀 **Agent mode** for automatic background startup
- 📦 **Standalone executable** without Python dependencies
- 🎨 **Custom icon** (logo_gb.ico) in window and taskbar
- 🌐 **Multi-instance support** - Auto-connect to available Home Assistant
- 🔌 **Lazy connection** - Works even when HA is offline at startup

## Usage Modes

### Normal Mode
Runs the application showing the window immediately:
```bash
python smart_proximity_control.py
# Or (executable):
SmartProximityControl.exe
```

### Agent Mode (Recommended for auto-start)
Stays in background and activates with configurable hotkeys:
```bash
python smart_proximity_control.py --agent
# Or (executable):
SmartProximityControl.exe --agent
```

**Agent Mode Operation:**
- Press **Ctrl+Shift+Space** (default) to show window and start BLE scanning
- Press **Ctrl+Shift+I** (default) to activate voice control
- Press **Ctrl+Shift+Q** (default) to completely close the application
- Press **ESC** to manually hide the window
- **Device memory**: Entities remain in memory for 10 seconds after closing
- Each scan detects the current area based on the nearest BLE device
- **All hotkeys are configurable** in `config.ini`

### Utility - List Areas
Shows all areas configured in Home Assistant:
```bash
python smart_proximity_control.py --list-areas
# Or (executable):
SmartProximityControl.exe --list-areas
```

## Installation

1. Create a virtual environment:
```bash
python -m venv .venv
.venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure `config.ini`:
```ini
[home_assistant]
url = http://homeassistant.local:8123
api_token = your_long_lived_access_token

# Voice control (agent mode only)
voice_control = true
voice_hotkey = ctrl+shift+i
# Entity domains for voice control (comma separated)
entity_domains = light

# Configurable hotkeys for agent mode
show_hotkey = ctrl+shift+space
quit_hotkey = ctrl+shift+q

[filters]
# Domains for proximity control (comma separated)
entity_domains = light

[gui]
title = Smart Proximity Control
icon_size = 48
show_tooltips = true
```

**Voice Control Configuration:**
- `voice_control = true` - Enable voice control in agent mode
- `voice_hotkey` - Hotkey to activate voice listening
- `entity_domains` (under `[home_assistant]`) - Entity types controllable by voice
- Voice recognition uses Google Speech Recognition (requires internet)
- Automatically detects current room via BLE before executing commands
- Supported commands: "Accendi [luce]", "Spegni [luce]", "Apri [tapparella]", "Chiudi [tapparella]"

4. Configure `ble_entity.json`:
```json
{
    "ble_mapping": {
        "AA:BB:CC:DD:EE:FF": "living_room",
        "11:22:33:44:55:66": "bedroom"
    }
}
```

**IMPORTANT:** The `area_id` must match exactly those in Home Assistant. Use `python smart_proximity_control.py --list-areas` to see them.

## Building .exe File

To create a Windows standalone executable:

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "config.ini;." --add-data "ble_entity.json;." smart_proximity_control.py
```

The executable will be in `dist/SmartProximityControl.exe`. 

**To start it in Agent mode at Windows startup:**

1. Create a shortcut to `SmartProximityControl.exe`
2. Properties → Target: `C:\path\to\SmartProximityControl.exe --agent`
3. Properties → Run: Minimized
4. Copy the shortcut to: `C:\Users\YOURNAME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`

## Requirements

- Python 3.8+
- Windows 10/11 (for global hotkeys and voice control)
- Bluetooth LE supported
- Home Assistant with REST API enabled
- Microphone (for voice control feature)
- Internet connection (for Google Speech Recognition)

## Domain Configuration

In the `config.ini` file, `[filters]` section, you can specify which entity types to show:

- `entity_domains = light` - Lights only
- `entity_domains = light,switch` - Lights and switches
- `entity_domains = light,switch,fan` - Lights, switches, and fans

## Notes

- **Strongest RSSI:** The system automatically detects the BLE beacon with the best signal
- **Single scan:** Each activation performs a new scan to detect the current location
- **Privileges:** Run as administrator to register global hotkeys on Windows
- **Frameless window:** Modern design without borders, with visible opaque background
- **Single file:** `get_area_id.py` has been integrated into `smart_proximity_control.py` (use `--list-areas`)

## Credits

This project is based on the original [hapy](https://github.com/gianlucaromito/hapy) by [Gianluca Romito](https://github.com/gianlucaromito).

**Major enhancements and features added:**
- � Voice control with BLE room detection and Google Speech Recognition
- 🎨 Modern UI with custom logo and MDI icons
- 🏷️ Entity grouping by type with labels
- ⚙️ Configurable hotkeys via config.ini
- 🔧 Improved configuration management with multi-instance support
- 🪟 Advanced window drag handling
- 📝 Optimized logging with rotation
- 🚀 Enhanced agent mode with lazy connection and better memory management
- 🌐 Automatic failover between multiple Home Assistant instances

Special thanks to the original author for the foundational work!

## License

MIT
