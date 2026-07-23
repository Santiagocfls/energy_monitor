#!/usr/bin/env python3
# ============================================================
# main.py — Punto de entrada del Sistema de Monitoreo Energético
# ============================================================
# ARQUITECTURA:
#   Este archivo únicamente orquesta los módulos independientes.
#   NO contiene lógica de sensores ni cálculos matemáticos.
#   Cada responsabilidad está delegada a su módulo correspondiente:
#
#   config.py              → Parámetros globales
#   sensors/rtc_sensor.py  → Fecha/hora (DS3231)
#   sensors/dht_sensor.py  → Temperatura y humedad (DHT22)
#   sensors/voltage_sensor.py → Voltaje RMS (ZMPT101B + MCP3008)
#   sensors/current_sensor.py → Corriente RMS (WCS1600 + MCP3008)
#   data/logger.py         → Registro CSV por sesión
#   display/terminal_ui.py → Dashboard en terminal
#   utils/timing.py        → Temporización de alta resolución
#
# FLUJO DE EJECUCIÓN:
#   1. Inicializar hardware (SPI, I2C, GPIO)
#   2. Mostrar pantalla de arranque
#   3. Calibrar sensor de tensión (blocking, ~4 s)
#   4. Calibrar sensor de corriente (blocking, ~4 s)
#   5. Crear archivo CSV con timestamp del RTC
#   6. Bucle principal de muestreo y cálculo
#   7. Cierre limpio al recibir Ctrl+C
#
# USO:
#   python3 main.py
#
# DEPENDENCIAS:
#   pip install spidev adafruit-circuitpython-ds3231
#               adafruit-circuitpython-dht
# ============================================================

import spidev
import time
import sys

# Módulos del sistema
from config import (
    SPI_BUS, SPI_DEVICE, SPI_SPEED_HZ,
    SAMPLE_INTERVAL_US, SAMPLES_PER_CYCLE
)
from sensors.rtc_sensor     import RTCSensor
from sensors.dht_sensor     import DHTSensor
from sensors.voltage_sensor import VoltageSensor
from sensors.current_sensor import CurrentSensor
from data.logger            import DataLogger
from display.terminal_ui    import TerminalUI
from utils.timing           import micros


# ============================================================
# 1. Inicializar hardware SPI compartido (MCP3008)
# ============================================================
spi = spidev.SpiDev()
spi.open(SPI_BUS, SPI_DEVICE)
spi.max_speed_hz = SPI_SPEED_HZ


def read_adc(channel: int) -> int:
    """
    Lee el valor ADC crudo del MCP3008 en el canal indicado.

    Protocolo SPI del MCP3008:
        Byte 1: Start bit           → 0x01
        Byte 2: Canal en modo single → (8 + canal) << 4
        Byte 3: Don't care          → 0x00

    Respuesta:
        Los 10 bits del resultado vienen en los bits 1-0 del byte 2
        y en los 8 bits del byte 3.

    Retorna:
        Entero 0–1023 (resolución de 10 bits)
    """
    if not 0 <= channel <= 7:
        raise ValueError(f"Canal ADC fuera de rango: {channel} (debe ser 0–7)")
    reply = spi.xfer2([1, (8 + channel) << 4, 0])
    return ((reply[1] & 3) << 8) + reply[2]


# ============================================================
# 2. Instanciar todos los módulos
# ============================================================
rtc     = RTCSensor()
dht     = DHTSensor()
voltage = VoltageSensor(read_adc)
current = CurrentSensor(read_adc)
ui      = TerminalUI()


# ============================================================
# 3. Arranque: pantalla de boot + calibración
# ============================================================
ui.show_boot_screen()

# === NUEVO: Sincronizar RTC con hora del sistema (sincronizada con internet) ===
print("  Sincronizando RTC con hora del sistema...")
if rtc.sync_with_system():
    print("  ✓ RTC sincronizado correctamente")
else:
    print("  ⚠️ No se pudo sincronizar RTC, usando hora actual")
time.sleep(0.5)

# Calibración bloqueante de tensión (sin carga ~4 s)
voltage.calibrate()

# Calibración bloqueante de corriente (sin carga ~4 s)
current.calibrate()

# Primera lectura del DHT22 (puede tardar ~1 s)
dht.read()


# ============================================================
# 4. Crear archivo CSV de sesión con timestamp del RTC
# ============================================================
start_timestamp = rtc.get_filename_str()   # ej: '2025-06-14_09-30-01'
logger = DataLogger(start_timestamp=start_timestamp)
ui.set_session_file(f"{start_timestamp}.csv")

print(f"\n  Sistema listo. Iniciando monitoreo...\n")
time.sleep(1.0)


# ============================================================
# 5. Bucle principal de muestreo y cálculo
# ============================================================
sample_timer = micros()   # Marca de tiempo para el intervalo de muestreo
dht_counter  = 0          # Contador para leer el DHT22 cada N ciclos

try:
    while True:
        now = micros()

        # ---- Muestreo continuo cada SAMPLE_INTERVAL_US microsegundos ----
        # A 1000 µs de intervalo → 1000 muestras/segundo
        # Con red a 60 Hz → ~16.7 ciclos completos por segundo de muestreo ✓
        if now - sample_timer >= SAMPLE_INTERVAL_US:
            voltage.sample()   # Acumula una muestra al sensor de tensión
            current.sample()   # Acumula una muestra al sensor de corriente
            sample_timer = now

        # ---- Cálculo RMS cada SAMPLES_PER_CYCLE muestras (~1 segundo) ----
        if voltage.sample_count >= SAMPLES_PER_CYCLE:

            # 1. Calcular magnitudes RMS del ciclo completado
            v_rms = voltage.compute_rms()    # Voltios
            i_rms = current.compute_rms()    # Amperios
            p_app = v_rms * i_rms            # Watts (potencia aparente)

            # 2. Leer el DHT22 cada DHT_READ_EVERY_N ciclos (~3 s)
            dht_counter += 1
            if dht_counter >= 3:
                dht.read()
                dht_counter = 0

            # 3. Obtener timestamp real del RTC para esta lectura
            timestamp = rtc.get_timestamp_str()
            hour      = rtc.get_hour()

            # 4. Guardar en CSV (sin zero_mv)
            logger.log(
                timestamp   = timestamp,
                hour        = hour,
                voltage     = v_rms,
                current     = i_rms,
                power       = p_app,
                temperature = dht.temperature,
                humidity    = dht.humidity,
            )

            # 5. Actualizar el dashboard en terminal (sin zero_mv)
            ui.render(
                timestamp   = timestamp,
                voltage     = v_rms,
                current     = i_rms,
                power       = p_app,
                temperature = dht.temperature,
                humidity    = dht.humidity,
            )

        # Dormir el mínimo posible para no saturar la CPU
        # El scheduler de Linux tiene resolución de ~100 µs
        time.sleep(0.0001)


# ============================================================
# 6. Cierre limpio del sistema
# ============================================================
except KeyboardInterrupt:
    print("\n\n  Deteniendo sistema de monitoreo...")

    logger.close()    # Cierra y guarda el CSV correctamente
    dht.exit()        # Libera el pin GPIO del DHT22
    spi.close()       # Cierra el bus SPI

    print(f"  DHT22  → {dht.status_str()}")
    print(f"  WCS1600 → {current.diagnostic_str()}")
    print(f"\n  ✓ Sistema detenido correctamente.\n")
    sys.exit(0)

except Exception as e:
    # Captura cualquier error inesperado y cierra de forma segura
    print(f"\n  [ERROR] {e}")
    logger.close()
    dht.exit()
    spi.close()
    sys.exit(1)
