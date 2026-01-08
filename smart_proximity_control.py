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

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, 
    QFrame, QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu
)
from PyQt6.QtGui import QPixmap, QImage, QPainter, QTransform, QCursor, QIcon
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import (
    Qt, QThread, QObject, QTimer, QEvent, pyqtSignal as Signal
)

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
        return None, None, None, None, None

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
            return None, None, None, None, None
        
        if len(ha_token) < 50:
            safe_print(f"Error: API token seems too short. Make sure you're using a Long-Lived Access Token.")
            return None, None, None, None, None
        
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
        
        return ha_instances, app_title, icon_size, show_tooltips, entity_domains_list
    except (configparser.NoSectionError, configparser.NoOptionError) as e:
        safe_print(f"Error: The configuration file '{file_path}' is invalid.")
        safe_print(f"Make sure it contains a [home_assistant] section with 'url' and 'api_token' keys.")
        safe_print(f"Error details: {e}")
        safe_print("\nPlease refer to README.md for configuration instructions.")
        return None, None, None, None, None

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
        icon_path = os.path.join(base_path, 'logo_gb.ico')
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
        icon_path = os.path.join(base_path, 'logo_gb.ico')
        
        logger.info(f"Creazione system tray icon. Path icona: {icon_path}")
        logger.info(f"Icona esiste: {os.path.exists(icon_path)}")
        
        if os.path.exists(icon_path):
            self.tray_icon = QSystemTrayIcon(QIcon(icon_path), self)
            logger.info("Tray icon creata con logo_gb.ico")
        else:
            # Usa un'icona di default se non trova logo_gb.ico
            self.tray_icon = QSystemTrayIcon(self)
            logger.warning("logo_gb.ico non trovato, uso icona di default")
        
        # Crea menu contestuale
        tray_menu = QMenu()
        
        show_action = tray_menu.addAction("Mostra finestra")
        show_action.triggered.connect(self.show_and_scan)
        
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
        
        # Avvia timer per nascondere dopo 10 secondi
        self.auto_hide_timer = QTimer(self)
        self.auto_hide_timer.timeout.connect(self.auto_hide)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.start(10000)  # 10 secondi
        safe_print(">>> Timer di 10 secondi avviato\\n")
        
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
    global HOME_ASSISTANT_URL, API_TOKEN, APP_TITLE, ICON_SIZE, SHOW_TOOLTIPS, ENTITY_DOMAINS, HEADERS, logger

    # Setup logging first
    logger = setup_logging()
    if agent_mode:
        logger.info("=== Avvio Hapy in modalità AGENT ===")
        safe_print("\\n" + "="*60)
        safe_print("  HAPY AGENT MODE ATTIVO")
        safe_print("="*60)
        safe_print("  Ctrl+Shift+Space: Mostra finestra")
        safe_print("  Ctrl+Shift+E: Chiudi agent")
        safe_print("  ESC: Nascondi finestra")
        safe_print("  Timer: 10 secondi (si resetta ad ogni interazione)")
        safe_print("="*60 + "\\n")
    else:
        logger.info("=== Avvio Hapy ===")

    # Load configuration and exit if it fails
    ha_instances, APP_TITLE, ICON_SIZE, SHOW_TOOLTIPS, ENTITY_DOMAINS = carica_configurazione('config.ini')
    if not ha_instances:
        logger.error("Configurazione non valida, uscita")
        sys.exit(1)
    
    # Detect which Home Assistant instance is available
    HOME_ASSISTANT_URL, API_TOKEN = detect_available_instance(ha_instances, current_url=None)
    if not HOME_ASSISTANT_URL or not API_TOKEN:
        logger.error("Nessuna istanza di Home Assistant disponibile, uscita")
        sys.exit(1)
    
    logger.info(f"Connesso a Home Assistant: {HOME_ASSISTANT_URL}")
    logger.info(f"Domini entità da filtrare: {', '.join(ENTITY_DOMAINS)}")

    # These globals are now set only when the script is executed directly,
    # and only after we've confirmed the config files are valid.
    HEADERS = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
    }
    
    # Registra funzione di cleanup
    atexit.register(cleanup)

    # Run the application
    q_app = QApplication(sys.argv)
    
    # Set the application name for better OS integration
    q_app.setApplicationName(APP_TITLE)
    
    main_window = HomeAssistantGUI(ha_instances, agent_mode=agent_mode)
    
    if agent_mode:
        # In modalità agent, registra hotkey globali
        try:
            keyboard.add_hotkey('ctrl+shift+space', main_window.trigger_show_and_scan, suppress=True)
            keyboard.add_hotkey('ctrl+shift+q', main_window.trigger_quit, suppress=True)
            logger.info("Hotkey Ctrl+Shift+Space e Ctrl+Shift+Q registrate correttamente")
            if sys.stdout:
                safe_print("✓ Hotkey registrate correttamente!")
                safe_print("  In attesa dei comandi...")
                sys.stdout.flush()
        except Exception as e:
            logger.error(f"Errore registrazione hotkey: {e}")
            if sys.stdout:
                safe_print(f"\n✗ ERRORE: Impossibile registrare hotkey: {e}")
                safe_print("  L'applicazione potrebbe richiedere privilegi di amministratore.")
                safe_print("  Su Windows, esegui come Amministratore.\n")
                sys.stdout.flush()
    else:
        # In modalità normale, mostra la finestra subito
        main_window.show()
    
    logger.info("GUI avviata")
    exit_code = q_app.exec()
    
    # Cleanup hotkey
    if agent_mode:
        try:
            keyboard.remove_hotkey('ctrl+shift+space')
            keyboard.remove_hotkey('ctrl+shift+q')
        except:
            pass
    
    logger.info(f"=== Chiusura Hapy (exit code: {exit_code}) ===")
    sys.exit(exit_code)

