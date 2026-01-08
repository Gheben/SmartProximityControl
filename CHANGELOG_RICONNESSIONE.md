# Changelog - Riconnessione Automatica

## Problema Risolto

Quando l'applicazione era aperta nella system tray e l'utente si spostava in un'altra rete WiFi con un'altra istanza di Home Assistant:
- L'app identificava correttamente la nuova zona tramite BLE
- Ma NON mostrava le entità perché continuava a cercare di connettersi all'istanza della vecchia rete
- Dai log si vedeva che tentava ancora di collegarsi all'istanza non più raggiungibile

## Modifiche Implementate

### 1. Rilevamento Intelligente dell'Istanza Disponibile

**File modificato:** `smart_proximity_control.py`

#### Funzione `detect_available_instance()` Migliorata
```python
def detect_available_instance(ha_instances, current_url=None):
```

**Cosa fa:**
- Se viene passato `current_url`, testa prima l'istanza corrente con un timeout rapido (2 secondi)
- Se l'istanza corrente è ancora disponibile, la riutilizza immediatamente
- Se l'istanza corrente non risponde, testa le altre istanze configurate
- Questo rende la riconnessione molto più veloce quando l'istanza non è cambiata

### 2. Gestione Dinamica della Connessione nella GUI

#### Nuovo Metodo `reconnect_to_available_instance()`
```python
def reconnect_to_available_instance(self):
```

**Cosa fa:**
- Verifica se l'istanza corrente è ancora disponibile
- Se non lo è, cerca automaticamente un'altra istanza disponibile
- Quando trova una nuova istanza:
  - Aggiorna `self.current_ha_url` e `self.current_ha_token`
  - Aggiorna le variabili globali per compatibilità
  - **Pulisce i dispositivi in memoria** (perché appartengono all'istanza precedente)
  - Logga il cambio istanza
- Ritorna `True` se trova un'istanza disponibile, `False` altrimenti

### 3. Integrazione nella Logica Esistente

#### Modifiche a `update_area_entities()`
```python
# Prova a riconnettere se necessario
if not self.reconnect_to_available_instance():
    self.status_label.setText("Error: No Home Assistant instance available")
    self.clear_entities()
    return
```

**Quando viene chiamato:**
- Ogni volta che viene rilevata un'area tramite BLE
- Prima di caricare le entità da Home Assistant
- Garantisce che la connessione sia valida prima di procedere

#### Modifiche a `show_and_scan()`
```python
# Verifica connessione prima di usare i dispositivi in memoria
if not self.reconnect_to_available_instance():
    self.status_label.setText("Error: No Home Assistant instance available")
    self.clear_entities()
    return
```

**Quando viene chiamato:**
- Quando l'utente preme la hotkey Ctrl+Shift+Space
- Quando l'utente fa doppio click sulla tray icon
- Prima di mostrare i dispositivi in memoria
- Garantisce che i dispositivi mostrati siano validi per l'istanza corrente

### 4. Variabili di Istanza per Tracciare lo Stato

Nel costruttore `__init__()`:
```python
# Variabili per gestire connessione e riconnessione
self.ha_instances = ha_instances  # Lista delle istanze configurate
self.current_ha_url = HOME_ASSISTANT_URL
self.current_ha_token = API_TOKEN
self.current_headers = HEADERS.copy()
```

**Perché:**
- Permette alla GUI di gestire autonomamente la connessione
- Non dipende più solo dalle variabili globali
- Può cambiare istanza dinamicamente senza riavviare l'app

## Come Funziona in Pratica

### Scenario 1: Stesso Palazzo, Stessa Rete
1. Premi Ctrl+Shift+Space
2. `reconnect_to_available_instance()` verifica l'istanza corrente (2 secondi)
3. L'istanza risponde → riutilizza la connessione esistente
4. Mostra i dispositivi in memoria (se presenti) o scansiona
5. **Tempo totale: ~2 secondi**

### Scenario 2: Cambio Palazzo, Cambio Rete
1. Premi Ctrl+Shift+Space
2. `reconnect_to_available_instance()` verifica l'istanza corrente (2 secondi timeout)
3. L'istanza non risponde → cerca altre istanze
4. Trova la nuova istanza disponibile
5. **Pulisce i dispositivi in memoria** (appartenevano all'istanza precedente)
6. Logga: "Cambio istanza: http://10.10.10.106:8123 -> http://192.168.1.100:8123"
7. Avvia scansione BLE per rilevare la nuova area
8. Carica le entità dalla nuova istanza
9. **Tempo totale: ~5-7 secondi**

### Scenario 3: Nessuna Istanza Disponibile
1. Premi Ctrl+Shift+Space
2. `reconnect_to_available_instance()` testa tutte le istanze
3. Nessuna risponde
4. Mostra messaggio: "Error: No Home Assistant instance available"
5. Pulisce i dispositivi
6. L'app rimane aperta e puoi riprovare

## Configurazione Necessaria

Nel file `config.ini`, aggiungi tutte le tue istanze di Home Assistant:

```ini
[home_assistant]
# Istanza primaria (casa)
url = http://10.10.10.106:8123
api_token = your_home_token

# Istanza secondaria (ufficio)
url_2 = http://192.168.1.100:8123
api_token_2 = your_office_token

# Istanza terziaria (opzionale)
url_3 = http://another-ip:8123
api_token_3 = another_token
```

L'app testerà automaticamente tutte le istanze e si connetterà alla prima disponibile.

## Vantaggi della Soluzione

✅ **Riconnessione Automatica**: Non serve riavviare l'app quando cambi rete
✅ **Veloce**: Timeout rapido (2 secondi) per l'istanza corrente
✅ **Trasparente**: L'utente non si accorge del cambio istanza
✅ **Robusto**: Gestisce correttamente il caso in cui nessuna istanza è disponibile
✅ **Pulito**: Cancella automaticamente i dispositivi dell'istanza precedente
✅ **Logging Completo**: Tutti i cambi istanza sono loggati per debug

## Test Consigliati

1. **Test Riconnessione Veloce**
   - Avvia l'app in modalità agent
   - Premi Ctrl+Shift+Space
   - Verifica che carichi rapidamente (2 secondi)

2. **Test Cambio Rete**
   - Avvia l'app connessa a una rete
   - Cambia rete WiFi (o disconnetti/riconnetti)
   - Premi Ctrl+Shift+Space
   - Verifica nei log il cambio istanza
   - Verifica che mostri le entità della nuova istanza

3. **Test Nessuna Istanza Disponibile**
   - Disconnetti da tutte le reti
   - Premi Ctrl+Shift+Space
   - Verifica che mostri il messaggio di errore
   - Riconnetti e riprova

## Log da Monitorare

Nel file `smart_proximity_control.log` cerca queste righe:

```
INFO - Verifica disponibilità istanza Home Assistant...
INFO - Istanza corrente ancora disponibile: http://10.10.10.106:8123
```

oppure:

```
INFO - Verifica disponibilità istanza Home Assistant...
INFO - Cambio istanza: http://10.10.10.106:8123 -> http://192.168.1.100:8123
INFO - Avvio scansione BLE per trovare dispositivo più vicino...
```

## Note Tecniche

- **Timeout connessione**: 2 secondi per l'istanza corrente, 3 secondi per le altre
- **Compatibilità**: Le variabili globali vengono ancora aggiornate per compatibilità con il resto del codice
- **Thread-safe**: La riconnessione avviene nel thread principale della GUI
- **Memoria dispositivi**: Viene pulita automaticamente quando l'istanza cambia
