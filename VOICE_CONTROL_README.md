# Voice Control for Home Assistant

Controllo vocale **push-to-talk** per Home Assistant - Non interferisce con microfono quando non in uso!

## 🎯 Caratteristiche

- ⌨️ **Push-to-Talk**: Ascolto SOLO quando premi **Ctrl+Shift+AltGr**
- 🎤 **Zero Interferenze**: Non usa il microfono finché non attivi la hotkey
- 💻 **Basso Consumo**: Quasi zero risorse quando in standby
- 🔊 **Feedback Audio**: Beep per confermare attivazione/successo/errore
- 🏠 **Multi-Istanza**: Riusa config.ini per supportare più istanze HA
- 📱 **Tray Icon**: Menu contestuale per gestire il servizio
- 🔗 **Comandi Multipli**: Esegui più azioni in una sola frase (es. "spegni luci e accendi led")

## 🚀 Come Funziona

1. **Avvio**: Lo script resta in background (icona nella tray)
2. **Attivazione**: Premi **Ctrl+Shift+AltGr** quando vuoi dare un comando
3. **Beep**: Senti un beep → il microfono è attivo (per 3 secondi)
4. **Comando**: Parla (es. "accendi luce soggiorno")
5. **Esecuzione**: Beep di conferma → comando eseguito!

### Quando NON Interferisce

- ✅ Durante riunioni Teams/Zoom
- ✅ Quando registri audio
- ✅ Quando usi altri programmi con microfono
- ✅ Quando non stai usando l'hotkey

Il microfono viene accesso **SOLO** quando premi Ctrl+Shift+AltGr!

## 📦 Installazione

### 1. Installa le dipendenze

```bash
pip install -r requirements.txt
```

**Nota:** Lo script usa `sounddevice` invece di PyAudio per compatibilità con Python 3.14+

### 2. Configurazione

Lo script usa lo stesso **config.ini** di Smart Proximity Control.
Non serve configurazione aggiuntiva!

### 3. Avvio

```bash
python voice_control.py
```

Oppure crea un eseguibile:
```bash
pyinstaller --noconsole --onefile --icon=logo_gb.ico voice_control.py
```

## 🎤 Comandi Supportati

### Comandi Multipli ⭐ NUOVO!
Puoi dare **più comandi in una sola frase** separandoli con "**e**" o "**and**":
- "**spegni tutte le luci e accendi tutti i led**"
- "**chiudi la tapparella e spegni la luce**"
- "**accendi luce cucina e apri tapparella soggiorno**"

Il sistema eseguirà ogni comando in sequenza automaticamente!

### Luci e Interruttori
- "**accendi** luce soggiorno"
- "**accendi** luce camera"
- "**spegni** luce cucina"
- "**spegni** tutte le luci" (se hai un'entità così chiamata)

### Tapparelle/Tende
- "**apri** tapparella soggiorno"
- "**chiudi** tapparella camera"

### Varianti Accettate
- "accendi" / "accenda" / "attiva"
- "spegni" / "spegna" / "disattiva"

## 🎹 Hotkey

| Hotkey | Azione |
|--------|--------|
| **Ctrl+Shift+AltGr** | Attiva ascolto vocale (3 sec timeout) |

## 🔊 Feedback Audio

| Suono | Significato |
|-------|-------------|
| Beep breve (1000Hz) | Ascolto attivato - parla ora! |
| Beep alto (1500Hz) | Comando riconosciuto |
| Beep molto alto (2000Hz) | Comando eseguito con successo ✓ |
| Beep basso lungo (500Hz) | Errore - comando non capito ✗ |

## 📱 System Tray Menu

Click destro sull'icona nella tray:
- **Disabilita/Abilita** - Attiva/disattiva il servizio
- **Riconnetti a HA** - Riconnette all'istanza disponibile
- **Esci** - Chiude l'applicazione

## 🛠️ Risoluzione Problemi

### "Non riconosce i comandi"

1. Verifica connessione internet (usa Google Speech API)
2. Parla chiaramente dopo il beep
3. Controlla che il nome dell'entità sia corretto
4. Esempio: se l'entità è "Luce Soggiorno", dì "accendi soggiorno"

### "Il microfono non funziona"

1. Verifica che il microfono sia configurato come default in Windows
2. Testa con: `python -c "import speech_recognition as sr; print(sr.Microphone.list_microphone_names())"`
3. Verifica che PyAudio sia installato correttamente

### "Interferisce con altre app"

**NON dovrebbe interferire** perché il microfono è attivo solo quando premi la hotkey.
Se interferisce, verifica che:
- Non hai l'ascolto bloccato (premi Ctrl+Shift+AltGr e aspetta 3 secondi)
- Non ci siano errori nel log (`voice_control.log`)

## 🔄 Confronto con Ascolto Continuo

| Caratteristica | Push-to-Talk (questo) | Ascolto Continuo |
|----------------|----------------------|------------------|
| Consumo CPU | ~0% (standby) | 10-30% costante |
| Consumo RAM | 50-100 MB | 200-500 MB |
| Interferenza microfono | **Nessuna** | **Sempre** |
| Privacy | **Alta** | Bassa |
| Latenza risposta | Immediata | Immediata |
| Compatibilità riunioni | ✅ **Sì** | ❌ No |

## 🔐 Privacy

- Il microfono è attivo **solo 3 secondi** dopo aver premuto la hotkey
- Usa Google Speech API (richiede internet, ma solo per il riconoscimento)
- Nessun dato viene salvato o registrato
- Il log contiene solo i comandi riconosciuti (non l'audio)

## 🌐 Requisiti Internet

- **Sì, richiesto** per il riconoscimento vocale (Google Speech API)
- Alternativa offline: Modificare per usare Vosk (più complesso, meno preciso)

## 🚀 Avvio Automatico con Windows

Crea un collegamento a `voice_control.py` in:
```
C:\Users\TuoNome\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup
```

Oppure aggiungi al Task Scheduler con trigger "All'avvio".

## 📊 Log

I log vengono salvati in `voice_control.log` (max 2MB, rotazione automatica).

Esempio log:
```
2026-01-08 10:30:15 - INFO - Ascolto attivato
2026-01-08 10:30:17 - INFO - Testo riconosciuto: 'accendi luce soggiorno'
2026-01-08 10:30:17 - INFO - Azione: turn_on, Entità: soggiorno
2026-01-08 10:30:17 - INFO - Comando eseguito: turn_on su light.luce_soggiorno
```

## 🔧 Personalizzazione

### Cambiare la Hotkey

Modifica la riga in `voice_control.py`:
```python
keyboard.add_hotkey('ctrl+shift+alt gr', self.on_hotkey, suppress=True)
```

Esempi:
- `'ctrl+alt+v'` - Ctrl+Alt+V
- `'f12'` - Tasto F12
- `'ctrl+space'` - Ctrl+Spazio

### Aggiungere Altri Comandi

Modifica il dizionario `commands` in `parse_command()`:
```python
commands = {
    'accendi': 'turn_on',
    'spegni': 'turn_off',
    'aumenta': 'brightness_increase',  # Nuovo!
    'diminuisci': 'brightness_decrease',  # Nuovo!
}
```

### Cambiare Timeout Ascolto

Modifica in `listen_and_execute()`:
```python
audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=10)
# timeout=5 → aspetta 5 secondi prima di abbandonare
# phrase_time_limit=10 → massimo 10 secondi di registrazione
```

## 🆚 Quando Usarlo

### Usa Voice Control quando:
- ✅ Vuoi controllo rapido senza guardare il telefono
- ✅ Hai le mani occupate (cucina, fai da te, ecc.)
- ✅ Vuoi un'alternativa veloce alla GUI

### Usa Smart Proximity Control quando:
- ✅ Vuoi controllo automatico basato sulla posizione
- ✅ Preferisci interfaccia visuale
- ✅ Vuoi vedere lo stato di più entità insieme

### Usali Insieme! 🎉
Entrambi gli script possono girare simultaneamente senza problemi!

## 📝 Esempio Sessione

```
=== Avvio Voice Control ===
✓ Connesso a http://10.10.10.106:8123
✓ Hotkey Ctrl+Shift+AltGr registrata!
  Premi Ctrl+Shift+AltGr per attivare l'ascolto

[Premi Ctrl+Shift+AltGr]

🎤 Ascolto attivo... Parla ora!
✓ Riconosciuto: 'accendi luce soggiorno'
→ Esecuzione: turn_on su light.luce_led_salotto
✓ Comando eseguito con successo!
🎤 Ascolto disattivato
```

## 🤝 Contributi

Idee per miglioramenti:
- [ ] Supporto per altre lingue
- [ ] Riconoscimento vocale offline (Vosk)
- [ ] Controllo volume luci ("imposta luminosità al 50%")
- [ ] Scene ("attiva scena cinema")
- [ ] Feedback vocale (Text-to-Speech)

## 📄 Licenza

MIT License - Usa come preferisci!

---

**Made with 🎤 by Guido Ballarini**
