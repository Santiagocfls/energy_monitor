# ============================================================
# sensors/dht_sensor.py — Módulo para el sensor DHT22
# ============================================================
# HARDWARE:
#   Sensor  : DHT22 (AM2302) — Temperatura y Humedad Relativa
#   Pin     : GPIO4 (configurable en config.py → DHT_PIN)
#   Protocolo: 1-Wire propietario (single-wire)
#
# CARACTERÍSTICAS DEL SENSOR:
#   Rango de temperatura : -40°C a +80°C  (±0.5°C de error)
#   Rango de humedad     : 0% a 100% HR   (±2–5% de error)
#   Tiempo entre lecturas: mínimo 2 segundos (el sensor lo rechaza si es antes)
#
# POR QUÉ NO LEER CADA SEGUNDO:
#   El DHT22 necesita al menos 2 s entre lecturas para estabilizar
#   su capacitor interno de medición. Leerlo más rápido produce
#   errores RuntimeError con "Checksum mismatch".
#   Por eso usamos DHT_READ_EVERY_N = 3 (lectura cada ~3 ciclos de 1 s).
#
# INSTALACIÓN:
#   pip install adafruit-circuitpython-dht
#   sudo apt-get install libgpiod2
# ============================================================

import board
import adafruit_dht
from config import DHT_PIN


class DHTSensor:
    """
    Sensor de temperatura y humedad relativa DHT22.

    Maneja internamente los errores de comunicación (RuntimeError)
    que son frecuentes en este sensor por su protocolo de 1 hilo.
    Cuando ocurre un error, conserva el último valor válido leído.
    """

    def __init__(self):
        """
        Inicializa el sensor DHT22 en el pin definido en config.py.
        """
        try:
            gpio_pin = getattr(board, DHT_PIN)
            self._dht = adafruit_dht.DHT22(gpio_pin)
        except AttributeError:
            raise ValueError(
                f"[DHTSensor] Pin '{DHT_PIN}' no válido. "
                f"Verifica DHT_PIN en config.py (ej: 'D4' para GPIO4)."
            )

        # Últimas lecturas válidas (se mantienen si ocurre un error)
        self.temperature: float = 0.0    # Temperatura en °C
        self.humidity: float    = 0.0    # Humedad relativa en %
        self._error_count: int  = 0      # Contador de errores acumulados
        self._read_count: int   = 0      # Total de lecturas intentadas

    # ----------------------------------------------------------
    # Lectura con manejo de errores
    # ----------------------------------------------------------

    def read(self) -> bool:
        """
        Intenta leer temperatura y humedad del DHT22.

        El sensor puede fallar ocasionalmente por:
          - Interferencia electromagnética en el cable de datos
          - Condensación en el sensor
          - Timing del protocolo 1-Wire afectado por carga del SO

        Retorna:
            True  → lectura exitosa (self.temperature y self.humidity actualizados)
            False → error de comunicación (valores anteriores conservados)
        """
        self._read_count += 1
        try:
            t = self._dht.temperature
            h = self._dht.humidity

            # Validar rangos físicamente posibles
            if t is not None and h is not None:
                if -40.0 <= t <= 80.0 and 0.0 <= h <= 100.0:
                    self.temperature = round(t, 1)
                    self.humidity    = round(h, 1)
                    return True

        except RuntimeError:
            # Error normal del DHT22, se registra pero no se propaga
            self._error_count += 1

        return False

    # ----------------------------------------------------------
    # Diagnóstico
    # ----------------------------------------------------------

    def error_rate(self) -> float:
        """
        Retorna el porcentaje de lecturas fallidas.

        Útil para detectar problemas de hardware:
          > 20% de error → revisar conexión física o cable muy largo
          > 50% de error → sensor defectuoso o pin incorrecto
        """
        if self._read_count == 0:
            return 0.0
        return round((self._error_count / self._read_count) * 100, 1)

    def status_str(self) -> str:
        """Retorna un string de diagnóstico para mostrar en pantalla o log."""
        return (
            f"DHT22 | Lecturas: {self._read_count} | "
            f"Errores: {self._error_count} ({self.error_rate()}%)"
        )

    # ----------------------------------------------------------
    # Limpieza de recursos
    # ----------------------------------------------------------

    def exit(self):
        """
        Libera el pin GPIO del DHT22.
        DEBE llamarse antes de cerrar el programa para evitar
        bloqueos del pin en la siguiente ejecución.
        """
        try:
            self._dht.exit()
        except Exception:
            pass
