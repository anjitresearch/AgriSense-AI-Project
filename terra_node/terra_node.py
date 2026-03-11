# ==============================================================
#  TERRA-NODE™ — Real-Time Soil Health Monitoring Firmware
#  Platform: ESP32-S3 (MicroPython)
#  Sensors:
#   - Capacitive Soil Moisture -> ADC (GPIO34)
#   - DS18B20 Temperature -> OneWire (GPIO4)
#   - pH Analog Module -> ADC (GPIO35)
#   - NPK RS485 -> UART2 (TX=17, RX=16) via Modbus RTU
#   - EC Analog Module -> ADC (GPIO32)
# ==============================================================

import machine
import network
import ujson
import utime
import ubinascii
import onewire
import ds18x20
from umqtt.simple import MQTTClient
import esp32

# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────
WIFI_SSID     = "AgriSense_Net"
WIFI_PASSWORD = "super_secret_wifi"
MQTT_BROKER   = "192.168.1.100"
MQTT_PORT     = 1883
FARM_ID       = "farm001"
DEVICE_ID     = "TERRA-001"
MQTT_TOPIC    = f"agrisense/{FARM_ID}/soil".encode()
POLL_INTERVAL = 300  # seconds (5 minutes)

# ──────────────────────────────────────────────
# PIN DEFINITIONS
# ──────────────────────────────────────────────
PIN_MOISTURE = 34
PIN_PH       = 35
PIN_EC       = 32
PIN_TEMP     = 4
PIN_RS485_TX = 17
PIN_RS485_RX = 16
PIN_RS485_DE = 18  # Data Enable for RS485 transceiver
PIN_LED      = 2   # Build-in LED for heartbeat

# ──────────────────────────────────────────────
# HARDWARE INIT
# ──────────────────────────────────────────────
led = machine.Pin(PIN_LED, machine.Pin.OUT)

# ADC Setup (0 - 3.3V range, 12-bit width: 0-4095)
adc_moisture = machine.ADC(machine.Pin(PIN_MOISTURE))
adc_moisture.atten(machine.ADC.ATTN_11DB)
adc_moisture.width(machine.ADC.WIDTH_12BIT)

adc_ph = machine.ADC(machine.Pin(PIN_PH))
adc_ph.atten(machine.ADC.ATTN_11DB)
adc_ph.width(machine.ADC.WIDTH_12BIT)

adc_ec = machine.ADC(machine.Pin(PIN_EC))
adc_ec.atten(machine.ADC.ATTN_11DB)
adc_ec.width(machine.ADC.WIDTH_12BIT)

# OneWire Temperature Setup
ds_pin = machine.Pin(PIN_TEMP)
ds_sensor = ds18x20.DS18X20(onewire.OneWire(ds_pin))
try:
    roms = ds_sensor.scan()
except Exception:
    roms = []

# RS485 UART Setup
uart2 = machine.UART(2, baudrate=9600, tx=PIN_RS485_TX, rx=PIN_RS485_RX, timeout=200)
rs485_de = machine.Pin(PIN_RS485_DE, machine.Pin.OUT)
rs485_de.value(0) # Receive mode by default

# ──────────────────────────────────────────────
# CALIBRATION DATA (NVS Flash Simulation)
# ──────────────────────────────────────────────
# In a real scenario, these would be loaded from machine.NVS
PH_CALIB = {
    "voltage_at_ph7": 2.0,   # volts
    "voltage_at_ph4": 2.5,   # volts
    "step_per_ph": -0.166    # (2.0 - 2.5) / (7 - 4)
}

MOISTURE_CALIB = {
    "air_adc": 4095,         # 0% VWC (Dry)
    "water_adc": 1500        # 100% VWC (Fully saturated)
}

def adc_to_voltage(adc_val):
    return (adc_val / 4095.0) * 3.3

def read_moisture():
    """Reads capacitive moisture and maps ADC to 0-100% VWC."""
    raw = adc_moisture.read()
    # Map raw value to percentage
    air = MOISTURE_CALIB["air_adc"]
    water = MOISTURE_CALIB["water_adc"]
    
    if raw >= air: return 0.0
    if raw <= water: return 100.0
    
    percent = ((air - raw) / (air - water)) * 100.0
    return round(percent, 1)

def read_ph():
    """Reads pH analog voltage and applies two-point calibration."""
    raw = adc_ph.read()
    voltage = adc_to_voltage(raw)
    
    # pH = 7.0 + ((voltage_at_ph7 - voltage) / step_per_ph)
    # E.g., if v=2.0 -> pH 7. If v=2.5 -> pH 4
    ph_val = 7.0 + ((PH_CALIB["voltage_at_ph7"] - voltage) / PH_CALIB["step_per_ph"])
    
    # Bound it to 0-14
    return round(max(0.0, min(14.0, ph_val)), 2)

def read_temp():
    """Reads DS18B20 OneWire temperature."""
    if not roms: return None
    try:
        ds_sensor.convert_temp()
        utime.sleep_ms(750)
        return round(ds_sensor.read_temp(roms[0]), 1)
    except Exception:
        return None

def read_ec():
    """Reads basic Analog EC. Returns raw mapping to mS/cm."""
    raw = adc_ec.read()
    voltage = adc_to_voltage(raw)
    # Generic linear mapping (depends heavily on probe specifics)
    ec_val = voltage * 2.5  
    return round(ec_val, 2)

def read_npk():
    """
    Reads NPK via Modbus RTU RS485.
    Sends read holding registers command.
    """
    # Standard query for N, P, K (Slave 0x01, Func 0x03, Reg 0x001E, 3 registers)
    # [01 03 00 1E 00 03 65 CD]
    cmd = bytes([0x01, 0x03, 0x00, 0x1E, 0x00, 0x03, 0x65, 0xCD])
    
    rs485_de.value(1) # Transmit mode
    utime.sleep_ms(10)
    uart2.write(cmd)
    utime.sleep_ms(50) # Wait for flush
    rs485_de.value(0) # Receive mode
    utime.sleep_ms(50)
    
    if uart2.any():
        response = uart2.read()
        # Modbus response for 3 registers:
        # [01][03][06][N_hi][N_lo][P_hi][P_lo][K_hi][K_lo][CRC_lo][CRC_hi]
        if response and len(response) >= 11 and response[0] == 0x01 and response[1] == 0x03:
            n = (response[3] << 8) | response[4]
            p = (response[5] << 8) | response[6]
            k = (response[7] << 8) | response[8]
            return {"N": n, "P": p, "K": k}
    
    return {"N": None, "P": None, "K": None}

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to {WIFI_SSID}...")
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        timeout = 20
        while not wlan.isconnected() and timeout > 0:
            utime.sleep(1)
            timeout -= 1
        if not wlan.isconnected():
            return False
    print("WiFi connected. IP:", wlan.ifconfig()[0])
    return True

def flash_led(times=3):
    for _ in range(times):
        led.value(1)
        utime.sleep_ms(100)
        led.value(0)
        utime.sleep_ms(100)

def main():
    print("[TERRA-NODE] Waking up from Deep Sleep...")
    
    # 1. Read Sensors
    temp = read_temp()
    moist = read_moisture()
    ph = read_ph()
    ec = read_ec()
    npk = read_npk()
    
    # Fake battery read for ESP32 (requires external voltage divider normally)
    batt_pct = 95.5
    
    payload = {
        "device_id": DEVICE_ID,
        "timestamp": utime.time(), 
        "npk": npk,
        "pH": ph,
        "EC": ec,
        "moisture": moist,
        "temperature": temp,
        "battery_pct": batt_pct
    }
    
    print("Payload:", ujson.dumps(payload))
    
    # 2. Publish to MQTT
    if connect_wifi():
        try:
            client_id = ubinascii.hexlify(machine.unique_id())
            client = MQTTClient(client_id, MQTT_BROKER, port=MQTT_PORT)
            client.connect()
            client.publish(MQTT_TOPIC, ujson.dumps(payload).encode('utf-8'))
            print(f"Published to {MQTT_TOPIC}")
            flash_led(3) # Heartbeat
            client.disconnect()
        except Exception as e:
            print("MQTT Error:", e)
            flash_led(1) # Error blink
    else:
        print("WiFi connection failed.")
        
    # 3. Deep Sleep (Requires RTC GPIO wake configuration internally)
    print(f"Going to deep sleep for {POLL_INTERVAL} seconds...")
    machine.deepsleep(POLL_INTERVAL * 1000)

if __name__ == "__main__":
    # If waking from deep sleep, execute immediately
    main()
