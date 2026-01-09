import requests
import threading
import time
import io
import configparser
import os
import logging
import logging.handlers
import atexit
from datetime import datetime
import sys
import locale
import tempfile
import json
import asyncio
from bleak import BleakScanner
import keyboard

# Import per Voice Control (integrato)
import speech_recognition as sr
import sounddevice as sd
import numpy as np
import winsound

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
    QFrame, QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu,
    QScrollArea, QLineEdit, QCheckBox, QSpinBox, QPushButton, QStyle
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QTransform, QCursor, QIcon
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import (
    Qt, QThread, QObject, QTimer, QEvent, pyqtSignal as Signal
)

# Voice Control è integrato direttamente
VOICE_CONTROL_AVAILABLE = True

# Funzione per ottenere il percorso base (directory dell'eseguibile o dello script)
def get_base_path():
    """Restituisce il percorso della directory contenente l'eseguibile o lo script."""
    if getattr(sys, 'frozen', False):
        # Se è un eseguibile creato con PyInstaller
        return os.path.dirname(sys.executable)
    else:
        # Se è uno script Python
        return os.path.dirname(os.path.abspath(__file__))

# Funzione per stampare in modo sicuro (gestisce stdout None in modalità windowed)
def safe_print(*args, **kwargs):
    """Stampa solo se stdout è disponibile (non None in modalità windowed)."""
    if sys.stdout is not None:
        print(*args, **kwargs)

# Base URL for Home Assistant icons (Material Design Icons)
ICONS_BASE_URL = "https://raw.githubusercontent.com/Templarian/MaterialDesign-SVG/master/svg"
ICONS_MAP = {
    'light': {
        'on': 'lightbulb',
        'off': 'lightbulb-off'
    },
    'switch': {
        'on': 'power-socket-us',
        'off': 'power-socket-us-off'
    },
    'fan': {
        'on': 'fan',
        'off': 'fan-off'
    },
    'cover': {
        0: 'window-shutter',
        'open': 'window-shutter-open'
    },
    'system': {
        'loading': 'loading',
        'alert': 'alert-circle'
    }
}

BLE_ENTITY_FILE = 'ble_entity.json'

def play_beep(frequency, duration):
    """Riproduce un beep solo se i suoni sono abilitati."""
    # Controlla se la variabile globale esiste e se è true
    if 'SOUNDS_ENABLED' in globals() and globals()['SOUNDS_ENABLED']:
        winsound.Beep(frequency, duration)

def setup_logging():
    """Sets up a rotating file logger with console output."""
    base_path = get_base_path()
    log_file = os.path.join(base_path, 'smart_proximity_control.log')
    max_log_size = 5 * 1024 * 1024
    
    # Create a logger (only ERROR and above)
    logger = logging.getLogger('spc_logger')
    logger.setLevel(logging.ERROR)
    
    # Create a rotating file handler (5MB max, 3 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=max_log_size, backupCount=3
    )
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler (solo per warning ed errori)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# =============================================================================
# VOICE CONTROL INTEGRATO
# =============================================================================

def load_voice_ble_mapping():
    """Carica la mappatura BLE -> stanza da ble_entity.json (per voice control)."""
    base_path = get_base_path()
    ble_file = os.path.join(base_path, BLE_ENTITY_FILE)
    
    if not os.path.exists(ble_file):
        safe_print(f"⚠️ File {BLE_ENTITY_FILE} non trovato")
        return None
    
    try:
        with open(ble_file, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        
        # Supporta sia formato vecchio (entities) che nuovo (ble_mapping)
        ble_mapping = {}
        
        # Formato nuovo: {"ble_mapping": {"MAC": "area"}}
        if 'ble_mapping' in mapping:
            ble_mapping = {mac.upper(): area for mac, area in mapping['ble_mapping'].items()}
        
        # Formato vecchio: {"entities": [{"mac": "...", "area": "..."}]}
        elif 'entities' in mapping:
            for entity in mapping.get('entities', []):
                mac = entity.get('mac')
                area = entity.get('area')
                if mac and area:
                    ble_mapping[mac.upper()] = area
        
        if ble_mapping:
            safe_print(f"✓ Caricata mappatura BLE: {len(ble_mapping)} dispositivi")
        return ble_mapping if ble_mapping else None
        
    except Exception as e:
        safe_print(f"⚠️ Errore caricamento {BLE_ENTITY_FILE}: {e}")
        return None

async def voice_detect_current_room(ble_mapping, scan_duration=3):
    """Rileva la stanza corrente basandosi sul beacon BLE con segnale più forte."""
    try:
        devices = await BleakScanner.discover(timeout=scan_duration, return_adv=True)
        
        strongest_device = None
        strongest_rssi = -1000
        strongest_room = None
        
        for device, adv_data in devices.values():
            mac = device.address.upper()
            if mac in ble_mapping:
                rssi = adv_data.rssi
                safe_print(f"📍 Beacon: {device.name or mac} → RSSI: {rssi}")
                
                if rssi > strongest_rssi:
                    strongest_rssi = rssi
                    strongest_device = device
                    strongest_room = ble_mapping[mac]
        
        if strongest_room:
            mac = strongest_device.address.upper()
            safe_print(f"📍 Beacon più forte: {strongest_device.name or mac} → {strongest_room} (RSSI: {strongest_rssi})")
            return strongest_room
        
        return None
            
    except Exception as e:
        safe_print(f"✗ Errore scansione BLE: {e}")
        return None

def voice_get_all_entities(ha_url, ha_token):
    """Recupera tutte le entità da Home Assistant (per voice control)."""
    try:
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        response = requests.get(f"{ha_url}/api/states", headers=headers, timeout=5)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        safe_print(f"✗ Errore recupero entità: {e}")
        return []

def voice_get_entities_in_area(ha_url, ha_token, area_id, domain_filter=None):
    """Recupera tutte le entità appartenenti a una specifica area/stanza usando API template."""
    try:
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        
        safe_print(f"🔍 Cerco entità per area_id: '{area_id}', domini: {domain_filter}")
        
        # Usa Jinja2 template per ottenere le entità dell'area
        # area_entities() restituisce tutte le entità (anche quelle assegnate via device)
        template = f"{{{{ area_entities('{area_id}') }}}}"
        
        response = requests.post(
            f"{ha_url}/api/template",
            headers=headers,
            json={"template": template},
            timeout=5
        )
        
        if response.status_code != 200:
            safe_print(f"✗ Errore API template: {response.status_code}")
            return []
        
        # L'API template restituisce il risultato come stringa, non come JSON array
        # Se il template è area_entities(), restituisce una stringa come "['light.led1', 'light.led2']"
        result_text = response.text.strip().strip('"')  # Rimuovi virgolette esterne se presenti
        
        # Converte la stringa Python list in una vera lista Python
        import ast
        try:
            entity_ids_in_area = ast.literal_eval(result_text)
            if not isinstance(entity_ids_in_area, list):
                entity_ids_in_area = []
        except (ValueError, SyntaxError):
            safe_print(f"✗ Errore parsing risposta template: {result_text}")
            return []
        
        safe_print(f"📊 Template ha trovato {len(entity_ids_in_area)} entità nell'area '{area_id}'")
        
        # Filtra per dominio se specificato
        if domain_filter:
            filtered_ids = [eid for eid in entity_ids_in_area 
                          if eid.split('.')[0] in domain_filter]
            safe_print(f"📊 Dopo filtro domini {domain_filter}: {len(filtered_ids)} entità")
        else:
            filtered_ids = entity_ids_in_area
        
        # Ottieni gli stati delle entità filtrate
        states_response = requests.get(f"{ha_url}/api/states", headers=headers, timeout=5)
        if states_response.status_code != 200:
            safe_print(f"✗ Errore API states: {states_response.status_code}")
            return []
        
        all_entities = states_response.json()
        
        # Trova le entità corrispondenti
        entities_in_area = []
        matched_entities = []
        for entity in all_entities:
            if entity['entity_id'] in filtered_ids:
                entities_in_area.append(entity)
                friendly_name = entity.get('attributes', {}).get('friendly_name', entity['entity_id'])
                matched_entities.append(f"{entity['entity_id']} ({friendly_name})")
        
        safe_print(f"✓ Trovate {len(entities_in_area)} entità nell'area '{area_id}': {matched_entities}")
        return entities_in_area
        
    except Exception as e:
        safe_print(f"✗ Errore recupero entità area: {e}")
        return []

def voice_find_entity_by_name(entities, name_to_find, current_room_entities=None, entity_domains=None):
    """Trova un'entità dal nome friendly o entity_id."""
    name_lower = name_to_find.lower().strip()
    if entity_domains is None:
        entity_domains = ['light']
    
    # Se abbiamo entità della stanza corrente, cerca prima lì
    if current_room_entities:
        for entity in current_room_entities:
            friendly_name = entity.get('attributes', {}).get('friendly_name', '')
            if friendly_name.lower() == name_lower:
                return entity['entity_id']
        
        for entity in current_room_entities:
            friendly_name = entity.get('attributes', {}).get('friendly_name', '')
            entity_id = entity['entity_id']
            if name_lower in friendly_name.lower() or name_lower in entity_id.lower():
                return entity['entity_id']
    
    # Cerca in tutte le entità ma solo nei domini configurati
    domain_prefixes = tuple(f"{d}." for d in entity_domains)
    filtered_entities = [e for e in entities if e['entity_id'].startswith(domain_prefixes)]
    
    for entity in filtered_entities:
        friendly_name = entity.get('attributes', {}).get('friendly_name', '')
        if friendly_name.lower() == name_lower:
            return entity['entity_id']
    
    for entity in filtered_entities:
        friendly_name = entity.get('attributes', {}).get('friendly_name', '')
        entity_id = entity['entity_id']
        if name_lower in friendly_name.lower() or name_lower in entity_id.lower():
            return entity['entity_id']
    
    return None

def voice_execute_command(ha_url, ha_token, entity_id, action):
    """Esegue un comando su un'entità."""
    try:
        domain = entity_id.split('.')[0]
        
        service_map = {
            'turn_on': f"{domain}.turn_on",
            'turn_off': f"{domain}.turn_off",
            'open_cover': "cover.open_cover",
            'close_cover': "cover.close_cover",
        }
        
        service = service_map.get(action)
        if not service:
            return False
        
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        
        payload = {"entity_id": entity_id}
        url = f"{ha_url}/api/services/{service.replace('.', '/')}"
        
        response = requests.post(url, headers=headers, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        safe_print(f"✗ Errore esecuzione comando: {e}")
        return False


class VoiceController:
    """Controller principale per il riconoscimento vocale."""
    
    def __init__(self, ha_instances, ble_mapping, entity_domains=None, group_lights_control=False):
        self.ha_instances = ha_instances  # Lista di istanze HA
        self.ha_url = None
        self.ha_token = None
        self.entities = []
        self.is_enabled = True
        self.is_listening = False
        self.ble_mapping = ble_mapping
        self.entity_domains = entity_domains or ['light']
        self.group_lights_control = group_lights_control
        self.current_room = None
        self.current_room_name = None
        self.current_room_lights = []
        self.room_cache_time = None
        self.room_cache_duration = 30  # Aumentato a 30s per dare tempo al voice command (registrazione 5s + riconoscimento ~2s)
        self.recognizer = sr.Recognizer()
        self.is_connected = False
        
        # Tenta connessione iniziale (non bloccante)
        self._try_connect()
    
    def _try_connect(self):
        """Tenta di connettersi a Home Assistant."""
        for instance in self.ha_instances:
            url = instance['url']
            token = instance['token']
            try:
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                response = requests.get(f"{url}/api/", headers=headers, timeout=3)
                if response.status_code == 200:
                    self.ha_url = url
                    self.ha_token = token
                    self.entities = voice_get_all_entities(url, token)
                    self.is_connected = True
                    safe_print(f"✓ Voice Control connesso a {url}")
                    return True
            except:
                continue
        self.is_connected = False
        return False
    
    def detect_room(self):
        """Rileva la stanza corrente tramite BLE e carica le sue luci."""
        if not self.ble_mapping:
            self.current_room = None
            self.current_room_name = None
            self.current_room_lights = []
            return
        
        # Verifica cache
        if self.room_cache_time and self.current_room:
            elapsed = time.time() - self.room_cache_time
            if elapsed < self.room_cache_duration:
                remaining = int(self.room_cache_duration - elapsed)
                safe_print(f"📍 Uso stanza in cache: {self.current_room_name} (ancora {remaining}s)")
                if self.current_room_lights:
                    light_names = [e.get('attributes', {}).get('friendly_name', e['entity_id']) 
                                  for e in self.current_room_lights]
                    safe_print(f"💡 {len(self.current_room_lights)} luci: {', '.join(light_names)}")
                return
        
        try:
            safe_print("📡 Rilevamento stanza...")
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            area_id = loop.run_until_complete(
                voice_detect_current_room(self.ble_mapping, scan_duration=3)
            )
            loop.close()
            
            if area_id:
                # Recupera il nome friendly dell'area
                area_info = get_area_info(area_id)
                self.current_room = area_id  # Salva l'ID per le query
                self.current_room_name = area_info['name']  # Salva il nome per la visualizzazione
                
                safe_print(f"📍 Stanza rilevata: {self.current_room_name}")
                self.current_room_lights = voice_get_entities_in_area(
                    self.ha_url, self.ha_token, area_id, 
                    domain_filter=self.entity_domains
                )
                if self.current_room_lights:
                    light_names = [e.get('attributes', {}).get('friendly_name', e['entity_id']) 
                                  for e in self.current_room_lights]
                    safe_print(f"💡 {len(self.current_room_lights)} luci trovate: {', '.join(light_names)}")
                else:
                    safe_print(f"⚠️  Nessuna luce trovata nella stanza {self.current_room_name}")
                
                # Imposta cache anche se non ci sono luci (la stanza è comunque stata rilevata)
                self.room_cache_time = time.time()
            else:
                safe_print("⚠️  Nessuna stanza rilevata")
                self.current_room = None
                self.current_room_name = None
                self.current_room_lights = []
                self.room_cache_time = None
                
        except Exception as e:
            safe_print(f"✗ Errore rilevamento stanza: {e}")
            self.current_room = None
            self.current_room_name = None
            self.current_room_lights = []
            self.room_cache_time = None
    
    def parse_command(self, text):
        """Analizza il comando vocale e determina azione ed entità.
        Supporta comandi speciali per gruppi:
        - 'tutte le luci' / 'le luci' / 'all lights' -> gruppo 'all_lights'
        - 'luce led' / 'luci led' / 'led lights' -> gruppo 'led_lights'
        """
        text_lower = text.lower().strip()
        
        commands = {
            # Italiano
            'accendi': 'turn_on',
            'accenda': 'turn_on',
            'attiva': 'turn_on',
            'spegni': 'turn_off',
            'spegna': 'turn_off',
            'disattiva': 'turn_off',
            'apri': 'open_cover',
            'chiudi': 'close_cover',
            # Inglese
            'turn on': 'turn_on',
            'switch on': 'turn_on',
            'turn off': 'turn_off',
            'switch off': 'turn_off',
            'open': 'open_cover',
            'close': 'close_cover',
        }
        
        action = None
        entity_name = None
        
        # Controlla prima i comandi di gruppo (se abilitati)
        if self.group_lights_control:
            # Pattern per "tutte le luci" o generico "le luci" (IT + EN)
            if any(phrase in text_lower for phrase in [
                # Italiano
                'tutte le luci', 'tutte le luce', 'tutte luci', 'le luci', 'la luce',
                # Inglese
                'all lights', 'all the lights', 'the lights'
            ]):
                for keyword, cmd in commands.items():
                    if keyword in text_lower:
                        return cmd, 'all_lights'
            
            # Pattern generico "lights" (solo se non è parte di un nome più lungo)
            import re
            if re.search(r'\blights\b', text_lower) and 'led' not in text_lower:
                for keyword, cmd in commands.items():
                    if keyword in text_lower:
                        return cmd, 'all_lights'
            
            # Pattern per "luce led" / "luci led" / "led" (IT + EN)
            # Controllo più specifico prima, poi quelli generici
            if any(phrase in text_lower for phrase in [
                # Italiano - specifici
                'tutti i led', 'tutte le led', 'luce led', 'luci led', 'le led', 'i led',
                # Inglese - specifici
                'led lights', 'led light', 'the led', 'the leds', 'all leds'
            ]):
                for keyword, cmd in commands.items():
                    if keyword in text_lower:
                        return cmd, 'led_lights'
            
            # Pattern generici "led" / "leds" (solo se non è parte di un nome più lungo)
            # Cerca parola "led" isolata o alla fine della frase
            import re
            if re.search(r'\b(led|leds)\b', text_lower):
                for keyword, cmd in commands.items():
                    if keyword in text_lower:
                        return cmd, 'led_lights'
        
        # Parsing normale per singole entità
        for keyword, cmd in commands.items():
            if keyword in text_lower:
                action = cmd
                parts = text_lower.split(keyword)
                if len(parts) > 1:
                    entity_name = parts[1].strip()
                    entity_name = entity_name.replace('la ', '').replace('il ', '').replace('lo ', '')
                    entity_name = entity_name.replace('luce ', '').replace('luci ', '')
                break
        
        if not action or not entity_name:
            return None, None
        
        return action, entity_name
    
    def listen_and_execute(self):
        """Ascolta un comando vocale ed esegue l'azione."""
        if not self.is_enabled or self.is_listening:
            return
        
        self.is_listening = True
        
        try:
            # La stanza è già stata rilevata in _detect_and_listen() prima di chiamare questo metodo
            # Non serve rilevare di nuovo, altrimenti si rischia di fare una nuova scansione BLE
            
            # Beep di attivazione
            play_beep(800, 60)
            safe_print("\n🎤 Ascolto attivo... Parla ora!")
            
            duration = 5
            sample_rate = 16000
            
            try:
                safe_print(f"⏺️  Registrazione in corso ({duration} secondi)...")
                
                audio_data = sd.rec(int(duration * sample_rate), 
                                   samplerate=sample_rate, 
                                   channels=1, 
                                   dtype='int16')
                sd.wait()
                
                safe_print("✓ Registrazione completata")
                
                max_amplitude = np.max(np.abs(audio_data))
                if max_amplitude < 100:
                    safe_print("⚠️  Audio troppo basso - microfono silenzioso?")
                
                audio_bytes = audio_data.tobytes()
                audio = sr.AudioData(audio_bytes, sample_rate, 2)
                
                safe_print("🔍 Riconoscimento in corso (Google Speech)...")
                text = self.recognizer.recognize_google(audio, language='it-IT')
                
                safe_print(f"✓ Riconosciuto: '{text}'")
                
                action, entity_name = self.parse_command(text)
                
                if action and entity_name:
                    # Gestione comandi di gruppo
                    if entity_name == 'all_lights':
                        if not self.current_room:
                            safe_print(f"✗ Nessuna stanza rilevata! Esegui prima una scansione BLE.")
                            play_beep(500, 150)
                        elif not self.current_room_lights:
                            safe_print(f"✗ Stanza {self.current_room_name} rilevata, ma nessuna luce configurata in Home Assistant per questa area.")
                            play_beep(500, 150)
                        else:
                            room_info = f" nella stanza {self.current_room_name}" if self.current_room_name else ""
                            safe_print(f"→ Esecuzione: {action} su TUTTE LE LUCI{room_info}")
                            
                            # Filtra solo le entità della stanza escludendo quelle con "led" nel nome
                            lights_to_control = []
                            
                            for entity in self.current_room_lights:
                                entity_id = entity.get('entity_id', '')
                                friendly_name = entity.get('attributes', {}).get('friendly_name', '')
                                
                                # Escludi entità con "led" nel nome
                                if entity_id.startswith('light.') and 'led' not in friendly_name.lower() and 'led' not in entity_id.lower():
                                    lights_to_control.append(entity_id)
                            
                            if lights_to_control:
                                success_count = 0
                                for light_id in lights_to_control:
                                    if voice_execute_command(self.ha_url, self.ha_token, light_id, action):
                                        success_count += 1
                                
                                safe_print(f"✓ {success_count}/{len(lights_to_control)} luci controllate con successo!")
                                play_beep(800, 60)
                            else:
                                safe_print(f"✗ Nessuna luce (non-LED) trovata{room_info}")
                                play_beep(500, 150)
                    
                    elif entity_name == 'led_lights':
                        if not self.current_room:
                            safe_print(f"✗ Nessuna stanza rilevata! Esegui prima una scansione BLE.")
                            play_beep(500, 150)
                        elif not self.current_room_lights:
                            safe_print(f"✗ Stanza {self.current_room_name} rilevata, ma nessuna luce configurata in Home Assistant per questa area.")
                            play_beep(500, 150)
                        else:
                            room_info = f" nella stanza {self.current_room_name}" if self.current_room_name else ""
                            safe_print(f"→ Esecuzione: {action} su LUCI LED{room_info}")
                            
                            # Filtra solo le entità LED della stanza
                            led_lights = []
                            
                            for entity in self.current_room_lights:
                                entity_id = entity.get('entity_id', '')
                                friendly_name = entity.get('attributes', {}).get('friendly_name', '')
                                
                                # Include solo entità con "led" nel nome
                                if entity_id.startswith('light.') and ('led' in friendly_name.lower() or 'led' in entity_id.lower()):
                                    led_lights.append(entity_id)
                            
                            if led_lights:
                                success_count = 0
                                for light_id in led_lights:
                                    if voice_execute_command(self.ha_url, self.ha_token, light_id, action):
                                        success_count += 1
                                
                                safe_print(f"✓ {success_count}/{len(led_lights)} luci LED controllate con successo!")
                                play_beep(800, 60)
                            else:
                                safe_print(f"✗ Nessuna luce LED trovata{room_info}")
                                play_beep(500, 150)
                    
                    # Gestione normale per singola entità
                    else:
                        entity_id = voice_find_entity_by_name(self.entities, entity_name, self.current_room_lights, self.entity_domains)
                        
                        if entity_id:
                            room_info = f" nella stanza {self.current_room_name}" if self.current_room_name else ""
                            safe_print(f"→ Esecuzione: {action} su {entity_id}{room_info}")
                            
                            if voice_execute_command(self.ha_url, self.ha_token, entity_id, action):
                                safe_print(f"✓ Comando eseguito con successo!")
                                play_beep(800, 60)
                            else:
                                safe_print(f"✗ Errore esecuzione comando")
                                play_beep(500, 150)
                        else:
                            room_info = f" nella stanza {self.current_room_name}" if self.current_room_name else ""
                            safe_print(f"✗ Entità '{entity_name}' non trovata{room_info}")
                            play_beep(500, 150)
                else:
                    safe_print(f"✗ Comando non valido")
                    play_beep(500, 150)
            
            except sr.UnknownValueError:
                safe_print("✗ Non ho capito, riprova")
                play_beep(500, 150)
            except sr.RequestError as e:
                safe_print(f"✗ Errore servizio Google: {e}")
                play_beep(500, 200)
            except Exception as recogn_error:
                safe_print(f"✗ Errore riconoscimento: {recogn_error}")
                play_beep(500, 200)
        
        except Exception as e:
            safe_print(f"✗ Errore: {e}")
        finally:
            self.room_cache_time = time.time()
            self.is_listening = False
            safe_print("🎤 Ascolto disattivato\n")
    
    def toggle_enabled(self):
        """Abilita/disabilita il controllo vocale."""
        self.is_enabled = not self.is_enabled
        status = "abilitato" if self.is_enabled else "disabilitato"
        safe_print(f"Controllo vocale {status}")
        return self.is_enabled


class VoiceControlAgent:
    """Agent per il controllo vocale, integrato in smart_proximity_control."""
    
    def __init__(self, ha_instances, ble_mapping=None, entity_domains=None, hotkey='ctrl+shift+i', group_lights_control=False):
        self.ha_instances = ha_instances  # Lista di istanze HA
        self.group_lights_control = group_lights_control
        self.ble_mapping = ble_mapping
        self.entity_domains = entity_domains or ['light']
        self.hotkey = hotkey
        self.is_running = False
        self.controller = None
        self._hotkey_registered = False
    
    def start(self):
        """Avvia l'agent e registra la hotkey."""
        if self.is_running:
            return False
        
        try:
            self.controller = VoiceController(self.ha_instances, self.ble_mapping, self.entity_domains, self.group_lights_control)
            
            keyboard.add_hotkey(self.hotkey, self._on_hotkey, suppress=False)
            self._hotkey_registered = True
            self.is_running = True
            
            safe_print(f"✓ Voice Control Agent attivo (hotkey: {self.hotkey})")
            return True
            
        except Exception as e:
            safe_print(f"✗ Errore avvio Voice Control: {e}")
            return False
    
    def stop(self):
        """Ferma l'agent e rimuove la hotkey."""
        if not self.is_running:
            return
        
        try:
            if self._hotkey_registered:
                keyboard.remove_hotkey(self.hotkey)
                self._hotkey_registered = False
        except:
            pass
        
        self.is_running = False
        self.controller = None
    
    def _on_hotkey(self):
        """Callback per la hotkey."""
        if not self.is_running or not self.controller:
            return
        
        safe_print("\n>>> Voice hotkey rilevata!")
        
        # Check connessione HA (lazy connect)
        if not self.controller.is_connected:
            safe_print("🔄 Tentativo connessione a Home Assistant...")
            if not self.controller._try_connect():
                safe_print("✗ Home Assistant non raggiungibile")
                play_beep(500, 200)
                return
        
        if self.controller.ble_mapping:
            threading.Thread(target=self._detect_and_listen, daemon=True).start()
        else:
            threading.Thread(target=self.controller.listen_and_execute, daemon=True).start()
    
    def _detect_and_listen(self):
        """Rileva la stanza e poi avvia l'ascolto."""
        self.controller.detect_room()
        self.controller.listen_and_execute()
    
    def toggle_enabled(self):
        """Abilita/disabilita l'ascolto."""
        if self.controller:
            return self.controller.toggle_enabled()
        return False

# =============================================================================
# FINE VOICE CONTROL INTEGRATO
# =============================================================================

def test_ha_connection(url, token, timeout=3):
    """Test connection to a Home Assistant instance."""
    try:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        response = requests.get(f"{url}/api/", headers=headers, timeout=timeout)
        if response.status_code == 200:
            api_info = response.json()
            safe_print(f"✓ Connected to Home Assistant at {url} (version {api_info.get('version', 'unknown')})")
            return True
        else:
            safe_print(f"✗ Failed to connect to {url}: Status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        safe_print(f"✗ Cannot reach {url}: {e}")
        return False

def detect_available_instance(ha_instances, current_url=None):
    """Detects the first available Home Assistant instance from the list.
    
    Args:
        ha_instances: List of dicts with 'url' and 'token' keys
        current_url: The currently connected URL (optional). If provided, it will be tested first.
        
    Returns:
        Tuple (url, token) of the first available instance, or (None, None) if none available
    """
    if not ha_instances:
        safe_print("Error: No Home Assistant instances configured")
        return None, None
    
    safe_print(f"\nTesting {len(ha_instances)} Home Assistant instance(s)...")
    
    # Se abbiamo un URL corrente, testalo per primo
    if current_url:
        for instance in ha_instances:
            if instance['url'] == current_url:
                safe_print(f"\nTesting current instance: {current_url}")
                if test_ha_connection(current_url, instance['token'], timeout=2):
                    safe_print(f"\n✓ Current instance still available: {current_url}\n")
                    return current_url, instance['token']
                else:
                    safe_print(f"\n✗ Current instance {current_url} no longer available, trying others...")
                break
    
    # Testa tutte le istanze
    for i, instance in enumerate(ha_instances, 1):
        url = instance['url']
        token = instance['token']
        
        # Salta l'istanza corrente se già testata
        if url == current_url:
            continue
            
        safe_print(f"\nTesting instance {i}/{len(ha_instances)}: {url}")
        
        if test_ha_connection(url, token):
            safe_print(f"\n✓ Using Home Assistant instance: {url}\n")
            return url, token
    
    safe_print("\n✗ No Home Assistant instances are reachable!")
    safe_print("Please check your network connection and configuration.\n")
    return None, None

def singleton():
    """Ensures that only one instance of the program is running."""
    lock_file_path = os.path.join(tempfile.gettempdir(), 'hapy.lock')

    if sys.platform == 'win32':
        import msvcrt
        try:
            global lock_file
            lock_file = open(lock_file_path, 'w')
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1) 
            atexit.register(lambda: lock_file.close())
            return True
        except (IOError, OSError):
            safe_print("Error: Another instance of the program is already running.")
            return False
    else:
        import fcntl
        global lock_fd
        try:
            lock_fd = open(lock_file_path, 'w')
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            atexit.register(lambda: lock_fd.close())
            return True
        except (IOError, BlockingIOError):
            safe_print("Error: Another instance of the program is already running.")
            return False

def carica_configurazione(file_path='config.ini'):
    """Reads the configuration file and returns the settings."""
    base_path = get_base_path()
    full_path = os.path.join(base_path, file_path)
    
    if not os.path.exists(full_path):
        safe_print(f"Error: Configuration file '{full_path}' not found.")
        safe_print("Please create it with your Home Assistant URL and API token.")
        safe_print("Example:\n")
        safe_print("[home_assistant]")
        safe_print("url = http://your-home-assistant-ip:8123")
        safe_print("api_token = your_long_lived_access_token\n")
        safe_print("For more details, please read the README.md file.")
        return None, None, None, None, None, None, None

    config = configparser.ConfigParser()
    config.read(file_path)
    try:
        # Carica tutte le istanze di Home Assistant (fino a 5)
        ha_instances = []
        
        # Prima istanza (obbligatoria)
        ha_url = config.get('home_assistant', 'url')
        ha_token = config.get('home_assistant', 'api_token')
        
        if not ha_url.startswith(('http://', 'https://')):
            safe_print(f"Error: URL must start with http:// or https://")
            safe_print(f"Current value: {ha_url}")
            return None, None, None, None, None, None
        
        if len(ha_token) < 50:
            safe_print(f"Error: API token seems too short. Make sure you're using a Long-Lived Access Token.")
            return None, None, None, None, None, None
        
        ha_instances.append({'url': ha_url, 'token': ha_token})
        
        # Istanze aggiuntive (opzionali, da 2 a 5)
        for i in range(2, 6):
            try:
                url_key = f'url_{i}'
                token_key = f'api_token_{i}'
                
                url = config.get('home_assistant', url_key)
                token = config.get('home_assistant', token_key)
                
                if url and token:
                    if not url.startswith(('http://', 'https://')):
                        safe_print(f"Warning: Instance {i} URL must start with http:// or https://, skipping")
                        continue
                    
                    if len(token) < 50:
                        safe_print(f"Warning: Instance {i} API token seems too short, skipping")
                        continue
                    
                    ha_instances.append({'url': url, 'token': token})
                    safe_print(f"✓ Loaded Home Assistant instance {i}: {url}")
            except (configparser.NoOptionError, configparser.NoSectionError):
                # Istanza non configurata, continua
                pass
        
        safe_print(f"Total Home Assistant instances configured: {len(ha_instances)}")
        
        app_title = config.get('gui', 'title', fallback='hapy')
        icon_size = config.getint('gui', 'icon_size', fallback=48)
        show_tooltips = config.getboolean('gui', 'show_tooltips', fallback=True)
        
        entity_domains = config.get('filters', 'entity_domains', fallback='light,switch')
        entity_domains_list = [d.strip() for d in entity_domains.split(',')]
        
        # Impostazioni Voice Control (opzionali)
        voice_config = {
            'enabled': config.getboolean('home_assistant', 'voice_control', fallback=False),
            'hotkey': config.get('home_assistant', 'voice_hotkey', fallback='ctrl+shift+i'),
            'entity_domains': config.get('home_assistant', 'entity_domains', fallback='light').split(','),
            'group_lights_control': config.getboolean('home_assistant', 'group_lights_control', fallback=False),
            'show_hotkey': config.get('home_assistant', 'show_hotkey', fallback='ctrl+shift+space'),
            'quit_hotkey': config.get('home_assistant', 'quit_hotkey', fallback='ctrl+shift+q')
        }
        voice_config['entity_domains'] = [d.strip() for d in voice_config['entity_domains']]
        
        # Impostazione suoni
        enable_sounds = config.getboolean('home_assistant', 'enable_sounds', fallback=True)
        
        return ha_instances, app_title, icon_size, show_tooltips, entity_domains_list, voice_config, enable_sounds
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        safe_print(f"Error: The configuration file '{file_path}' is invalid.")
        safe_print(f"Make sure it contains a [home_assistant] section with 'url' and 'api_token' keys.")
        safe_print(f"Error details: {e}")
        safe_print("\nPlease refer to README.md for configuration instructions.")
        return None, None, None, None, None, None, None

def carica_mappatura_ble(file_path=BLE_ENTITY_FILE):
    """Carica la mappatura dei dispositivi BLE con gli ID area."""
    base_path = get_base_path()
    full_path = os.path.join(base_path, file_path)
    
    if not os.path.exists(full_path):
        safe_print(f"Error: BLE entity file '{file_path}' not found.")
        safe_print("Please create it with your BLE device mappings using AREA IDs.")
        safe_print("Example format:")
        safe_print('''
{
    "ble_mapping": {
        "F2:EC:8F:2A:BE:2D": "area_id_1",
        "AA:BB:CC:DD:EE:FF": "area_id_2"
    }
}''')
        safe_print("\nUse the provided script to get your area IDs from Home Assistant.")
        return None

    try:
        with open(full_path, 'r') as file:
            data = json.load(file)
            return data.get("ble_mapping", {})
    except Exception as e:
        safe_print(f"Error loading BLE entity file: {e}")
        return None

def get_area_info(area_id):
    """Recupera informazioni su un'area dato l'ID."""
    try:
        url = f"{HOME_ASSISTANT_URL}/api/config/area_registry"
        response = requests.get(url, headers=HEADERS, timeout=5)
        
        if response.status_code == 200:
            areas = response.json()
            for area in areas:
                if area.get('area_id') == area_id:
                    return {
                        'name': area.get('name', area_id),
                        'id': area_id
                    }
            # Area non trovata nel registry
            return {'name': area_id, 'id': area_id}
        
        elif response.status_code == 404:
            # API area_registry non disponibile, usa template Jinja2
            logger.info(f"Area registry API not available, using template for area {area_id}")
            template_url = f"{HOME_ASSISTANT_URL}/api/template"
            
            # Ottieni il nome dell'area usando il template
            name_template = f"{{{{ area_name('{area_id}') }}}}"
            name_response = requests.post(template_url, headers=HEADERS,
                                         json={"template": name_template}, timeout=5)
            
            if name_response.status_code == 200:
                area_name = name_response.text.strip()
                # Se il template ritorna l'area_id stesso, l'area non esiste
                if area_name and area_name != area_id:
                    return {'name': area_name, 'id': area_id}
            
            return {'name': area_id, 'id': area_id}
        
        else:
            logger.warning(f"Unexpected status code {response.status_code} from area_registry")
            return {'name': area_id, 'id': area_id}
        
    except Exception as e:
        logger.error(f"Error getting area info: {e}")
        return {'name': area_id, 'id': area_id}

def get_area_ids(ha_url=None, ha_token=None):
    """Recupera tutti gli ID area da Home Assistant usando i template.
    Se chiamata senza parametri, usa le variabili globali.
    Utile per vedere tutte le aree disponibili.
    """
    url = ha_url or HOME_ASSISTANT_URL
    token = ha_token or API_TOKEN
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    try:
        # Prova prima con area_registry (versioni più recenti di HA)
        api_url = f"{url}/api/config/area_registry"
        response = requests.get(api_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            areas = response.json()
            safe_print("\n✓ Aree trovate in Home Assistant:")
            safe_print("=" * 60)
            for area in areas:
                safe_print(f"  ID: {area['area_id']:<20} Nome: {area.get('name', 'N/A')}")
            safe_print("=" * 60)
            safe_print(f"\nTotale: {len(areas)} aree")
            return areas
        elif response.status_code == 404:
            # Fallback: usa il template areas()
            safe_print("\n⚠ Area registry non disponibile, uso template Jinja2...")
            template_url = f"{url}/api/template"
            template = "{{ areas() }}"
            template_response = requests.post(template_url, headers=headers, json={"template": template}, timeout=5)
            
            if template_response.status_code == 200:
                area_ids = eval(template_response.text)
                safe_print("\n✓ Aree trovate in Home Assistant (solo ID):")
                safe_print("=" * 60)
                for area_id in area_ids:
                    # Ottieni il nome usando area_name()
                    name_template = f"{{{{ area_name('{area_id}') }}}}"
                    name_response = requests.post(template_url, headers=headers, json={"template": name_template}, timeout=5)
                    name = name_response.text.strip() if name_response.status_code == 200 else area_id
                    safe_print(f"  ID: {area_id:<20} Nome: {name}")
                safe_print("=" * 60)
                safe_print(f"\nTotale: {len(area_ids)} aree")
                return [{'area_id': aid, 'name': aid} for aid in area_ids]
            else:
                safe_print(f"Errore template: {template_response.status_code}")
                return []
        else:
            safe_print(f"Errore: {response.status_code} - {response.text}")
            return []
            
    except Exception as e:
        safe_print(f"Errore durante il recupero delle aree: {e}")
        return []

def get_entities_for_area(area_id, allowed_domains=None):
    """Recupera tutte le entità di un'area specifica usando l'API nativa di Home Assistant.
    
    Questo approccio usa area_entities template che restituisce le entity_id dell'area,
    poi ottiene lo stato per filtrarle per dominio.
    """
    if allowed_domains is None:
        allowed_domains = ['light']
    
    entities = []
    
    try:
        # Usa il template di HA per ottenere le entità dell'area
        # area_entities(area_name_or_id) funziona sia con nome che con ID
        template = f"{{{{ area_entities('{area_id}') }}}}"
        
        template_url = f"{HOME_ASSISTANT_URL}/api/template"
        template_payload = {"template": template}
        
        template_response = requests.post(template_url, headers=HEADERS, json=template_payload, timeout=5)
        template_response.raise_for_status()
        
        # Il template restituisce una lista di entity_id
        area_entity_ids = eval(template_response.text)  # Converte la stringa lista in lista Python
        
        logger.info(f"Trovate {len(area_entity_ids)} entità totali nell'area '{area_id}'")
        
        if not area_entity_ids:
            logger.warning(f"Nessuna entità trovata per l'area '{area_id}'")
            return []
        
        # Ottieni lo stato di tutte le entità
        states_url = f"{HOME_ASSISTANT_URL}/api/states"
        states_response = requests.get(states_url, headers=HEADERS, timeout=5)
        states_response.raise_for_status()
        all_states = states_response.json()
        
        # Crea un dizionario entity_id -> state per accesso veloce
        states_dict = {s['entity_id']: s for s in all_states}
        
        # Filtra per dominio
        for entity_id in area_entity_ids:
            domain = entity_id.split('.')[0]
            
            if domain in allowed_domains:
                state = states_dict.get(entity_id)
                if state:
                    entities.append({
                        'entity_id': entity_id,
                        'alias': state.get('attributes', {}).get('friendly_name', entity_id.replace('_', ' ').title())
                    })
                    logger.info(f"Aggiunta entità: {entity_id}")
        
        logger.info(f"Trovate {len(entities)} entità per l'area '{area_id}' (domini: {', '.join(allowed_domains)})")
        return entities
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting entities for area '{area_id}': {e}")
        return []

async def ble_scanner_task(ble_mapping, callback, stop_event, single_scan=False):
    """Task asincrono che scansiona i dispositivi BLE e trova quello con segnale più forte.
    
    Args:
        ble_mapping: Dizionario {mac: area_id}
        callback: Funzione da chiamare con area_id quando trovato
        stop_event: Event per fermare la scansione
        single_scan: Se True, fa una sola scansione e ritorna
    """
    target_macs = {mac.upper(): area_id for mac, area_id in ble_mapping.items()}
    
    while not stop_event.is_set():
        logger.info("Avvio scansione BLE per trovare dispositivo più vicino...")
        safe_print("Scansione BLE in corso...")
        
        strongest_device = None
        strongest_rssi = -1000  # Valore molto basso
        
        try:
            devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
            
            # Trova il dispositivo target con RSSI più alto (segnale più forte)
            for device, adv_data in devices.values():
                if device.address.upper() in target_macs:
                    rssi = adv_data.rssi
                    logger.info(f"Trovato {device.address.upper()} con RSSI: {rssi}")
                    
                    if rssi > strongest_rssi:
                        strongest_rssi = rssi
                        strongest_device = device
            
            if strongest_device:
                found_mac = strongest_device.address.upper()
                area_id = target_macs.get(found_mac)
                
                logger.info(f"Dispositivo più vicino: {found_mac} (RSSI: {strongest_rssi})")
                safe_print(f"Dispositivo più vicino: {found_mac} (RSSI: {strongest_rssi})")
                
                if area_id:
                    logger.info(f"Area rilevata: {area_id}")
                    callback(area_id)
                    if single_scan:
                        return
                else:
                    logger.warning(f"MAC trovato ma area_id mancante: {found_mac}")
            else:
                logger.info("Nessun dispositivo BLE target rilevato")
                safe_print("Nessun dispositivo nelle vicinanze")
                # Se è una scansione singola e non trova dispositivi, notifica comunque
                if single_scan:
                    callback(None)
                
        except Exception as e:
            logger.error(f"Errore durante la scansione BLE: {e}")
            safe_print(f"Errore scansione BLE: {e}")
            # Notifica errore in caso di scansione singola
            if single_scan:
                callback(None)
        
        if single_scan or stop_event.is_set():
            return
            
        await asyncio.sleep(5)

def run_ble_scanner(ble_mapping, callback, stop_event, single_scan=False):
    """Wrapper per eseguire il task asincrono BLE in un thread separato."""
    asyncio.run(ble_scanner_task(ble_mapping, callback, stop_event, single_scan))

def get_stato_entita(entity_id, max_retries=3):
    """Gets the state of a single entity from Home Assistant with retry logic."""
    url = f"{HOME_ASSISTANT_URL}/api/states/{entity_id}"
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=HEADERS, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                logger.error(f"Error connecting to Home Assistant after {max_retries} attempts: {e}")
                safe_print(f"Errore durante la connessione ad Home Assistant: {e}")
                return None
            # Backoff esponenziale: 0.5s, 1s, 1.5s
            time.sleep(0.5 * (attempt + 1))
    
    return None

def toggle_entita(entity_id):
    """Toggles the state of a single entity."""
    domain = entity_id.split('.')[0]
    service = 'toggle'
    url = f"{HOME_ASSISTANT_URL}/api/services/{domain}/{service}"
    payload = {"entity_id": entity_id}
    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error toggling state for '{entity_id}': {e}")
        safe_print(f"Errore durante l'inversione dello stato di '{entity_id}': {e}")
        return False

def set_cover_position(entity_id, position):
    """Sets the position of a cover entity."""
    url = f"{HOME_ASSISTANT_URL}/api/services/cover/set_cover_position"
    payload = {"entity_id": entity_id, "position": position}
    try:
        response = requests.post(url, headers=HEADERS, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Error setting position for '{entity_id}': {e}")
        safe_print(f"Errore durante l'impostazione della posizione per '{entity_id}': {e}")
        return False

CACHE_DIR = 'icon_cache'
class ImageProvider(QObject):
    """Handles downloading, caching, and providing images as QPixmaps."""
    image_ready = Signal(str, QPixmap)

    def __init__(self):
        super().__init__()
        self._cache = {}
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

    def get_pixmap(self, domain, state_data):
        """Requests a pixmap. Returns from cache or starts a download thread."""
        if not state_data:
            return None
            
        state = state_data.get('state', 'unknown')
        icon_name = 'alert-circle'

        if domain == 'cover':
            position = state_data.get('attributes', {}).get('current_position', 0)
            if position < 36:
                icon_name = ICONS_MAP['cover'].get(0, 'window-shutter')
            else:
                icon_name = ICONS_MAP['cover'].get('open', 'window-shutter-open')
        else:
            icon_name = ICONS_MAP.get(domain, {}).get(state, 'alert-circle')

        # Usa sempre icon_name come parte della cache_key per coerenza
        cache_key = f"{domain}_{icon_name}"
        if icon_name == 'loading':
            cache_key = 'loading_icon'

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Determina il colore per le icone accese
        color = None
        if state == 'on' and domain in ['light', 'switch', 'fan']:
            color = '#FFD700'  # Giallo oro per dispositivi accesi
        
        # Check file cache
        cached_path = os.path.join(CACHE_DIR, f"{icon_name}.svg")
        if os.path.exists(cached_path):
            self._load_image_from_file(cache_key, cached_path, color)
            return None # The signal will deliver the pixmap

        # Download in a separate thread
        threading.Thread(target=self._download_image, args=(cache_key, icon_name, color), daemon=True).start()
        return None

    def _load_image_from_file(self, cache_key, file_path, color=None):
        try:
            with open(file_path, 'rb') as f:
                svg_data = f.read()
            
            # Colora l'SVG se richiesto
            if color:
                svg_data = self._colorize_svg(svg_data, color)
            
            renderer = QSvgRenderer(svg_data)
            pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
            # Use the correct enum access for PyQt6
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            self._cache[cache_key] = pixmap
            self.image_ready.emit(cache_key, pixmap)
        except Exception as e:
            logger.error(f"Error loading cached icon '{file_path}': {e}")
    
    def _colorize_svg(self, svg_data, color):
        """Colora un SVG sostituendo il colore di fill."""
        svg_str = svg_data.decode('utf-8')
        # Sostituisci il nero (#000) con il colore desiderato
        svg_str = svg_str.replace('fill="#000"', f'fill="{color}"')
        svg_str = svg_str.replace('fill="black"', f'fill="{color}"')
        # Aggiungi fill se non presente
        if 'fill=' not in svg_str and '<path' in svg_str:
            svg_str = svg_str.replace('<path ', f'<path fill="{color}" ')
        return svg_str.encode('utf-8')

    def _download_image(self, cache_key, icon_name, color=None):
        try:
            url = f"{ICONS_BASE_URL}/{icon_name}.svg"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            svg_data = response.content

            # Save to file cache (versione non colorata)
            cached_path = os.path.join(CACHE_DIR, f"{icon_name}.svg")
            with open(cached_path, 'wb') as f:
                f.write(svg_data)

            # Colora l'SVG se richiesto
            if color:
                svg_data = self._colorize_svg(svg_data, color)

            # Render SVG directly for high quality
            renderer = QSvgRenderer(svg_data)
            pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
            # Use the correct enum access for PyQt6
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            self._cache[cache_key] = pixmap
            self.image_ready.emit(cache_key, pixmap)
        except Exception as e:
            logger.error(f"Error downloading or converting icon '{icon_name}': {e}")

class EntityWidget(QWidget):
    """A widget representing a single Home Assistant entity."""
    def __init__(self, item, image_provider):
        super().__init__()
        self.item = item
        self.image_provider = image_provider
        self.image_provider.image_ready.connect(self._on_image_ready)
        self.entity_id = item['entity_id']
        self.state_data = None # Cache for state data
        self.is_loading = False
        self.animation_timer = None
        self.rotation_angle = 0

        # Stile card moderno
        self.setStyleSheet("""
            EntityWidget {
                background-color: rgba(52, 73, 94, 0.8);
                border-radius: 12px;
                padding: 10px;
            }
            EntityWidget:hover {
                background-color: rgba(52, 73, 94, 0.95);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 12)  # Più margine in basso
        layout.setSpacing(8)  # Più spazio tra icona e testo
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)  # Allinea in alto e centro orizzontale

        self.icon_label = QLabel()
        # Use the correct enum access for PyQt6
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(ICON_SIZE + 16, ICON_SIZE)  # Larghezza maggiore per centrare

        alias_label = QLabel(item.get('alias', self.entity_id))
        alias_label.setWordWrap(True)
        alias_label.setMaximumWidth(ICON_SIZE + 40)  # Larghezza maggiore per il testo
        alias_label.setMinimumHeight(36)  # Altezza minima per 3 righe di testo
        # Use the correct enum access for PyQt6
        alias_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)  # Testo allineato in alto
        alias_label.setStyleSheet("""
            color: #ecf0f1;
            font-size: 8pt;
            font-weight: 500;
            background: transparent;
        """)

        layout.addWidget(self.icon_label)
        layout.addWidget(alias_label)

        # Use the correct enum access for PyQt6
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)) # Use QCursor explicitly

        # Create a shadow effect più moderna
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(20)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(4)
        # Use the correct enum access for PyQt6
        self.shadow.setColor(Qt.GlobalColor.black)
        self.shadow.setOffset(0, 3)
        self.shadow.setEnabled(False) # Disabled by default
        self.setGraphicsEffect(self.shadow)


    def _on_image_ready(self, cache_key, pixmap):
        # Check if this image is still relevant for the current state
        if self.is_loading and cache_key == 'loading_icon':
            self._start_animation_timer(pixmap)
        elif self.state_data:
            current_icon_name = self._get_current_icon_name()
            expected_cache_key = f"{self.entity_id.split('.')[0]}_{current_icon_name}"
            if cache_key == expected_cache_key:
                self.icon_label.setPixmap(pixmap)
        # Handle the case where the state changed while the download was running
        elif not self.state_data and cache_key == 'loading_icon':
            # This handles the initial load of the loading icon
            self._start_animation_timer(pixmap)


    def _get_current_icon_name(self):
        if not self.state_data:
            return 'alert-circle'

        domain = self.entity_id.split('.')[0]
        state = self.state_data['state']

        if domain == 'cover':
            position = self.state_data.get('attributes', {}).get('current_position', 0)
            if position < 36:
                return ICONS_MAP['cover'].get(0, 'window-shutter')
            else:
                return ICONS_MAP['cover'].get('open', 'window-shutter-open')
        else:
            return ICONS_MAP.get(domain, {}).get(state, 'alert-circle')

    def update_visual_state(self, state_data):
        self.state_data = state_data # Cache the state
        self.stop_loading_animation()
        if state_data:
            pixmap = self.image_provider.get_pixmap(self.entity_id.split('.')[0], state_data)
            if pixmap: # If pixmap is in cache, display it
                self.icon_label.setPixmap(pixmap)

            if SHOW_TOOLTIPS:
                last_updated = state_data.get('last_updated', 'N/A')
                self.setToolTip(f"Last Updated:\n{self.format_timestamp(last_updated)}")
        else:
            # Se non ci sono dati di stato, mostra icona di errore
            pixmap = self.image_provider.get_pixmap('system', {'state': 'alert'})
            if pixmap:
                self.icon_label.setPixmap(pixmap)

    def start_loading_animation(self):
        self.is_loading = True
        loading_pixmap = self.image_provider.get_pixmap('system', {'state': 'loading'})
        if loading_pixmap: # If loading icon is already cached
            self._start_animation_timer(loading_pixmap)
        # If not cached, _on_image_ready will start the animation when it's downloaded

    def _start_animation_timer(self, pixmap):
        self.base_loading_pixmap = pixmap
        if not self.animation_timer:
            self.animation_timer = QTimer(self)
            self.animation_timer.timeout.connect(self._rotate_icon)
            self.animation_timer.start(50)
    
    def stop_loading_animation(self):
        self.is_loading = False
        if self.animation_timer:
            self.animation_timer.stop()
            self.animation_timer = None
        self.rotation_angle = 0

    def _rotate_icon(self):
        if not self.is_loading or not hasattr(self, 'base_loading_pixmap'):
            return
        self.rotation_angle = (self.rotation_angle - 15) % 360
        transform = QTransform().rotate(self.rotation_angle)
        # Use the correct enum access for PyQt6
        rotated_pixmap = self.base_loading_pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation) 
        self.icon_label.setPixmap(rotated_pixmap)

    def format_timestamp(self, ts_string):
        if ts_string == 'N/A': return ts_string
        try: return datetime.fromisoformat(ts_string).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError): return ts_string

    def customEvent(self, event: QEvent):
        """Handles custom events, specifically for state updates."""
        if event.type() == StateUpdateEvent.EVENT_TYPE:
            self.update_visual_state(event.state_data)
            event.setAccepted(True)
        # Call super().customEvent for unhandled events
        super().customEvent(event)


class SettingsWindow(QWidget):
    """Finestra moderna per la configurazione dei parametri."""
    
    def __init__(self, config_file='config.ini'):
        super().__init__()
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.init_ui()
    
    def init_ui(self):
        """Inizializza l'interfaccia grafica."""
        self.setWindowTitle("⚙️ Smart Proximity Control - Settings")
        self.setFixedSize(700, 800)
        
        # Stile moderno coerente con l'app principale
        self.setStyleSheet("""
            SettingsWindow {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e3c72, stop:1 #2a5298
                );
            }
            QLabel {
                color: #ecf0f1;
                font-size: 10pt;
                font-weight: 500;
            }
            QLabel#section_title {
                color: #3498db;
                font-size: 12pt;
                font-weight: bold;
                padding: 10px 0px;
            }
            QLineEdit, QSpinBox {
                background-color: rgba(52, 73, 94, 0.8);
                color: #ecf0f1;
                border: 2px solid rgba(52, 152, 219, 0.3);
                border-radius: 6px;
                padding: 8px;
                font-size: 10pt;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #3498db;
            }
            QCheckBox {
                color: #ecf0f1;
                font-size: 10pt;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid rgba(52, 152, 219, 0.5);
                background: rgba(52, 73, 94, 0.8);
            }
            QCheckBox::indicator:checked {
                background: #3498db;
                border-color: #3498db;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 11pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #21618c;
            }
            QPushButton#cancel_btn {
                background-color: rgba(231, 76, 60, 0.8);
            }
            QPushButton#cancel_btn:hover {
                background-color: rgba(192, 57, 43, 0.9);
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QWidget#scroll_content {
                background: transparent;
            }
        """)
        
        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Titolo
        title_label = QLabel("⚙️ Configurazione")
        title_label.setStyleSheet("font-size: 18pt; font-weight: bold; color: #ecf0f1; padding: 10px;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Scroll area per i settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        scroll_widget = QWidget()
        scroll_widget.setObjectName("scroll_content")
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(20)
        
        # === Home Assistant Settings ===
        self.ha_section = self.create_ha_section()
        scroll_layout.addWidget(self.ha_section)
        
        # === BLE Beacons Settings ===
        self.beacon_section = self.create_beacon_section()
        scroll_layout.addWidget(self.beacon_section)
        
        # === Voice Control Settings ===
        voice_section = self.create_section("🎤 Voice Control", [
            ("Abilita Voice Control:", "voice_control", "bool"),
            ("Hotkey Voice:", "voice_hotkey", "text"),
            ("Domini Entità:", "entity_domains", "text"),
            ("Abilita Controllo Gruppi Luci:", "group_lights_control", "bool"),
        ])
        scroll_layout.addWidget(voice_section)
        
        # === Hotkeys Settings ===
        hotkey_section = self.create_section("⌨️ Hotkeys", [
            ("Mostra Finestra:", "show_hotkey", "text"),
            ("Esci:", "quit_hotkey", "text"),
        ])
        scroll_layout.addWidget(hotkey_section)
        
        # === GUI Settings ===
        gui_section = self.create_section("🎨 Interfaccia", [
            ("Titolo Applicazione:", "title", "text", "[gui]"),
            ("Dimensione Icone:", "icon_size", "number", "[gui]"),
            ("Mostra Tooltip:", "show_tooltips", "bool", "[gui]"),
        ])
        scroll_layout.addWidget(gui_section)
        
        # === Filters Settings ===
        filter_section = self.create_section("🔍 Filtri", [
            ("Domini Entità (proximity):", "entity_domains", "text", "[filters]"),
        ])
        scroll_layout.addWidget(filter_section)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        
        # Pulsanti Salva/Annulla
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        cancel_btn = QPushButton("✖ Annulla")
        cancel_btn.setObjectName("cancel_btn")
        cancel_btn.clicked.connect(self.close)
        
        save_btn = QPushButton("💾 Salva e Riavvia Agent")
        save_btn.clicked.connect(self.save_and_restart)
        
        buttons_layout.addWidget(cancel_btn)
        buttons_layout.addWidget(save_btn)
        
        main_layout.addLayout(buttons_layout)
    
    def create_ha_section(self):
        """Crea la sezione Home Assistant con possibilità di aggiungere istanze."""
        section_frame = QFrame()
        section_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(52, 73, 94, 0.6);
                border-radius: 12px;
                padding: 15px;
            }
        """)
        
        self.ha_layout = QVBoxLayout(section_frame)
        self.ha_layout.setSpacing(12)
        
        # Titolo sezione
        title_label = QLabel("🏠 Home Assistant")
        title_label.setObjectName("section_title")
        self.ha_layout.addWidget(title_label)
        
        # Contenitore per le istanze
        self.ha_instances_layout = QVBoxLayout()
        self.ha_instances_layout.setSpacing(15)
        
        # Conta quante istanze esistono
        self.ha_instance_count = 1
        for i in range(2, 6):
            url_key = f'url_{i}' if i > 1 else 'url'
            if self.config.has_option('home_assistant', url_key):
                url = self.config.get('home_assistant', url_key, fallback='')
                if url:
                    self.ha_instance_count = i
        
        # Crea campi per le istanze esistenti
        for i in range(1, self.ha_instance_count + 1):
            self.add_ha_instance_fields(i)
        
        self.ha_layout.addLayout(self.ha_instances_layout)
        
        # Pulsante Aggiungi Istanza
        add_btn_layout = QHBoxLayout()
        self.add_instance_btn = QPushButton("➕ Aggiungi Istanza Home Assistant")
        self.add_instance_btn.clicked.connect(self.add_new_ha_instance)
        self.add_instance_btn.setEnabled(self.ha_instance_count < 5)
        add_btn_layout.addStretch()
        add_btn_layout.addWidget(self.add_instance_btn)
        add_btn_layout.addStretch()
        self.ha_layout.addLayout(add_btn_layout)
        
        return section_frame
    
    def add_ha_instance_fields(self, instance_num):
        """Aggiunge i campi per una istanza Home Assistant."""
        instance_frame = QFrame()
        instance_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(44, 62, 80, 0.4);
                border-radius: 8px;
                padding: 10px;
                margin: 5px 0px;
            }
        """)
        instance_frame.setProperty("instance_num", instance_num)
        instance_layout = QVBoxLayout(instance_frame)
        instance_layout.setSpacing(8)
        
        # Header con numero istanza e pulsante rimuovi
        header_layout = QHBoxLayout()
        header_label = QLabel(f"📍 Istanza {instance_num}" + (" (Primaria)" if instance_num == 1 else ""))
        header_label.setStyleSheet("color: #3498db; font-weight: bold; font-size: 10pt;")
        header_layout.addWidget(header_label)
        
        # Pulsante rimuovi (solo per istanze > 1)
        if instance_num > 1:
            remove_btn = QPushButton("🗑️ Rimuovi")
            remove_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(231, 76, 60, 0.7);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(192, 57, 43, 0.9);
                }
            """)
            remove_btn.clicked.connect(lambda: self.remove_ha_instance(instance_frame))
            header_layout.addStretch()
            header_layout.addWidget(remove_btn)
        
        instance_layout.addLayout(header_layout)
        
        # URL
        url_key = 'url' if instance_num == 1 else f'url_{instance_num}'
        url_layout = QHBoxLayout()
        url_label = QLabel("URL:")
        url_label.setFixedWidth(100)
        url_field = QLineEdit()
        url_field.setText(self.config.get('home_assistant', url_key, fallback=''))
        url_field.setPlaceholderText("http://homeassistant.local:8123")
        url_field.setObjectName(f"[home_assistant]:{url_key}")
        url_layout.addWidget(url_label)
        url_layout.addWidget(url_field)
        instance_layout.addLayout(url_layout)
        
        # Token
        token_key = 'api_token' if instance_num == 1 else f'api_token_{instance_num}'
        token_layout = QHBoxLayout()
        token_label = QLabel("API Token:")
        token_label.setFixedWidth(100)
        token_field = QLineEdit()
        token_field.setEchoMode(QLineEdit.EchoMode.Password)
        token_field.setText(self.config.get('home_assistant', token_key, fallback=''))
        token_field.setPlaceholderText("Long-Lived Access Token")
        token_field.setObjectName(f"[home_assistant]:{token_key}")
        token_layout.addWidget(token_label)
        token_layout.addWidget(token_field)
        instance_layout.addLayout(token_layout)
        
        self.ha_instances_layout.addWidget(instance_frame)
    
    def add_new_ha_instance(self):
        """Aggiunge una nuova istanza Home Assistant."""
        if self.ha_instance_count >= 5:
            safe_print("⚠️ Massimo 5 istanze raggiunto")
            return
        
        self.ha_instance_count += 1
        self.add_ha_instance_fields(self.ha_instance_count)
        
        # Disabilita il pulsante se raggiunto il massimo
        if self.ha_instance_count >= 5:
            self.add_instance_btn.setEnabled(False)
    
    def remove_ha_instance(self, instance_frame):
        """Rimuove un'istanza Home Assistant."""
        instance_num = instance_frame.property("instance_num")
        
        # Rimuovi il frame dal layout
        self.ha_instances_layout.removeWidget(instance_frame)
        instance_frame.deleteLater()
        
        # Rimuovi i valori dal config
        url_key = f'url_{instance_num}'
        token_key = f'api_token_{instance_num}'
        
        if self.config.has_option('home_assistant', url_key):
            self.config.remove_option('home_assistant', url_key)
        if self.config.has_option('home_assistant', token_key):
            self.config.remove_option('home_assistant', token_key)
        
        # Riabilita il pulsante aggiungi
        self.add_instance_btn.setEnabled(True)
        
        safe_print(f"✓ Istanza {instance_num} rimossa")
    
    def create_beacon_section(self):
        """Crea la sezione BLE Beacons con possibilità di aggiungere/rimuovere beacon."""
        section_frame = QFrame()
        section_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(52, 73, 94, 0.6);
                border-radius: 12px;
                padding: 15px;
            }
        """)
        
        self.beacon_layout = QVBoxLayout(section_frame)
        self.beacon_layout.setSpacing(12)
        
        # Titolo sezione
        title_label = QLabel("📡 BLE Beacons")
        title_label.setObjectName("section_title")
        self.beacon_layout.addWidget(title_label)
        
        # Contenitore per i beacon
        self.beacons_layout = QVBoxLayout()
        self.beacons_layout.setSpacing(15)
        
        # Carica beacon esistenti da ble_entity.json
        self.beacon_count = 0
        ble_mapping = self.load_ble_mapping()
        if ble_mapping:
            for mac, area in ble_mapping.items():
                self.beacon_count += 1
                self.add_beacon_fields(self.beacon_count, mac, area)
        
        # Se non ci sono beacon, aggiungi almeno un campo vuoto
        if self.beacon_count == 0:
            self.beacon_count = 1
            self.add_beacon_fields(1, "", "")
        
        self.beacon_layout.addLayout(self.beacons_layout)
        
        # Pulsante Aggiungi Beacon
        add_beacon_btn_layout = QHBoxLayout()
        self.add_beacon_btn = QPushButton("➕ Aggiungi Beacon BLE")
        self.add_beacon_btn.clicked.connect(self.add_new_beacon)
        add_beacon_btn_layout.addStretch()
        add_beacon_btn_layout.addWidget(self.add_beacon_btn)
        add_beacon_btn_layout.addStretch()
        self.beacon_layout.addLayout(add_beacon_btn_layout)
        
        return section_frame
    
    def load_ble_mapping(self):
        """Carica la mappatura BLE da ble_entity.json."""
        base_path = get_base_path()
        ble_file = os.path.join(base_path, BLE_ENTITY_FILE)
        
        if not os.path.exists(ble_file):
            return {}
        
        try:
            with open(ble_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Estrai la mappatura (supporta sia formato vecchio che nuovo)
            if 'ble_mapping' in data:
                return data['ble_mapping']
            elif 'entities' in data:
                mapping = {}
                for entity in data['entities']:
                    if 'mac' in entity and 'area' in entity:
                        mapping[entity['mac']] = entity['area']
                return mapping
            return {}
        except Exception as e:
            safe_print(f"⚠️ Errore caricamento beacon: {e}")
            return {}
    
    def add_beacon_fields(self, beacon_num, mac="", area=""):
        """Aggiunge i campi per un beacon BLE."""
        beacon_frame = QFrame()
        beacon_frame.setProperty("beacon_num", beacon_num)
        beacon_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(41, 128, 185, 0.15);
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        beacon_layout = QVBoxLayout(beacon_frame)
        beacon_layout.setSpacing(10)
        
        # Header con numero beacon e bottone rimuovi
        header_layout = QHBoxLayout()
        header_label = QLabel(f"Beacon {beacon_num}")
        header_label.setStyleSheet("color: #3498db; font-weight: bold;")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        
        # Bottone rimuovi (solo se non è l'unico beacon)
        if self.beacon_count > 1 or (mac and area):
            remove_btn = QPushButton("🗑️ Rimuovi")
            remove_btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(231, 76, 60, 0.8);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 9pt;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: rgba(192, 57, 43, 0.9);
                }
            """)
            remove_btn.clicked.connect(lambda: self.remove_beacon(beacon_frame))
            header_layout.addStretch()
            header_layout.addWidget(remove_btn)
        
        beacon_layout.addLayout(header_layout)
        
        # Campo MAC Address
        mac_layout = QHBoxLayout()
        mac_label = QLabel("MAC Address:")
        mac_label.setFixedWidth(120)
        mac_layout.addWidget(mac_label)
        
        mac_input = QLineEdit()
        mac_input.setText(mac)
        mac_input.setPlaceholderText("AA:BB:CC:DD:EE:FF")
        mac_input.setObjectName(f"[beacon_{beacon_num}]:mac")
        mac_layout.addWidget(mac_input)
        beacon_layout.addLayout(mac_layout)
        
        # Campo Area ID
        area_layout = QHBoxLayout()
        area_label = QLabel("Area ID:")
        area_label.setFixedWidth(120)
        area_layout.addWidget(area_label)
        
        area_input = QLineEdit()
        area_input.setText(area)
        area_input.setPlaceholderText("bedroom, living_room, kitchen...")
        area_input.setObjectName(f"[beacon_{beacon_num}]:area")
        area_layout.addWidget(area_input)
        beacon_layout.addLayout(area_layout)
        
        self.beacons_layout.addWidget(beacon_frame)
    
    def add_new_beacon(self):
        """Aggiunge un nuovo beacon vuoto."""
        self.beacon_count += 1
        self.add_beacon_fields(self.beacon_count, "", "")
        safe_print(f"✓ Aggiunto campo per nuovo beacon {self.beacon_count}")
    
    def remove_beacon(self, beacon_frame):
        """Rimuove un beacon dalla UI e dalla configurazione."""
        beacon_num = beacon_frame.property("beacon_num")
        
        # Rimuovi il frame dalla UI
        beacon_frame.setParent(None)
        beacon_frame.deleteLater()
        
        # Decrementa il contatore se necessario
        if self.beacon_count > 1:
            self.beacon_count -= 1
        
        safe_print(f"✓ Beacon {beacon_num} rimosso")
    
    def save_ble_mapping(self):
        """Salva la mappatura BLE in ble_entity.json."""
        base_path = get_base_path()
        ble_file = os.path.join(base_path, BLE_ENTITY_FILE)
        
        # Raccogli tutti i beacon dai widget
        ble_mapping = {}
        for widget in self.findChildren(QWidget):
            obj_name = widget.objectName()
            if ':' in obj_name and 'beacon_' in obj_name:
                section, key = obj_name.split(':')
                beacon_num = section.strip('[]').replace('beacon_', '')
                
                if key == 'mac':
                    mac = widget.text().strip()
                    # Trova l'area corrispondente
                    area_widget = self.findChild(QWidget, f"[beacon_{beacon_num}]:area")
                    if area_widget and mac:
                        area = area_widget.text().strip()
                        if area:  # Salva solo se entrambi i campi sono compilati
                            ble_mapping[mac.upper()] = area
        
        # Salva in formato JSON
        try:
            data = {'ble_mapping': ble_mapping}
            with open(ble_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            safe_print(f"✓ Salvati {len(ble_mapping)} beacon in {BLE_ENTITY_FILE}")
        except Exception as e:
            safe_print(f"✗ Errore salvataggio beacon: {e}")
    
    def create_section(self, title, fields):
        """Crea una sezione di settings."""
        section_frame = QFrame()
        section_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(52, 73, 94, 0.6);
                border-radius: 12px;
                padding: 15px;
            }
        """)
        
        section_layout = QVBoxLayout(section_frame)
        section_layout.setSpacing(12)
        
        # Titolo sezione
        title_label = QLabel(title)
        title_label.setObjectName("section_title")
        section_layout.addWidget(title_label)
        
        # Campi
        for field_data in fields:
            label_text = field_data[0]
            key = field_data[1]
            field_type = field_data[2]
            section = field_data[3] if len(field_data) > 3 else "[home_assistant]"
            
            field_layout = QHBoxLayout()
            field_layout.setSpacing(10)
            
            label = QLabel(label_text)
            label.setFixedWidth(220)
            field_layout.addWidget(label)
            
            # Crea il widget appropriato
            if field_type == "bool":
                widget = QCheckBox()
                value = self.config.get(section.strip('[]'), key, fallback='false')
                widget.setChecked(value.lower() == 'true')
                widget.setObjectName(f"{section}:{key}")
            elif field_type == "number":
                widget = QSpinBox()
                widget.setRange(16, 128)
                value = self.config.get(section.strip('[]'), key, fallback='32')
                widget.setValue(int(value))
                widget.setObjectName(f"{section}:{key}")
            elif field_type == "password":
                widget = QLineEdit()
                widget.setEchoMode(QLineEdit.EchoMode.Password)
                value = self.config.get(section.strip('[]'), key, fallback='')
                widget.setText(value)
                widget.setObjectName(f"{section}:{key}")
            else:  # text
                widget = QLineEdit()
                value = self.config.get(section.strip('[]'), key, fallback='')
                widget.setText(value)
                widget.setObjectName(f"{section}:{key}")
            
            field_layout.addWidget(widget)
            section_layout.addLayout(field_layout)
        
        return section_frame
    
    def save_and_restart(self):
        """Salva le configurazioni e riavvia l'agent."""
        try:
            # Salva tutte le modifiche
            self.save_settings()
            
            # Messaggio di conferma
            safe_print("✓ Configurazione salvata! Riavvio agent...")
            
            # Chiudi la finestra
            self.close()
            
            # Riavvia l'applicazione
            QApplication.instance().quit()
            python = sys.executable
            os.execl(python, python, *sys.argv)
            
        except Exception as e:
            safe_print(f"✗ Errore salvataggio: {e}")
    
    def save_settings(self):
        """Salva i settings nel file config.ini e ble_entity.json."""
        saved_count = 0
        
        # Salva i beacon in ble_entity.json
        self.save_ble_mapping()
        
        # Trova tutti i widget con objectName impostato
        for widget in self.findChildren(QWidget):
            obj_name = widget.objectName()
            if ':' in obj_name:
                section, key = obj_name.split(':')
                section = section.strip('[]')
                
                # Salta i beacon (già salvati in ble_entity.json)
                if section.startswith('beacon_'):
                    continue
                
                # Ottieni il valore
                if isinstance(widget, QCheckBox):
                    value = 'true' if widget.isChecked() else 'false'
                elif isinstance(widget, QSpinBox):
                    value = str(widget.value())
                elif isinstance(widget, QLineEdit):
                    value = widget.text().strip()
                else:
                    continue
                
                # Salva nel config (anche se vuoto per le istanze HA opzionali)
                if not self.config.has_section(section):
                    self.config.add_section(section)
                
                # Salva sempre per le istanze HA, altrimenti solo se non vuoto
                if section == 'home_assistant' or value:
                    self.config.set(section, key, value)
                    saved_count += 1
                    safe_print(f"  → [{section}] {key} = {'***' if 'token' in key else value}")
        
        # Scrivi il file
        with open(self.config_file, 'w') as f:
            self.config.write(f)
        
        safe_print(f"✓ {saved_count} parametri salvati in {self.config_file}")

class HomeAssistantGUI(QWidget):
    """The main application window - Agent mode."""
    area_detected_signal = Signal(str)
    
    def __init__(self, ha_instances, agent_mode=False):
        super().__init__()
        self.agent_mode = agent_mode
        self.entities = []
        self.entity_widgets = []
        self.current_focus_index = 0
        self.image_provider = ImageProvider()
        self.current_area_id = None
        self.ble_scanner_thread = None
        self.stop_ble_scan = threading.Event()
        self.entities_loaded = False
        self.ble_mapping = None
        self.auto_hide_timer = None
        self.cleanup_timer = None
        self.is_scanning = False
        
        # Variabili per gestire connessione e riconnessione
        self.ha_instances = ha_instances  # Lista delle istanze configurate
        self.current_ha_url = HOME_ASSISTANT_URL
        self.current_ha_token = API_TOKEN
        self.current_headers = HEADERS.copy()
        
        # Variabili per drag-and-drop
        self.dragging = False
        self.drag_position = None
        
        # System tray icon per modalità agent
        self.tray_icon = None
        
        # Connetti il signal allo slot
        self.area_detected_signal.connect(self.update_area_entities)

        self.init_ui()
        
        # Crea system tray icon in modalità agent
        if agent_mode:
            self.create_system_tray()
        
        if not agent_mode:
            # Modalità normale: avvia subito la scansione
            self.start_ble_scanner()
        else:
            # Modalità agent: carica solo il mapping, la scansione parte con hotkey
            self.ble_mapping = carica_mappatura_ble()
            if not self.ble_mapping:
                logger.error("Nessun mapping BLE trovato")
            self.hide()  # Nascondi all'avvio in modalità agent

    def init_ui(self):
        self.setWindowTitle(APP_TITLE)
        
        # Imposta l'icona della finestra
        base_path = get_base_path()
        icon_path = os.path.join(base_path, 'Smart_Proximity_Control.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Attributi per migliorare il rendering della finestra frameless
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        
        # Stile moderno con gradiente e bordi arrotondati - sfondo opaco visibile
        self.setStyleSheet("""
            QWidget#MainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2c3e50, stop:1 #34495e);
                border-radius: 15px;
                border: 2px solid #1a252f;
            }
            QLabel {
                color: #ecf0f1;
                background: transparent;
            }
        """)
        
        # Rimuovi il bordo della finestra per look moderno
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        # Imposta il nome dell'oggetto per il CSS
        self.setObjectName("MainWindow")

        # Dimensioni iniziali più compatte
        self.setFixedSize(320, 220)

        self.main_layout = QVBoxLayout(self)
        # Use the correct enum access for PyQt6
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignCenter)
        self.main_layout.setSpacing(8)
        self.main_layout.setContentsMargins(12, 12, 12, 12)

        self.title_label = QLabel(APP_TITLE)
        self.title_label.setStyleSheet("""
            font-size: 12pt; 
            font-weight: bold; 
            color: #ecf0f1;
            background: transparent;
            padding: 3px;
        """)
        # Use the correct enum access for PyQt6
        self.main_layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Usa VBoxLayout per supportare righe multiple di entità
        self.entities_layout = QVBoxLayout()
        self.entities_layout.setSpacing(8)
        # Use the correct enum access for PyQt6
        self.entities_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.main_layout.addLayout(self.entities_layout)
        self.main_layout.addStretch()

        self.status_label = QLabel("Scanning for BLE devices...")
        self.status_label.setStyleSheet("""
            color: #95a5a6;
            font-size: 8pt;
            background: transparent;
        """)
        # Use the correct enum access for PyQt6
        self.main_layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # Layout orizzontale per quit label e powered by
        bottom_layout = QHBoxLayout()
        
        quit_label = QLabel(get_localized_string('quit_message', self.agent_mode))
        quit_label.setStyleSheet("""
            color: #7f8c8d;
            font-size: 7pt;
            background: transparent;
        """)
        
        powered_by_label = QLabel("powered by Guido Ballarini")
        powered_by_label.setStyleSheet("""
            color: #5a6c7d;
            font-size: 6pt;
            background: transparent;
            font-style: italic;
        """)
        
        bottom_layout.addWidget(quit_label, alignment=Qt.AlignmentFlag.AlignLeft)
        bottom_layout.addStretch()
        bottom_layout.addWidget(powered_by_label, alignment=Qt.AlignmentFlag.AlignRight)
        
        self.main_layout.addLayout(bottom_layout)

    def create_system_tray(self):
        """Crea l'icona nella system tray per la modalità agent."""
        base_path = get_base_path()
        icon_path = os.path.join(base_path, 'Smart_Proximity_Control.ico')
        
        logger.info(f"Creazione system tray icon. Path icona: {icon_path}")
        logger.info(f"Icona esiste: {os.path.exists(icon_path)}")
        
        if os.path.exists(icon_path):
            self.tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
            logger.info("Tray icon creata con Smart_Proximity_Control.ico")
        else:
            # Usa un'icona di default se non trova Smart_Proximity_Control.ico
            self.tray_icon = QSystemTrayIcon(self)
            logger.warning("Smart_Proximity_Control.ico non trovato, uso icona di default")
        
        # Crea menu contestuale
        tray_menu = QMenu()
        
        show_action = tray_menu.addAction("Mostra finestra")
        show_action.triggered.connect(self.show_and_scan)
        
        tray_menu.addSeparator()
        
        settings_action = tray_menu.addAction("⚙️ Settings")
        settings_action.triggered.connect(self.open_settings)
        
        tray_menu.addSeparator()
        
        quit_action = tray_menu.addAction("Esci")
        quit_action.triggered.connect(QApplication.instance().quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.setToolTip(APP_TITLE)
        
        # Doppio click sulla tray icon mostra la finestra
        self.tray_icon.activated.connect(self._on_tray_activated)
        
        # IMPORTANTE: mostra esplicitamente il tray icon
        self.tray_icon.show()
        self.tray_icon.setVisible(True)
        
        logger.info(f"System tray icon mostrata. Visible: {self.tray_icon.isVisible()}")
    
    def _on_tray_activated(self, reason):
        """Gestisce il click sull'icona del system tray."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_and_scan()
    
    def open_settings(self):
        """Apre la finestra di configurazione."""
        try:
            base_path = get_base_path()
            config_path = os.path.join(base_path, 'config.ini')
            self.settings_window = SettingsWindow(config_path)
            self.settings_window.show()
        except Exception as e:
            safe_print(f"✗ Errore apertura settings: {e}")
            logger.error(f"Errore apertura settings: {e}")
    
    def reconnect_to_available_instance(self):
        """Riconnette all'istanza Home Assistant disponibile.
        Ritorna True se ha trovato un'istanza disponibile, False altrimenti.
        """
        logger.info("Verifica disponibilità istanza Home Assistant...")
        
        # Usa detect_available_instance passando l'URL corrente
        new_url, new_token = detect_available_instance(self.ha_instances, self.current_ha_url)
        
        if new_url and new_token:
            # Controlla se l'istanza è cambiata
            if new_url != self.current_ha_url:
                logger.info(f"Cambio istanza: {self.current_ha_url} -> {new_url}")
                safe_print(f"Cambio istanza: {new_url}")
                
                # Aggiorna le variabili di istanza
                self.current_ha_url = new_url
                self.current_ha_token = new_token
                self.current_headers = {
                    "Authorization": f"Bearer {new_token}",
                    "Content-Type": "application/json",
                }
                
                # Aggiorna anche le variabili globali per compatibilità
                global HOME_ASSISTANT_URL, API_TOKEN, HEADERS
                HOME_ASSISTANT_URL = new_url
                API_TOKEN = new_token
                HEADERS = self.current_headers.copy()
                
                # Pulisce i dispositivi in memoria dato che l'istanza è cambiata
                self.clear_entities()
                self.entities_loaded = False
                self.current_area_id = None
            else:
                logger.info(f"Istanza corrente ancora disponibile: {new_url}")
            
            return True
        else:
            logger.error("Nessuna istanza Home Assistant disponibile")
            safe_print("✗ Nessuna istanza disponibile")
            return False

    def start_ble_scanner(self, single_scan=False):
        """Avvia lo scanner BLE in un thread separato.
        
        Args:
            single_scan: Se True, fa una sola scansione e poi si ferma
        """
        if self.is_scanning:
            logger.info("Scansione già in corso, ignoro richiesta")
            return
            
        # Carica o riusa il mapping
        if not self.ble_mapping:
            self.ble_mapping = carica_mappatura_ble()
            
        if not self.ble_mapping:
            self.status_label.setText("Error: No BLE mapping found")
            logger.error("Nessun mapping BLE trovato")
            return

        # Reset dello stato per nuova scansione
        if single_scan:
            self.entities_loaded = False
            self.current_area_id = None
            self.clear_entities()
            self.stop_ble_scan.clear()

        self.is_scanning = True
        # Avvia lo scanner BLE
        self.ble_scanner_thread = threading.Thread(
            target=run_ble_scanner, 
            args=(self.ble_mapping, self.on_area_detected, self.stop_ble_scan, single_scan), 
            daemon=True
        )
        self.ble_scanner_thread.start()
        self.status_label.setText("Scanning for BLE devices...")
    
    def show_and_scan(self):
        """Mostra la finestra e avvia una nuova scansione BLE."""
        safe_print("\\n>>> HOTKEY PREMUTA! Mostrando finestra...")
        logger.info("Hotkey attivata: mostro finestra e avvio scansione")
        
        # Cancella timer di auto-hide se esiste
        if self.auto_hide_timer:
            self.auto_hide_timer.stop()
            self.auto_hide_timer = None
        
        # Cancella timer di cleanup se esiste (finestra riaperta entro i 10 secondi)
        if self.cleanup_timer and self.cleanup_timer.isActive():
            logger.info("Timer di cleanup annullato: finestra riaperta entro 10 secondi")
            self.cleanup_timer.stop()
            self.cleanup_timer = None
        
        # Mostra la finestra
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        
        # Verifica connessione prima di usare i dispositivi in memoria
        if not self.reconnect_to_available_instance():
            self.status_label.setText("Error: No Home Assistant instance available")
            self.clear_entities()
            return
        
        # Verifica se ci sono dispositivi già caricati in memoria e l'istanza è la stessa
        if self.entity_widgets and self.entities_loaded:
            logger.info("Dispositivi ancora in memoria, riutilizzo senza scansione")
            safe_print(">>> Dispositivi in memoria: mostro senza scansionare")
            # I dispositivi sono già mostrati, non serve scansione
        else:
            # Nessun dispositivo in memoria, scansiona normalmente
            logger.info("Nessun dispositivo in memoria, avvio scansione")
            safe_print(">>> Finestra mostrata, avvio scansione BLE...")
            # Avvia scansione singola
            self.start_ble_scanner(single_scan=True)
        
        # Avvia timer per nascondere dopo 20 secondi
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.auto_hide)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.start(20000)  # 20 secondi
        safe_print(">>> Timer di 20 secondi avviato\\n")
        
    def auto_hide(self):
        """Nasconde automaticamente la finestra dopo il timeout."""
        logger.info("Timer scaduto: nascondo finestra")
        self.hide()
        self.auto_hide_timer = None
        
        # Avvia timer per pulire dispositivi dopo 10 secondi (solo se ci sono dispositivi)
        if self.entity_widgets:
            logger.info("Avvio timer di cleanup (10 secondi): dispositivi resteranno in memoria")
            self.cleanup_timer = QTimer(self)
            self.cleanup_timer.timeout.connect(self.cleanup_devices)
            self.cleanup_timer.setSingleShot(True)
            self.cleanup_timer.start(10000)  # 10 secondi
    
    def cleanup_devices(self):
        """Pulisce i dispositivi dalla memoria dopo 10 secondi dalla chiusura."""
        # Se la finestra è visibile, non cancellare (l'utente l'ha riaperta)
        if self.isVisible():
            logger.info("Cleanup annullato: finestra visibile")
            self.cleanup_timer = None
            return
        
        logger.info("Cleanup: cancello dispositivi dalla memoria")
        safe_print(">>> Cleanup: dispositivi rimossi dalla memoria")
        self.clear_entities()
        self.entities_loaded = False
        self.current_area_id = None
        self.status_label.setText("Scanning for BLE devices...")
        self.cleanup_timer = None
    
    def reset_auto_hide_timer(self):
        """Resetta il timer di auto-hide quando l'utente interagisce con la finestra."""
        if self.agent_mode and self.auto_hide_timer and self.auto_hide_timer.isActive():
            self.auto_hide_timer.stop()
            self.auto_hide_timer.start(10000)  # Resetta a 10 secondi
    
    def trigger_show_and_scan(self):
        """Wrapper thread-safe per show_and_scan chiamato dall'hotkey."""
        # Use QTimer.singleShot to invoke show_and_scan in the Qt main thread
        QTimer.singleShot(0, self.show_and_scan)
    
    def trigger_quit(self):
        """Wrapper thread-safe per chiudere l'applicazione dall'hotkey."""
        logger.info("Hotkey Ctrl+Shift+Q premuto: chiudo applicazione")
        safe_print("\n>>> Chiusura agent richiesta da hotkey...")
        # Use QTimer.singleShot to invoke quit in the Qt main thread
        QTimer.singleShot(0, QApplication.instance().quit)

    def on_area_detected(self, area_id):
        """Callback chiamata quando viene rilevato un dispositivo BLE."""
        logger.info(f"Callback on_area_detected chiamato con area_id: {area_id}")
        safe_print(f"Area ID detected: {area_id}")
        
        # Emetti il signal invece di usare QTimer
        self.area_detected_signal.emit(area_id)

    def update_area_entities(self, area_id):
        """Aggiorna le entità mostrate in base all'area rilevata."""
        logger.info(f"update_area_entities chiamato con area_id: {area_id}")
        logger.info(f"entities_loaded flag: {self.entities_loaded}")
        
        # Reset flag scansione (sempre, anche se area_id è None)
        self.is_scanning = False
        
        if area_id is None:
            self.clear_entities()
            self.status_label.setText("No BLE device detected")
            logger.warning("area_id è None - nessun dispositivo trovato")
            return
        
        if self.entities_loaded and self.current_area_id == area_id:
            logger.info("Entità già caricate per questa area, uscita")
            return

        self.current_area_id = area_id
        logger.info(f"Recupero informazioni area: {area_id}")
        
        # Prova a riconnettere se necessario
        if not self.reconnect_to_available_instance():
            self.status_label.setText("Error: No Home Assistant instance available")
            self.clear_entities()
            return
        
        area_info = get_area_info(area_id)
        area_name = area_info['name']
        logger.info(f"Nome area: {area_name}")
        
        self.status_label.setText(f"Area: {area_name} - Loading entities...")

        # Pulisci i widget esistenti
        self.clear_entities()

        # Carica le entità per questa area da Home Assistant
        entities = get_entities_for_area(area_id, ENTITY_DOMAINS)
        if not entities:
            self.status_label.setText(f"No entities found for area: {area_name}")
            logger.warning(f"Nessuna entità trovata per l'area: {area_name}")
            return

        safe_print(f"Found {len(entities)} entities for area {area_name}")
        
        # Raggruppa entità per dominio (tipo)
        entities_by_domain = {}
        for item in entities:
            domain = item['entity_id'].split('.')[0]
            if domain not in entities_by_domain:
                entities_by_domain[domain] = []
            entities_by_domain[domain].append(item)
        
        # Mappa nomi domini in etichette leggibili
        domain_labels = {
            'light': '💡 Lights',
            'switch': '🔌 Switches',
            'scene': '🎬 Scenes',
            'script': '📜 Scripts',
            'cover': '🪟 Covers',
            'fan': '🌀 Fans',
            'climate': '🌡️ Climate',
            'media_player': '📺 Media',
        }
        
        # Crea una riga (HBoxLayout) per ogni tipo di entità
        for domain, domain_entities in entities_by_domain.items():
            # Container per la riga completa (label + entità)
            row_container = QVBoxLayout()
            row_container.setSpacing(4)
            
            # Etichetta del tipo
            type_label = QLabel(domain_labels.get(domain, domain.capitalize()))
            type_label.setStyleSheet("""
                color: #95a5a6;
                font-size: 7pt;
                font-weight: bold;
                background: transparent;
                padding: 2px;
            """)
            type_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row_container.addWidget(type_label)
            
            # Layout orizzontale per le entità
            row_layout = QHBoxLayout()
            row_layout.setSpacing(10)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            for item in domain_entities:
                widget = EntityWidget(item, self.image_provider)
                self.entity_widgets.append(widget)
                row_layout.addWidget(widget)
            
            row_container.addLayout(row_layout)
            self.entities_layout.addLayout(row_container)

        # Aggiorna lo stato iniziale
        if self.entity_widgets:
            self.entity_widgets[0].setFocus()
            self.current_focus_index = 0
            self.update_focus_highlight()
            
            # Fetch initial state for all widgets
            for widget in self.entity_widgets:
                widget.start_loading_animation()
                # Usa un thread separato per non bloccare l'UI
                threading.Thread(
                    target=self._load_initial_state, 
                    args=(widget,), 
                    daemon=True
                ).start()

        # Segna che le entità sono state caricate e ferma la scansione BLE
        self.entities_loaded = True
        self.stop_ble_scan.set()
        self.status_label.setText(f"Area: {area_name} - Ready")
        
        # Ridimensiona la finestra in base al layout delle entità
        if self.entity_widgets:
            # Calcola il numero massimo di entità in una riga
            max_entities_per_row = 0
            num_rows = self.entities_layout.count()
            
            for i in range(num_rows):
                row_container = self.entities_layout.itemAt(i).layout()
                if row_container and row_container.count() > 1:
                    # Il secondo elemento è l'HBoxLayout con le entità
                    entities_layout = row_container.itemAt(1).layout()
                    if entities_layout:
                        max_entities_per_row = max(max_entities_per_row, entities_layout.count())
            
            # Larghezza: basata sulla riga più lunga
            new_width = min(600, max(320, (ICON_SIZE + 32) * max_entities_per_row + 100))
            # Altezza: basata sul numero di righe (label + icone)
            base_height = 180
            row_height = ICON_SIZE + 35  # Spazio per label + icone
            new_height = min(500, base_height + (row_height * num_rows))
            self.setFixedSize(new_width, new_height)
        
        # Centra la finestra sullo schermo
        self.center_on_screen()

        # Avvia gli aggiornamenti in background
        self.start_background_updates()

    def _load_initial_state(self, widget):
        """Carica lo stato iniziale di un widget in un thread separato."""
        initial_state = get_stato_entita(widget.entity_id)
        if initial_state:
            QApplication.instance().postEvent(widget, StateUpdateEvent(initial_state))

    def clear_entities(self):
        """Pulisce tutte le entità dalla GUI."""
        # Rimuovi tutti i widget
        for widget in self.entity_widgets:
            widget.deleteLater()
        self.entity_widgets.clear()
        
        # Rimuovi tutti i layout figli (i container delle righe)
        while self.entities_layout.count():
            row_container = self.entities_layout.takeAt(0)
            if row_container.layout():
                # È un VBoxLayout (container riga), rimuovi label e layout entità
                while row_container.layout().count():
                    child = row_container.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
                    elif child.layout():
                        # È l'HBoxLayout con le entità
                        while child.layout().count():
                            child.layout().takeAt(0)
                        child.layout().deleteLater()
                row_container.layout().deleteLater()

    def start_background_updates(self):
        """Avvia gli aggiornamenti periodici dello stato."""
        self.update_thread = threading.Thread(target=self._update_states_loop, daemon=True)
        self.update_thread.start()

    def _update_states_loop(self):
        while True:
            for widget in self.entity_widgets:
                if not widget.is_loading:
                    state_data = get_stato_entita(widget.entity_id)
                    if state_data:
                        # We need to update GUI from the main thread
                        QApplication.instance().postEvent(widget, StateUpdateEvent(state_data))
            time.sleep(5)

    def _toggle_and_update(self, item):
        entity_id = item['entity_id']
        domain = entity_id.split('.')[0]

        # Use an index to find the widget quickly
        widget = next((w for w in self.entity_widgets if w.entity_id == entity_id), None)
        if not widget: return

        if domain == 'cover':
            state_data = get_stato_entita(entity_id)
            if not state_data: 
                widget.stop_loading_animation()
                return

            current_pos = state_data.get('attributes', {}).get('current_position', 0)
            min_pos = item.get('min_position', 0)
            max_pos = item.get('max_position', 100)

            # Determine whether to open (max) or close (min)
            if abs(current_pos - min_pos) < abs(current_pos - max_pos):
                logger.info(f"Action: Setting cover '{entity_id}' to position {max_pos}.")
                set_cover_position(entity_id, max_pos)
            else:
                logger.info(f"Action: Setting cover '{entity_id}' to position {min_pos}.")
                set_cover_position(entity_id, min_pos)
        else:
            logger.info(f"Action: Toggling entity '{entity_id}'.")
            toggle_entita(entity_id)

        # Give HA a moment to process the command
        time.sleep(1)
        
        # Get the new state and update the GUI
        state_data = get_stato_entita(entity_id)
        if state_data:
            QApplication.instance().postEvent(widget, StateUpdateEvent(state_data))
        else:
            # If update fails, stop loading anyway
            widget.stop_loading_animation()

    def center_on_screen(self):
        """Centra la finestra sullo schermo."""
        screen = QApplication.primaryScreen().geometry()
        window_geometry = self.frameGeometry()
        center_point = screen.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())
    
    def keyPressEvent(self, event):
        # Resetta timer ad ogni interazione
        self.reset_auto_hide_timer()
        
        key = event.key()
        # Use the correct enum access for PyQt6
        if key == Qt.Key.Key_Escape:
            if self.agent_mode:
                # In modalità agent, ESC nasconde la finestra usando hide() direttamente
                logger.info("ESC premuto: nascondo finestra")
                if self.auto_hide_timer:
                    self.auto_hide_timer.stop()
                    self.auto_hide_timer = None
                self.hide()  # Nascondi direttamente senza chiamare close()
                # Avvia timer di cleanup
                if self.entity_widgets:
                    logger.info("Avvio timer di cleanup (10 secondi)")
                    if self.cleanup_timer:
                        self.cleanup_timer.stop()
                    self.cleanup_timer = QTimer(self)
                    self.cleanup_timer.timeout.connect(self.cleanup_devices)
                    self.cleanup_timer.setSingleShot(True)
                    self.cleanup_timer.start(10000)
            else:
                # In modalità normale, ESC chiude l'applicazione
                QApplication.instance().quit()
        elif key == Qt.Key.Key_Right:
            self.navigate(1)
        elif key == Qt.Key.Key_Left:
            self.navigate(-1)
        elif key == Qt.Key.Key_Space or key == Qt.Key.Key_Return: # Added Enter/Return key
            self.activate_current_widget()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Resetta timer ad ogni interazione
        self.reset_auto_hide_timer()
        
        if event.button() == Qt.MouseButton.LeftButton:
            widget = self.childAt(event.pos())
            # Traverse up to find the EntityWidget if clicked on a child (like QLabel)
            while widget is not None and not isinstance(widget, EntityWidget):
                widget = widget.parent()
                
            if isinstance(widget, EntityWidget):
                try:
                    self.current_focus_index = self.entity_widgets.index(widget)
                    self.update_focus_highlight()
                    self.activate_current_widget()
                except ValueError:
                    # Should not happen if logic is correct
                    pass
            else:
                # Click su area vuota: inizia drag della finestra
                self.dragging = True
                # Salva dimensioni correnti e rimuovi vincoli fissi
                self.saved_size = self.size()
                self.setMinimumSize(0, 0)
                self.setMaximumSize(16777215, 16777215)
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
        else:
            super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Sposta la finestra durante il drag."""
        # Resetta timer ad ogni interazione
        self.reset_auto_hide_timer()
        
        if self.dragging and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """Termina il drag della finestra."""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.dragging:
                self.dragging = False
                # Riabilita layout e aggiornamenti
                self.main_layout.setEnabled(True)
                self.setUpdatesEnabled(True)
                self.update()
            event.accept()

    def navigate(self, direction):
        if not self.entity_widgets: return
        self.current_focus_index = (self.current_focus_index + direction) % len(self.entity_widgets)
        self.entity_widgets[self.current_focus_index].setFocus()
        self.update_focus_highlight()

    def activate_current_widget(self):
        if self.entity_widgets:
            widget = self.entity_widgets[self.current_focus_index]
            if not widget.is_loading:
                widget.start_loading_animation()
                threading.Thread(target=self._toggle_and_update, args=(widget.item,), daemon=True).start()

    def update_focus_highlight(self):
        for i, widget in enumerate(self.entity_widgets):
            is_focused = (i == self.current_focus_index)
            # Enable shadow on focus, disable otherwise
            widget.shadow.setEnabled(is_focused)
    
    def closeEvent(self, event):
        """Gestisce la chiusura della finestra (click su X)."""
        if self.agent_mode:
            # In modalità agent, nasconde invece di chiudere
            logger.info("closeEvent: nascondo finestra invece di chiudere")
            event.ignore()
            self.hide()
            if self.tray_icon:
                self.tray_icon.showMessage(
                    APP_TITLE,
                    "L'applicazione continua in background. Usa Ctrl+Shift+Space per mostrarla.",
                    QSystemTrayIcon.MessageIcon.Information,
                    2000
                )
            # Avvia timer di cleanup
            if self.entity_widgets:
                logger.info("Avvio timer di cleanup (10 secondi) da closeEvent")
                if self.cleanup_timer:
                    self.cleanup_timer.stop()
                self.cleanup_timer = QTimer(self)
                self.cleanup_timer.timeout.connect(self.cleanup_devices)
                self.cleanup_timer.setSingleShot(True)
                self.cleanup_timer.start(10000)
        else:
            # In modalità normale, chiude l'applicazione
            event.accept()
            QApplication.instance().quit()


class StateUpdateEvent(QEvent):
    """A custom event to carry state update data."""
    # QEvent.User is defined as 1000. Use a value higher than that.
    EVENT_TYPE = QEvent.Type(QEvent.Type.User + 1) 

    def __init__(self, state_data):
        super().__init__(StateUpdateEvent.EVENT_TYPE)
        self.setAccepted(False)
        self.state_data = state_data

    # This method is optional in PyQt6 but good practice for clarity
    def type(self):
        return StateUpdateEvent.EVENT_TYPE

def get_localized_string(key, agent_mode=False):
    """Returns a localized string based on the OS language."""
    translations = {
        'quit_message': {
            'it': 'Premere ESC per nascondere' if agent_mode else 'Premere ESC per uscire',
            'en': 'Press ESC to hide' if agent_mode else 'Press ESC to exit',
        }
    }
    try:
        # Get the preferred locale language code
        lang, _ = locale.getlocale()
        lang_short = lang.split('_')[0] if lang else 'en'
    except (ValueError, TypeError):
        # Fallback in case getlocale() returns something unexpected
        lang_short = 'en'
        
    return translations.get(key, {}).get(lang_short, translations.get(key, {}).get('en', 'Press ESC to exit'))

def cleanup():
    """Pulizia risorse prima dell'uscita."""
    try:
        if 'logger' in globals():
            logger.info("Chiusura applicazione...")
        if 'main_window' in globals():
            if hasattr(main_window, 'stop_ble_scan'):
                main_window.stop_ble_scan.set()
            if hasattr(main_window, 'ble_scanner_thread') and main_window.ble_scanner_thread:
                main_window.ble_scanner_thread.join(timeout=2)
        if 'logger' in globals():
            logger.info("Risorse rilasciate correttamente")
    except Exception as e:
        if 'logger' in globals():
            logger.error(f"Errore durante il cleanup: {e}")

if __name__ == "__main__":
    # Controlla se è richiesta la lista delle aree
    if len(sys.argv) > 1 and sys.argv[1] in ['--list-areas', '-l', 'areas']:
        # Carica solo la configurazione minima
        base_path = get_base_path()
        config_path = os.path.join(base_path, 'config.ini')
        config = configparser.ConfigParser()
        if os.path.exists(config_path):
            config.read(config_path)
            try:
                # Carica tutte le istanze
                ha_instances = []
                ha_url = config.get('home_assistant', 'url')
                ha_token = config.get('home_assistant', 'api_token')
                ha_instances.append({'url': ha_url, 'token': ha_token})
                
                # Aggiungi istanze opzionali
                for i in range(2, 6):
                    try:
                        url = config.get('home_assistant', f'url_{i}')
                        token = config.get('home_assistant', f'api_token_{i}')
                        if url and token:
                            ha_instances.append({'url': url, 'token': token})
                    except (configparser.NoOptionError, configparser.NoSectionError):
                        pass
                
                # Rileva istanza disponibile
                active_url, active_token = detect_available_instance(ha_instances, current_url=None)
                if active_url and active_token:
                    get_area_ids(active_url, active_token)
                else:
                    safe_print("Nessuna istanza Home Assistant disponibile!")
            except (configparser.NoSectionError, configparser.NoOptionError) as e:
                safe_print(f"Errore configurazione: {e}")
                safe_print("Assicurati che config.ini contenga [home_assistant] con 'url' e 'api_token'")
        else:
            safe_print("File config.ini non trovato!")
        sys.exit(0)
    
    # Controlla se deve essere eseguito in modalità agent
    agent_mode = len(sys.argv) > 1 and sys.argv[1] in ['--agent', '-a', 'agent']
    
    # Ensure single instance
    if not singleton():
        sys.exit(1) # Use exit code 1 to indicate error/already running
    
    # These variables need to be available to the whole script
    global HOME_ASSISTANT_URL, API_TOKEN, APP_TITLE, ICON_SIZE, SHOW_TOOLTIPS, ENTITY_DOMAINS, HEADERS, logger, SOUNDS_ENABLED

    # Setup logging first
    logger = setup_logging()
    if agent_mode:
        logger.info("=== Avvio Hapy in modalità AGENT ===")
        safe_print("\\n" + "="*60)
        safe_print("  HAPY AGENT MODE ATTIVO")
        safe_print("="*60)
        safe_print("  Ctrl+Shift+Space: Mostra finestra")
        safe_print("  Ctrl+Shift+Q: Chiudi agent")
        safe_print("  ESC: Nascondi finestra")
        safe_print("  Timer: 10 secondi (si resetta ad ogni interazione)")
        safe_print("="*60 + "\\n")
    else:
        logger.info("=== Avvio Hapy ===")

    # Load configuration and exit if it fails
    ha_instances, APP_TITLE, ICON_SIZE, SHOW_TOOLTIPS, ENTITY_DOMAINS, VOICE_CONFIG, ENABLE_SOUNDS = carica_configurazione('config.ini')
    if not ha_instances:
        logger.error("Configurazione non valida, uscita")
        sys.exit(1)
    
    # Imposta la variabile globale per i suoni
    SOUNDS_ENABLED = ENABLE_SOUNDS
    
    # Detect which Home Assistant instance is available
    HOME_ASSISTANT_URL, API_TOKEN = detect_available_instance(ha_instances, current_url=None)
    
    # In agent mode, continua anche senza connessione HA (lazy connect)
    if not HOME_ASSISTANT_URL or not API_TOKEN:
        if agent_mode:
            logger.warning("Nessuna istanza di Home Assistant disponibile, continuo in modalità agent (lazy connect)")
            safe_print("⚠️  Home Assistant non raggiungibile, riproverò quando invocato")
            HOME_ASSISTANT_URL = None
            API_TOKEN = None
        else:
            logger.error("Nessuna istanza di Home Assistant disponibile, uscita")
            sys.exit(1)
    else:
        logger.info(f"Connesso a Home Assistant: {HOME_ASSISTANT_URL}")
    
    logger.info(f"Domini entità da filtrare: {', '.join(ENTITY_DOMAINS)}")

    # These globals are now set only when the script is executed directly,
    # and only after we've confirmed the config files are valid.
    if API_TOKEN:
        HEADERS = {
            "Authorization": f"Bearer {API_TOKEN}",
            "Content-Type": "application/json",
        }
    else:
        HEADERS = None
    
    # Registra funzione di cleanup
    atexit.register(cleanup)
    
    # Inizializza Voice Control Agent (solo in modalità agent)
    voice_agent = None
    
    if agent_mode and VOICE_CONFIG.get('enabled', False):
        safe_print("[DEBUG] Inizializzazione Voice Control Agent...")
        try:
            # Carica mappatura BLE per voice control
            ble_mapping = load_voice_ble_mapping()
            safe_print(f"[DEBUG] BLE mapping caricato: {ble_mapping is not None}")
            
            voice_agent = VoiceControlAgent(
                ha_instances=ha_instances,  # Passa la lista di istanze per lazy connect
                ble_mapping=ble_mapping,
                entity_domains=VOICE_CONFIG.get('entity_domains', ['light']),
                hotkey=VOICE_CONFIG.get('hotkey', 'ctrl+shift+i'),
                group_lights_control=VOICE_CONFIG.get('group_lights_control', False)
            )
            safe_print(f"[DEBUG] VoiceControlAgent creato: {voice_agent}")
            safe_print(f"  {VOICE_CONFIG.get('hotkey', 'ctrl+shift+i').upper()}: Comando vocale")
            logger.info("Voice Control Agent configurato")
        except Exception as e:
            import traceback
            logger.error(f"Errore inizializzazione Voice Control: {e}")
            safe_print(f"⚠️  Voice Control non disponibile: {e}")
            safe_print(f"[DEBUG] Traceback: {traceback.format_exc()}")
    elif agent_mode:
        safe_print(f"[DEBUG] Voice Control non avviato: enabled={VOICE_CONFIG.get('enabled', False)}")

    # Run the application
    q_app = QApplication(sys.argv)
    
    # Set the application name for better OS integration
    q_app.setApplicationName(APP_TITLE)
    
    main_window = HomeAssistantGUI(ha_instances, agent_mode=agent_mode)
    
    if agent_mode:
        # In modalità agent, registra hotkey globali (configurabili da config.ini)
        show_hotkey = VOICE_CONFIG.get('show_hotkey', 'ctrl+shift+space')
        quit_hotkey = VOICE_CONFIG.get('quit_hotkey', 'ctrl+shift+q')
        try:
            keyboard.add_hotkey(show_hotkey, main_window.trigger_show_and_scan, suppress=True)
            keyboard.add_hotkey(quit_hotkey, main_window.trigger_quit, suppress=True)
            logger.info(f"Hotkey {show_hotkey} e {quit_hotkey} registrate correttamente")
            if sys.stdout:
                safe_print(f"✓ Hotkey registrate: {show_hotkey.upper()}, {quit_hotkey.upper()}")
                sys.stdout.flush()
        except Exception as e:
            logger.error(f"Errore registrazione hotkey: {e}")
            if sys.stdout:
                safe_print(f"\n✗ ERRORE: Impossibile registrare hotkey: {e}")
                safe_print("  L'applicazione potrebbe richiedere privilegi di amministratore.")
                safe_print("  Su Windows, esegui come Amministratore.\n")
                sys.stdout.flush()
        
        # Avvia Voice Control Agent se configurato
        safe_print(f"[DEBUG] voice_agent={voice_agent}")
        if voice_agent:
            safe_print("[DEBUG] Chiamata voice_agent.start()...")
            result = voice_agent.start()
            safe_print(f"[DEBUG] voice_agent.start() returned: {result}")
            if result:
                logger.info("Voice Control Agent avviato correttamente")
                safe_print("✓ Voice Control Agent avviato!")
            else:
                logger.warning("Voice Control Agent non avviato")
                safe_print("⚠️ Voice Control Agent non avviato")
        else:
            safe_print("[DEBUG] voice_agent è None, Voice Control non disponibile")
        
        safe_print("  In attesa dei comandi...")
    else:
        # In modalità normale, mostra la finestra subito
        main_window.show()
    
    logger.info("GUI avviata")
    exit_code = q_app.exec()
    
    # Cleanup hotkey
    if agent_mode:
        try:
            keyboard.remove_hotkey(show_hotkey)
            keyboard.remove_hotkey(quit_hotkey)
        except:
            pass
        
        # Ferma Voice Control Agent
        if voice_agent:
            voice_agent.stop()
    
    logger.info(f"=== Chiusura Hapy (exit code: {exit_code}) ===")
    sys.exit(exit_code)

