# ============================================================
# sensors/rtc_sensor.py — Módulo para el RTC DS3231 vía I2C
# ============================================================
# HARDWARE:
#   Sensor  : DS3231 (Real Time Clock)
#   Protocolo: I2C (SDA → GPIO2, SCL → GPIO3 en RPi)
#   Librería : adafruit-circuitpython-ds3231
#
# CONCEPTO:
#   El DS3231 mantiene la fecha y hora incluso sin alimentación
#   gracias a una batería CR2032 de respaldo.
#   Cada lectura de muestra lleva un timestamp real del RTC,
#   lo que permite correlacionar consumos con franjas horarias.
#
# INSTALACIÓN:
#   pip install adafruit-circuitpython-ds3231
# ============================================================

import board
import adafruit_ds3231
import time
import datetime


class RTCSensor:
    """
    Interfaz para el reloj en tiempo real DS3231.

    Proporciona timestamps formateados para:
      - Mostrar en pantalla (get_timestamp_str)
      - Nombrar archivos CSV  (get_filename_str)
      - Procesar como diccionario (get_datetime)
    """

    def __init__(self):
        """
        Inicializa la conexión I2C con el DS3231.
        Lanza IOError si el sensor no responde en el bus I2C.
        """
        try:
            i2c = board.I2C()
            self._rtc = adafruit_ds3231.DS3231(i2c)
        except Exception as e:
            raise IOError(
                f"[RTCSensor] No se pudo inicializar el DS3231. "
                f"Verifica la conexión I2C (SDA/SCL).\nError: {e}"
            )

    # ----------------------------------------------------------
    # Lectura principal
    # ----------------------------------------------------------

    def get_datetime(self) -> dict:
        """
        Retorna la fecha y hora actuales como diccionario.

        Retorna:
            dict con claves: year, month, day, hour, minute, second
        """
        t = self._rtc.datetime
        return {
            "year"  : t.tm_year,
            "month" : t.tm_mon,
            "day"   : t.tm_mday,
            "hour"  : t.tm_hour,
            "minute": t.tm_min,
            "second": t.tm_sec,
        }

    # ----------------------------------------------------------
    # Formatos de salida
    # ----------------------------------------------------------

    def get_timestamp_str(self) -> str:
        """
        Retorna fecha/hora en formato legible para pantalla.

        Ejemplo de salida: '2025-06-14 09:30:01'
        """
        d = self.get_datetime()
        return (
            f"{d['year']}-{d['month']:02d}-{d['day']:02d} "
            f"{d['hour']:02d}:{d['minute']:02d}:{d['second']:02d}"
        )

    def get_filename_str(self) -> str:
        """
        Retorna fecha/hora en formato seguro para nombres de archivo.
        Evita caracteres inválidos en sistemas de ficheros (sin ':' ni espacios).

        Ejemplo de salida: '2025-06-14_09-30-01'
        """
        d = self.get_datetime()
        return (
            f"{d['year']}-{d['month']:02d}-{d['day']:02d}_"
            f"{d['hour']:02d}-{d['minute']:02d}-{d['second']:02d}"
        )

    def get_hour(self) -> int:
        """Retorna solo la hora actual (0–23). Útil para análisis por franja horaria."""
        return self._rtc.datetime.tm_hour

    # ----------------------------------------------------------
    # Configuración del RTC (uso único en puesta en marcha)
    # ----------------------------------------------------------

    def set_datetime(self, year: int, month: int, day: int,
                     hour: int, minute: int, second: int):
        """
        Establece la fecha y hora del RTC.
        USAR SOLO UNA VEZ para configurar el módulo con batería nueva.

        Ejemplo:
            rtc.set_datetime(2025, 6, 14, 9, 30, 0)
        """
        self._rtc.datetime = time.struct_time(
            (year, month, day, hour, minute, second, 0, -1, -1)
        )
        print(f"[RTCSensor] Fecha/hora configurada: {self.get_timestamp_str()}")

    # ----------------------------------------------------------
    # Sincronización con hora del sistema (NUEVO)
    # ----------------------------------------------------------

    def sync_with_system(self):
        """
        Sincroniza el RTC con la hora actual del sistema.
        El sistema debe estar sincronizado con NTP o tener la hora correcta.
        
        Ejemplo de uso:
            rtc.sync_with_system()
        """
        try:
            # Obtener hora del sistema
            now = datetime.datetime.now()
            
            # Convertir a struct_time para el RTC
            system_time = time.struct_time(
                (now.year, now.month, now.day,
                 now.hour, now.minute, now.second,
                 0, -1, -1)
            )
            
            # Escribir al RTC
            self._rtc.datetime = system_time
            
            print(f"[RTCSensor] ✅ Sincronizado con sistema: {self.get_timestamp_str()}")
            return True
            
        except Exception as e:
            print(f"[RTCSensor] ❌ Error al sincronizar con sistema: {e}")
            return False
