"""
Script per testare il recupero del nome dell'area da Home Assistant
"""
import requests
import configparser
import os

def get_base_path():
    """Restituisce il percorso della directory contenente lo script."""
    return os.path.dirname(os.path.abspath(__file__))

def load_config():
    """Carica la configurazione dal file config.ini"""
    base_path = get_base_path()
    config_file = os.path.join(base_path, 'config.ini')
    
    if not os.path.exists(config_file):
        print(f"❌ File config.ini non trovato in: {config_file}")
        return []
    
    config = configparser.ConfigParser()
    config.read(config_file)
    
    instances = []
    
    # Primary instance
    if config.has_option('home_assistant', 'url') and config.has_option('home_assistant', 'api_token'):
        url = config.get('home_assistant', 'url')
        token = config.get('home_assistant', 'api_token')
        if url and token:
            instances.append({'url': url, 'token': token})
    
    # Additional instances (up to 4)
    for i in range(2, 6):
        url_key = f'url_{i}'
        token_key = f'api_token_{i}'
        if config.has_option('home_assistant', url_key) and config.has_option('home_assistant', token_key):
            url = config.get('home_assistant', url_key)
            token = config.get('home_assistant', token_key)
            if url and token:
                instances.append({'url': url, 'token': token})
    
    return instances

def get_area_info(ha_url, ha_token, area_id):
    """Mostra la differenza tra entity_id e friendly_name per le entità di un'area."""
    try:
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        
        print(f"\n🔍 ANALISI ENTITÀ AREA: '{area_id}'")
        print("=" * 90)
        
        # Ottieni le entità dell'area
        template_url = f"{ha_url}/api/template"
        
        print(f"\n1️⃣  Ottengo lista entità per l'area '{area_id}'")
        print("-" * 90)
        
        entities_template = f"{{{{ area_entities('{area_id}') | list }}}}"
        entities_resp = requests.post(template_url, headers=headers,
                                     json={"template": entities_template}, timeout=5)
        
        if entities_resp.status_code != 200:
            print(f"❌ Errore nel recupero entità: {entities_resp.status_code}")
            return {'id': area_id, 'name': area_id}
        
        entity_ids = eval(entities_resp.text)
        print(f"✅ Trovate {len(entity_ids)} entità")
        
        # Ottieni gli stati di tutte le entità (contiene friendly_name)
        print(f"\n2️⃣  Recupero informazioni complete per ogni entità")
        print("-" * 90)
        
        states_url = f"{ha_url}/api/states"
        states_resp = requests.get(states_url, headers=headers, timeout=5)
        
        if states_resp.status_code != 200:
            print(f"❌ Errore nel recupero stati: {states_resp.status_code}")
            return {'id': area_id, 'name': area_id}
        
        all_states = states_resp.json()
        
        # Crea un mapping entity_id -> stato completo
        states_map = {state['entity_id']: state for state in all_states}
        
        # Mostra solo le luci per semplicità
        print(f"\n3️⃣  CONFRONTO ENTITY_ID vs FRIENDLY_NAME (solo luci)")
        print("-" * 90)
        print(f"{'ENTITY_ID':<45} | {'FRIENDLY_NAME':<40}")
        print("-" * 90)
        
        light_count = 0
        for entity_id in entity_ids:
            if entity_id.startswith('light.'):
                state = states_map.get(entity_id)
                if state:
                    friendly_name = state.get('attributes', {}).get('friendly_name', entity_id)
                    print(f"{entity_id:<45} | {friendly_name:<40}")
                    light_count += 1
        
        print("-" * 90)
        print(f"Totale luci: {light_count}")
        
        # Mostra esempio completo di un'entità
        if light_count > 0:
            print(f"\n4️⃣  ESEMPIO OGGETTO COMPLETO DI UN'ENTITÀ LUCE")
            print("-" * 90)
            
            for entity_id in entity_ids:
                if entity_id.startswith('light.'):
                    state = states_map.get(entity_id)
                    if state:
                        import json
                        print(json.dumps(state, indent=2))
                    break
            print("-" * 90)
        
        # Ottieni il nome dell'area
        area_name_template = f"{{{{ area_name('{area_id}') }}}}"
        area_name_resp = requests.post(template_url, headers=headers,
                                      json={"template": area_name_template}, timeout=5)
        area_name = area_name_resp.text.strip() if area_name_resp.status_code == 200 else area_id
        
        print("=" * 90)
        
        return {'id': area_id, 'name': area_name}
        
    except Exception as e:
        print(f"❌ Errore durante la chiamata: {e}")
        import traceback
        traceback.print_exc()
        return {'id': area_id, 'name': area_id}

def test_connection(ha_url, ha_token):
    """Testa la connessione a Home Assistant"""
    try:
        headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        response = requests.get(f"{ha_url}/api/", headers=headers, timeout=3)
        return response.status_code == 200
    except:
        return False

def main():
    print("\n" + "=" * 70)
    print("🧪 TEST RECUPERO NOME AREA DA HOME ASSISTANT")
    print("=" * 70)
    
    # Carica configurazione
    instances = load_config()
    if not instances:
        print("❌ Nessuna istanza Home Assistant configurata")
        return
    
    print(f"\n📋 Trovate {len(instances)} istanze configurate")
    
    # Trova prima istanza disponibile
    ha_url = None
    ha_token = None
    
    for i, instance in enumerate(instances, 1):
        url = instance['url']
        token = instance['token']
        print(f"\n🔄 Test connessione istanza {i}: {url}")
        
        if test_connection(url, token):
            print(f"   ✅ Connessione riuscita!")
            ha_url = url
            ha_token = token
            break
        else:
            print(f"   ❌ Non raggiungibile")
    
    if not ha_url:
        print("\n❌ Nessuna istanza Home Assistant raggiungibile!")
        return
    
    print(f"\n🏠 Utilizzo: {ha_url}")
    
    # Chiedi area_id da testare
    area_id = input("\n📝 Inserisci l'area_id da testare (es. area_ict): ").strip()
    
    if not area_id:
        print("❌ Area ID vuoto!")
        return
    
    # Testa get_area_info
    result = get_area_info(ha_url, ha_token, area_id)
    
    print(f"\n🎯 RISULTATO FINALE:")
    print("=" * 70)
    print(f"  Area ID:   {result['id']}")
    print(f"  Area Nome: {result['name']}")
    print("=" * 70)
    
    if result['id'] == result['name']:
        print("\n⚠️  ATTENZIONE: Nome uguale a ID (possibile fallback)")
        print("    Verifica che l'area_id esista in Home Assistant")
    else:
        print(f"\n✅ OK: Nome dell'area recuperato correttamente da HA!")

if __name__ == "__main__":
    main()
    input("\n\nPremi INVIO per chiudere...")
