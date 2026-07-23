# ============================================================
# sensors/voltage_sensor.py — Módulo para el sensor ZMPT101B
# ============================================================
# HARDWARE:
#   Sensor  : ZMPT101B (transformador de voltaje miniatura)
#   ADC     : MCP3008 Canal CH0
#   Salida  : Señal AC centrada en VCC/2 → escalada a 0–3.3V
#
# PRINCIPIO DE OPERACIÓN:
#   El ZMPT101B aísla galvánicamente la red AC (120/220V) y entrega
#   una señal proporcional centrada alrededor de VCC/2 (1.65V con 3.3V).
#   El ADC convierte esa señal a valores digitales 0–1023.
#   El valor de reposo (sin tensión AC) es ≈ 512 (mitad del rango).
#
# CÁLCULO DEL VOLTAJE RMS:
#   1. Restar la componente DC: muestra_centrada = raw_adc - 512
#   2. Aplicar offset1 para corregir desvíos estáticos de la señal
#   3. Calcular la media cuadrática: sqrt(Σ(muestra²) / N)
#   4. Aplicar VOLTAGE_SCALE_FACTOR (calibración empírica con multímetro)
#   5. Aplicar offset2 para eliminar el error residual del RMS
#
# PROCESO DE CALIBRACIÓN (2 FASES):
#   FASE 1 → Calcula la media DC de la señal (offset1) para centrarla en 0
#   FASE 2 → Con la señal centrada, calcula el RMS base (offset2) para
#             corregir el ruido de piso que el ADC añade incluso sin señal
#
# SEGURIDAD:
#   ⚠ El ZMPT101B tiene aislamiento galvánico, PERO el circuito de
#   acondicionamiento puede tener tensiones peligrosas antes del módulo.
#   NUNCA tocar los terminales de entrada del módulo con la red energizada.
# ============================================================

import math
import time
import config
from config import (
    ADC_VOLTAGE_CH, ADC_RESOLUTION, VOLTAGE_SCALE_FACTOR,
    VOLTAGE_MIN_RMS, VOLTAGE_GATE_V, VOLTAGE_CAL_SAMPLES,
    VOLTAGE_OFFSET1_WAIT, VOLTAGE_OFFSET2_WAIT,
    SAMPLE_INTERVAL_US
)
from utils.timing import micros


class VoltageSensor:
    """
    Sensor de tensión AC ZMPT101B con calibración automática de offset.

    Proceso interno:
        calibrate()  → determina offset1 y offset2 (bloquea ~4 segundos)
        sample()     → acumula una muestra al acumulador RMS
        compute_rms() → calcula y retorna el voltaje RMS, reinicia acumuladores
    """

    def __init__(self, adc_reader):
        """
        Parámetros:
            adc_reader: callable(channel: int) → int
                        Función que lee el canal del MCP3008.
                        Se pasa desde main.py para no duplicar la instancia SPI.
        """
        self._read_adc = adc_reader

        # Offsets de calibración (calculados en calibrate())
        self._offset1: float = 0.0
        self._offset2: float = 0.0

        # Acumuladores para el cálculo RMS por ciclo
        self._sum_sq: float   = 0.0   # Σ(muestra²) — suma de cuadrados
        self._sum_dc: float   = 0.0   # Σ(muestra)  — para monitorear deriva DC
        self.sample_count: int = 0    # Número de muestras acumuladas

        # Último resultado calculado
        self.rms_v: float = 0.0

    # ----------------------------------------------------------
    # Calibración automática de doble offset
    # ----------------------------------------------------------

    def calibrate(self):
        """
        Calibración bloqueante de dos fases.
        ⚠ DEBE ejecutarse SIN tensión AC en el sensor para mejor precisión.

        FASE 1 (offset1): elimina la componente DC estática de la señal.
                          Toma VOLTAGE_OFFSET1_WAIT muestras.
        FASE 2 (offset2): elimina el RMS residual del ruido de piso del ADC.
                          Toma VOLTAGE_OFFSET2_WAIT muestras adicionales.

        Duración total: ~4 segundos a 1 muestra/ms.
        """
        print("  [VoltageSensor] Fase 1: calculando offset DC...")
        self._offset1, self._offset2 = 0.0, 0.0

        # ---- Fase 1: media DC ----
        sum_dc, count = 0.0, 0
        t_last = micros()
        while count < VOLTAGE_OFFSET1_WAIT:
            now = micros()
            if now - t_last >= SAMPLE_INTERVAL_US:
                raw = self._read_adc(ADC_VOLTAGE_CH)
                sum_dc += (raw - 512)
                count  += 1
                t_last  = now
            time.sleep(0.0001)

        self._offset1 = -(sum_dc / count)   # Offset negativo para centrar en 0

        print("  [VoltageSensor] Fase 2: calculando offset RMS residual...")

        # ---- Fase 2: RMS residual (ruido de piso) ----
        sum_sq2, count2 = 0.0, 0
        t_last = micros()
        while count2 < VOLTAGE_OFFSET2_WAIT:
            now = micros()
            if now - t_last >= SAMPLE_INTERVAL_US:
                raw     = self._read_adc(ADC_VOLTAGE_CH)
                sample  = (raw - 512) + self._offset1
                sum_sq2 += sample * sample
                count2  += 1
                t_last   = now
            time.sleep(0.0001)

        rms_base    = math.sqrt(sum_sq2 / count2) * VOLTAGE_SCALE_FACTOR
        self._offset2 = -rms_base   # Corregimos el nivel base

        print(f"  [VoltageSensor] offset1={self._offset1:.4f} | "
              f"offset2={self._offset2:.4f} | Calibración completada ✓")

    # ----------------------------------------------------------
    # Muestreo continuo (llamar cada ~1 ms en el bucle principal)
    # ----------------------------------------------------------

    def sample(self):
        """
        Lee una muestra del ADC, la centra con offset1 y la acumula
        en el acumulador cuadrático para el cálculo RMS.

        Llamar desde el bucle principal cada SAMPLE_INTERVAL_US µs.
        """
        raw    = self._read_adc(ADC_VOLTAGE_CH)
        sample = (raw - 512) + self._offset1

        self._sum_sq     += sample * sample
        self._sum_dc     += sample
        self.sample_count += 1

    # ----------------------------------------------------------
    # Cálculo RMS y reinicio de ciclo
    # ----------------------------------------------------------

    def compute_rms(self) -> float:
        """
        Calcula el voltaje RMS del ciclo acumulado.

        Fórmula:
            V_rms = sqrt(Σ(muestras²) / N) × SCALE_FACTOR + offset2

        Aplica:
          - Escala empírica (VOLTAGE_SCALE_FACTOR) ajustada con multímetro
          - Offset de corrección del RMS base (offset2)
          - Umbral mínimo (VOLTAGE_MIN_RMS) para retornar 0 cuando no hay red

        Reinicia los acumuladores al finalizar.

        Retorna:
            Voltaje RMS en Voltios (float).
        """
        if self.sample_count == 0:
            self.rms_v = 0.0
            return 0.0

        mean_sq = self._sum_sq / self.sample_count
        rms_raw = math.sqrt(mean_sq) * VOLTAGE_SCALE_FACTOR
        rms_cal = rms_raw + self._offset2

        # Umbral: si el valor calibrado es muy bajo, no hay tensión real
        self.rms_v = rms_cal if rms_cal > max(VOLTAGE_MIN_RMS, VOLTAGE_GATE_V) else 0.0

        # ---- Reiniciar acumuladores para el siguiente ciclo ----
        self._sum_sq      = 0.0
        self._sum_dc      = 0.0
        self.sample_count = 0

        return self.rms_v

    # ----------------------------------------------------------
    # Diagnóstico
    # ----------------------------------------------------------

    @property
    def offset1(self) -> float:
        """Offset DC calculado en calibración (unidades ADC)."""
        return self._offset1

    @property
    def offset2(self) -> float:
        """Offset RMS residual calculado en calibración (V)."""
        return self._offset2
