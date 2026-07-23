# ============================================================
# utils/timing.py — Utilidades de temporización de alta resolución
# ============================================================
# CONCEPTO CLAVE:
#   Python's time.perf_counter() es el reloj de mayor resolución
#   disponible en el sistema. Se usa para medir intervalos precisos
#   de muestreo sin depender del scheduler del SO.
#
#   micros() → devuelve tiempo en microsegundos (float)
#   millis() → devuelve tiempo en milisegundos  (float)
#
#   Uso típico:
#       t0 = micros()
#       ... (esperar)
#       if micros() - t0 >= 1000:   # Han pasado 1000 µs = 1 ms
#           tomar_muestra()
# ============================================================

import time


def micros() -> float:
    """
    Retorna el tiempo actual en microsegundos (µs).
    Equivalente a micros() de Arduino.
    Resolución típica: < 1 µs en Linux con PREEMPT_RT.
    """
    return time.perf_counter() * 1_000_000.0


def millis() -> float:
    """
    Retorna el tiempo actual en milisegundos (ms).
    Equivalente a millis() de Arduino.
    """
    return time.perf_counter() * 1_000.0


def elapsed_us(since_us: float) -> float:
    """
    Calcula el tiempo transcurrido en µs desde 'since_us'.

    Parámetros:
        since_us: marca de tiempo de referencia (obtenida con micros())
    Retorna:
        Microsegundos transcurridos desde 'since_us'
    """
    return micros() - since_us


def elapsed_ms(since_ms: float) -> float:
    """
    Calcula el tiempo transcurrido en ms desde 'since_ms'.

    Parámetros:
        since_ms: marca de tiempo de referencia (obtenida con millis())
    Retorna:
        Milisegundos transcurridos desde 'since_ms'
    """
    return millis() - since_ms
