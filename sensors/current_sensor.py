# ============================================================
# sensors/current_sensor.py — Módulo para el sensor WCS1600
# ============================================================
# HARDWARE:
#   Sensor  : WCS1600 (sensor de corriente AC por efecto Hall)
#   ADC     : MCP3008 Canal CH1
#   Rango   : ±16A (máximo recomendado para uso continuo: 12A)
#   Salida  : 0.4V–4.6V centrada en VCC/2 → escalada a 3.3V
#
# PRINCIPIO DE OPERACIÓN (Efecto Hall):
#   El WCS1600 detecta el campo magnético generado por la corriente
#   que fluye a través del conductor que pasa por su núcleo toroidal.
#   No hace contacto galvánico con el circuito de potencia → SEGURO.
#   Su tensión de salida sigue la ley:
#
#       V_out = V_zero + (I_ac × SENSITIVITY_MV_A)
#
#   Donde:
#       V_zero          = VCC/2 (punto de reposo, ≈ 2500 mV con 5V)
#       SENSITIVITY_MV_A = 24 mV/A (especificación del fabricante)
#
# CÁLCULO DE CORRIENTE RMS:
#   Para corriente AC, el valor RMS es la raíz cuadrática media:
#
#       I_rms = sqrt( Σ(I_instantánea²) / N )
#
#   Donde cada muestra instantánea es:
#
#       I_inst = (V_adc_mV - V_zero_mV) / SENSITIVITY_MV_A
#
# CADENA DE PROCESAMIENTO:
#   ADC raw → Voltaje mV → Centrar en 0 → I_inst → I²→ Σ → RMS →
#   → Restar ruido de piso → × Factor de calibración → Noise Gate → I_final
#
# ⚠ SEGURIDAD:
#   Aunque el WCS1600 es seguro (no contacto galvánico),
#   el cableado de la carga que pasa por el sensor SÍ porta 120/220V.
#   Nunca manipular ese cableado con el sistema energizado.
# ============================================================

import math
import time
from config import (
    ADC_CURRENT_CH, ADC_RESOLUTION, MCP3008_VREF_MV,
    SENSITIVITY_MV_A, NOISE_FLOOR_RMS_A, CALIBRATION_FACTOR,
    CURRENT_GATE_A, ZERO_CURRENT_MV_DEFAULT, CURRENT_CAL_DURATION_S,
    SAMPLE_INTERVAL_US
)
from utils.timing import micros


class CurrentSensor:
    """
    Sensor de corriente AC WCS1600 con calibración dinámica del punto cero.

    El punto cero (zero_voltage_mv) se determina durante la calibración
    midiendo la tensión de salida del sensor SIN corriente que fluya.
    Esto compensa variaciones de temperatura y tolerancias del módulo.
    """

    def __init__(self, adc_reader):
        """
        Parámetros:
            adc_reader: callable(channel: int) → int
                        Función compartida de lectura del MCP3008.
        """
        self._read_adc = adc_reader

        # Punto cero calibrado dinámicamente (mV)
        self.zero_voltage_mv: float = ZERO_CURRENT_MV_DEFAULT

        # Acumuladores para el cálculo RMS por ciclo
        self._sum_sq: float    = 0.0   # Σ(I_instantánea²)
        self._count: int       = 0     # Número de muestras acumuladas

        # Último resultado calculado
        self.rms_a: float = 0.0

        # Diagnóstico
        self._cal_samples: int = 0

    # ----------------------------------------------------------
    # Calibración del punto cero (sin carga)
    # ----------------------------------------------------------

    def calibrate(self, duration_s: float = None):
        """
        Determina el voltaje de reposo del sensor SIN corriente.

        IMPORTANTE:
            - Ejecutar con el circuito de carga DESCONECTADO o apagado
            - Duración: CURRENT_CAL_DURATION_S segundos (default: 4 s)
            - A mayor duración → mayor precisión del punto cero

        Matemáticamente:
            V_zero = (Σ(raw_adc) / N) × (VREF / ADC_RESOLUTION)

        El promedio de muchas muestras elimina el ruido AC residual
        y entrega el valor DC real del punto de reposo del sensor.
        """
        if duration_s is None:
            duration_s = CURRENT_CAL_DURATION_S

        print(f"  [CurrentSensor] Calibrando punto cero ({duration_s:.0f} s sin carga)...")

        total_raw, count = 0.0, 0
        end_time = time.perf_counter() + duration_s
        t_last   = micros()

        while time.perf_counter() < end_time:
            now = micros()
            if now - t_last >= SAMPLE_INTERVAL_US:
                total_raw += self._read_adc(ADC_CURRENT_CH)
                count     += 1
                t_last     = now
            time.sleep(0.0001)

        if count > 0:
            raw_avg            = total_raw / count
            self.zero_voltage_mv = (raw_avg / ADC_RESOLUTION) * MCP3008_VREF_MV
            self._cal_samples  = count

        print(f"  [CurrentSensor] Punto cero = {self.zero_voltage_mv:.2f} mV "
              f"(promedio de {self._cal_samples} muestras) ✓")

    # ----------------------------------------------------------
    # Muestreo continuo (llamar cada ~1 ms en el bucle principal)
    # ----------------------------------------------------------

    def sample(self):
        """
        Lee una muestra ADC, calcula la corriente instantánea y la
        acumula en el acumulador cuadrático.

        Proceso de conversión:
            1. raw_adc   → V_sensor_mV = (raw_adc / 1023) × 3300
            2. Centrar   → V_offset_mV = V_sensor_mV - zero_voltage_mv
            3. Amperios  → I_inst_A    = V_offset_mV / SENSITIVITY_MV_A (24 mV/A)
            4. Cuadrado  → I_inst² se suma al acumulador
        """
        raw       = self._read_adc(ADC_CURRENT_CH)
        v_mv      = (raw / ADC_RESOLUTION) * MCP3008_VREF_MV
        i_inst    = (v_mv - self.zero_voltage_mv) / SENSITIVITY_MV_A

        self._sum_sq += i_inst * i_inst
        self._count  += 1

    # ----------------------------------------------------------
    # Cálculo RMS y reinicio de ciclo
    # ----------------------------------------------------------

    def compute_rms(self) -> float:
        """
        Calcula la corriente RMS del ciclo acumulado con compensaciones.

        Cadena de procesamiento:
            I_rms_raw   = sqrt(Σ(I²) / N)
            I_compensada = I_rms_raw - NOISE_FLOOR_RMS_A
            I_calibrada  = I_compensada × CALIBRATION_FACTOR
            I_final      = 0 si I_calibrada < CURRENT_GATE_A

        Compensaciones aplicadas:
          1. NOISE_FLOOR_RMS_A (0.15 A): resta el ruido de piso inherente
             al sensor (inducción residual del transformador de tensión).
          2. CALIBRATION_FACTOR (0.392): corrige la ganancia real vs. teórica
             del circuito divisor de tensión (VCC 5V → 3.3V del ADC).
          3. CURRENT_GATE_A (0.50 A): filtro final por software que suprime
             lecturas falsas por inducción electromagnética ambiental.

        Reinicia los acumuladores al finalizar.

        Retorna:
            Corriente RMS calibrada en Amperios (float). 0.0 si hay noise gate.
        """
        if self._count == 0:
            self.rms_a = 0.0
            return 0.0

        # 1. RMS matemático puro
        rms_raw = math.sqrt(self._sum_sq / self._count)

        # 2. Restar ruido de piso del sensor
        compensated = rms_raw - NOISE_FLOOR_RMS_A

        # 3. Aplicar factor de calibración empírico
        calibrated = compensated * CALIBRATION_FACTOR

        # 4. Noise gate por software
        self.rms_a = calibrated if calibrated >= CURRENT_GATE_A else 0.0

        # ---- Reiniciar acumuladores ----
        self._sum_sq = 0.0
        self._count  = 0

        return self.rms_a

    # ----------------------------------------------------------
    # Diagnóstico
    # ----------------------------------------------------------

    @property
    def calibration_samples(self) -> int:
        """Número de muestras usadas en la calibración del punto cero."""
        return self._cal_samples

    def diagnostic_str(self) -> str:
        """Retorna string de diagnóstico para debug o pantalla."""
        return (
            f"WCS1600 | Cero: {self.zero_voltage_mv:.2f} mV | "
            f"I_rms: {self.rms_a:.3f} A | "
            f"Cal. muestras: {self._cal_samples}"
        )
