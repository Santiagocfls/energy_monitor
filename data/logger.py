# ============================================================
# data/logger.py — Registro de datos en archivo CSV por sesión
# ============================================================
# RESPONSABILIDAD:
#   Crear un archivo CSV con timestamp de inicio y guardar
#   cada lectura con su timestamp real del RTC.
#
# ESTRUCTURA DEL CSV:
#   timestamp,hour,voltage,current,power,temperature,humidity
#
# USO:
#   logger = DataLogger(start_timestamp="2025-06-14_09-30-01")
#   logger.log(timestamp, hour, voltage, current, power, temp, hum)
#   logger.close()
# ============================================================

import os
import csv
from datetime import datetime


class DataLogger:
    """
    Registra los datos de monitoreo en un archivo CSV.

    Atributos:
        session_dir (str): Directorio donde se guardan las sesiones.
        filepath (str): Ruta completa al archivo CSV de la sesión.
        writer (csv.DictWriter): Escritor CSV con cabeceras.
        record_count (int): Contador de registros guardados.
    """

    def __init__(self, start_timestamp: str):
        """
        Crea un nuevo archivo CSV para la sesión.

        El archivo se guarda en data/sessions/ con el formato:
            data/sessions/YYYY-MM-DD_HH-MM-SS.csv

        Args:
            start_timestamp: Timestamp de inicio en formato filename.
                             Ej: '2025-06-14_09-30-01'
        """
        # Directorio base para sesiones
        self.session_dir = "data/sessions"
        os.makedirs(self.session_dir, exist_ok=True)

        # Construir la ruta del archivo CSV
        filename = f"{start_timestamp}.csv"
        self.filepath = os.path.join(self.session_dir, filename)

        # Inicializar el archivo CSV con cabeceras (sin zero_mv)
        self.file = open(self.filepath, mode="w", newline="")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=[
                "timestamp",
                "hour",
                "voltage",
                "current",
                "power",
                "temperature",
                "humidity"
            ]
        )
        self.writer.writeheader()
        self.file.flush()

        self.record_count = 0
        print(f"  [DataLogger] Sesión iniciada → {self.filepath}")

    def log(self, timestamp: str, hour: int, voltage: float,
            current: float, power: float, temperature: float,
            humidity: float):
        """
        Guarda una lectura completa en el archivo CSV.

        Args:
            timestamp: Fecha/hora en formato 'YYYY-MM-DD HH:MM:SS'
            hour: Hora extraída (0-23) para análisis rápido
            voltage: Voltaje RMS en voltios
            current: Corriente RMS en amperios
            power: Potencia en watts
            temperature: Temperatura en °C
            humidity: Humedad relativa en %
        """
        self.writer.writerow({
            "timestamp": timestamp,
            "hour": hour,
            "voltage": f"{voltage:.2f}",
            "current": f"{current:.3f}",
            "power": f"{power:.2f}",
            "temperature": f"{temperature:.1f}",
            "humidity": f"{humidity:.1f}",
        })
        self.file.flush()
        self.record_count += 1

    def close(self):
        """
        Cierra el archivo CSV correctamente.
        Muestra el total de registros guardados.
        """
        if hasattr(self, "file") and not self.file.closed:
            self.file.close()
            print(f"  [DataLogger] Sesión cerrada → {self.filepath}")
            print(f"  [DataLogger] Total de registros guardados: {self.record_count}")

    def __del__(self):
        """Método destructor: asegura que el archivo se cierre."""
        if hasattr(self, "file") and not self.file.closed:
            self.file.close()
