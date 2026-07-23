# Sistema de Monitoreo Energético — Raspberry Pi

Monitor de variables eléctricas AC (voltaje, corriente, potencia) con
registro histórico en CSV vinculado al reloj en tiempo real DS3231.

---

## Estructura del Proyecto

```
energy_monitor/
│
├── main.py                      ← Punto de entrada (ejecutar esto)
├── config.py                    ← Todos los parámetros ajustables
│
├── sensors/
│   ├── rtc_sensor.py            ← DS3231  (fecha/hora)
│   ├── dht_sensor.py            ← DHT22   (temperatura y humedad)
│   ├── voltage_sensor.py        ← ZMPT101B (voltaje AC via MCP3008 CH0)
│   └── current_sensor.py        ← WCS1600  (corriente AC via MCP3008 CH1)
│
├── data/
│   ├── logger.py                ← Escritura de CSV por sesión
│   └── sessions/                ← Archivos CSV generados automáticamente
│       └── 2025-06-14_09-30-01.csv
│
├── display/
│   └── terminal_ui.py           ← Dashboard en terminal con historial
│
└── utils/
    └── timing.py                ← micros() / millis() de alta resolución
```

---

## Conexiones de Hardware

### MCP3008 → Raspberry Pi (SPI)
| MCP3008 | RPi Pin | Función         |
|---------|---------|-----------------|
| VDD     | 3.3V    | Alimentación    |
| VREF    | 3.3V    | Referencia ADC  |
| AGND    | GND     | Tierra analógica|
| CLK     | GPIO11  | SPI SCLK        |
| DOUT    | GPIO9   | SPI MISO        |
| DIN     | GPIO10  | SPI MOSI        |
| CS/SHDN | GPIO8   | SPI CE0         |
| DGND    | GND     | Tierra digital  |

### Sensores → MCP3008
| Sensor    | Canal MCP3008 | Variable  |
|-----------|---------------|-----------|
| ZMPT101B  | CH0           | Voltaje   |
| WCS1600   | CH1           | Corriente |

### DHT22 → Raspberry Pi (GPIO directo)
| DHT22 | RPi        |
|-------|------------|
| VCC   | 3.3V o 5V  |
| DATA  | GPIO4 (D4) |
| GND   | GND        |

### DS3231 → Raspberry Pi (I2C)
| DS3231 | RPi     |
|--------|---------|
| VCC    | 3.3V    |
| GND    | GND     |
| SDA    | GPIO2   |
| SCL    | GPIO3   |

---

## Instalación de Dependencias

```bash
# Habilitar SPI e I2C en la Raspberry Pi
sudo raspi-config
# → Interface Options → SPI → Enable
# → Interface Options → I2C → Enable

# Instalar librerías Python
pip install spidev
pip install adafruit-circuitpython-ds3231
pip install adafruit-circuitpython-dht
sudo apt-get install libgpiod2
```

---

## Uso

```bash
# Desde la carpeta raíz del proyecto
python3 main.py

# Detener el monitoreo
Ctrl+C    # Guarda el CSV y cierra correctamente
```

---

## Archivos CSV Generados

Cada ejecución crea un archivo CSV en `data/sessions/`:

```
timestamp,hour,voltage_v,current_a,power_w,temperature_c,humidity_pct,zero_current_mv
2025-06-14 09:30:01,9,118.45,0.000,0.00,29.4,65.7,2555.53
2025-06-14 09:30:02,9,118.62,0.832,98.69,29.4,65.7,2555.53
```

### Análisis con pandas (Python)
```python
import pandas as pd

df = pd.read_csv("data/sessions/2025-06-14_09-30-01.csv")
df['timestamp'] = pd.to_datetime(df['timestamp'])

# Consumo promedio por hora del día
print(df.groupby('hour')['power_w'].mean())

# Pico de corriente
print(f"Pico: {df['current_a'].max():.3f} A")
```

---

## Parámetros de Calibración (config.py)

| Parámetro           | Default | Descripción                                    |
|---------------------|---------|------------------------------------------------|
| `SENSITIVITY_MV_A`  | 24.0    | Sensibilidad del WCS1600 (mV/A del datasheet)  |
| `CALIBRATION_FACTOR`| 0.392   | Ajustar midiendo con pinza amperimétrica        |
| `CURRENT_GATE_A`    | 0.50    | Noise gate: cargas menores se reportan como 0   |
| `NOISE_FLOOR_RMS_A` | 0.15    | Ruido de piso del sensor (A)                   |
| `VOLTAGE_SCALE_FACTOR`| 1.5   | Ajustar midiendo con multímetro calibrado       |

---

## Proceso de Calibración de Corriente

1. **Sin carga**: arrancar el sistema → `current.calibrate()` mide el punto cero
2. **Con carga conocida**: conectar una carga de potencia conocida (ej: foco 100W)
3. **Medir con pinza amperimétrica**: anotar el valor real
4. **Calcular el factor**: `CALIBRATION_FACTOR = I_real / I_medida`
5. **Actualizar `config.py`** con el nuevo valor

---

## Diagrama de Flujo

```
                    ┌─────────────┐
                    │   main.py   │
                    └──────┬──────┘
                           │ instancia
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   VoltageSensor    CurrentSensor      RTCSensor
   (ZMPT101B)       (WCS1600)          (DS3231)
          │                │                │
          └────────────────┤                │
                     cada 1 ms             │
                    sample()               │ timestamp
                           │               │
                    cada 1000 ms           │
                    compute_rms() ◄────────┘
                           │
                    ┌──────┴──────┐
                    │             │
               DataLogger   TerminalUI
               (CSV)        (pantalla)
```
