"""Script per testare il rilevamento BLE e mostrare tutti i beacon con i loro RSSI."""
import asyncio
import json
from bleak import BleakScanner

async def scan_ble_devices():
    """Scansiona tutti i dispositivi BLE e mostra i loro RSSI."""
    
    # Carica il mapping
    with open('ble_entity.json', 'r') as f:
        data = json.load(f)
        ble_mapping = data.get('ble_mapping', {})
    
    # Converti le chiavi in maiuscolo per il confronto
    ble_mapping_upper = {mac.upper(): area for mac, area in ble_mapping.items()}
    
    print("🔍 Scansione BLE in corso (5 secondi)...\n")
    
    devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
    
    print(f"📱 Trovati {len(devices)} dispositivi BLE totali\n")
    
    # Filtra solo i beacon configurati
    configured_beacons = []
    
    for device, adv_data in devices.values():
        mac = device.address.upper()
        if mac in ble_mapping_upper:
            area = ble_mapping_upper[mac]
            rssi = adv_data.rssi
            configured_beacons.append({
                'mac': mac,
                'name': device.name or 'N/A',
                'area': area,
                'rssi': rssi
            })
    
    if not configured_beacons:
        print("❌ Nessun beacon configurato rilevato!")
        return
    
    # Ordina per RSSI decrescente (più forte prima)
    configured_beacons.sort(key=lambda x: x['rssi'], reverse=True)
    
    print("📍 BEACON CONFIGURATI RILEVATI (ordinati per segnale più forte):\n")
    print(f"{'#':<3} {'Area':<20} {'MAC':<20} {'RSSI':<8} {'Nome':<15}")
    print("-" * 75)
    
    for idx, beacon in enumerate(configured_beacons, 1):
        marker = "👉 " if idx == 1 else "   "
        print(f"{marker}{idx:<3} {beacon['area']:<20} {beacon['mac']:<20} {beacon['rssi']:<8} {beacon['name']:<15}")
    
    print("\n👉 Il beacon selezionato dovrebbe essere il primo (segnale più forte)")
    print(f"✅ Area rilevata: {configured_beacons[0]['area']} (RSSI: {configured_beacons[0]['rssi']})")

if __name__ == "__main__":
    asyncio.run(scan_ble_devices())
