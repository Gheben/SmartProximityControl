# Changelog - Riconnessione Automatica

## [2026-01-09] - Supporto Comandi Vocali Multipli

### Nuova Funzionalità: Comandi Multipli in Una Frase

**Problema risolto:**
Il sistema vocale riconosceva correttamente frasi come "Spegni tutte le luci e accendi tutti i led" ma eseguiva solo la prima parte del comando.

**Implementazione:**

1. **Nuova funzione `split_multiple_commands()`**
   - Divide il testo riconosciuto in comandi multipli quando contiene " e " o " and "
   - Supporta sia italiano che inglese
   - Usa regex per evitare falsi positivi (`\s+e\s+|\s+and\s+`)

2. **Modificata `listen_and_execute()`**
   - Dopo il riconoscimento vocale, divide automaticamente il testo in comandi multipli
   - Mostra il numero di comandi rilevati
   - Esegue ogni comando separatamente in sequenza
   - Fornisce feedback per ogni comando quando sono multipli

3. **Nuova funzione `_execute_single_command()`**
   - Contiene la logica di esecuzione estratta e riutilizzabile
   - Gestisce gruppi (`all_lights`, `led_lights`) e singole entità
   - Viene chiamata per ogni comando della lista

**Esempi di utilizzo:**
- "Spegni tutte le luci e accendi tutti i led"
- "Chiudi la tapparella e spegni la luce"
- "Turn off lights and open cover"

**Output esempio:**
```
✓ Riconosciuto: 'Spegni tutte le luci e accendi tutti i led'
📋 Rilevati 2 comandi da eseguire

--- Comando 1/2: 'Spegni tutte le luci' ---
→ Esecuzione: turn_off su TUTTE LE LUCI nella stanza Soggiorno
✓ 3/3 luci controllate con successo!

--- Comando 2/2: 'accendi tutti i led' ---
→ Esecuzione: turn_on su LUCI LED nella stanza Soggiorno
✓ 2/2 luci LED controllate con successo!

✓ Completati tutti i 2 comandi!
```

---

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
