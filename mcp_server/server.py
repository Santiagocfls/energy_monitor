#!/usr/bin/env python3
# ============================================================
# server.py — Servidor MCP para el Monitor de Energía
# ============================================================
# Este servidor expone, vía MCP (Model Context Protocol), los
# archivos CSV generados por energy_monitor/main.py en
# energy_monitor/data/sessions/.
#
# Herramientas expuestas a Claude:
#   list_sessions()            -> lista todas las sesiones disponibles
#   session_summary(file)      -> estadísticas de una sesión (V, I, P, kWh)
#   estimate_cost(file, price) -> costo estimado de la sesión
#   compare_sessions(files)    -> compara varias sesiones
#   read_session(file, n)      -> primeras/últimas N filas crudas
#   detect_anomalies(file)     -> detecta lecturas fuera de rango físico
#   plot_power(file)           -> gráfica de potencia vs tiempo (imagen PNG)
#   plot_voltage_current(file) -> gráfica de voltaje y corriente (imagen PNG)
#
# EJECUCIÓN:
#   python3 server.py
#   (por defecto sirve en 0.0.0.0:8765 vía streamable-http, listo para
#    exponerse con ngrok)
# ============================================================

import os
import glob
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # sin display, servidor headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from mcp.server.fastmcp import FastMCP, Image

# ----------------------------------------------------------
# Configuración
# ----------------------------------------------------------

# Carpeta data/sessions dentro de energy_monitor (un nivel arriba de mcp_server/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSIONS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "data", "sessions"))

# Umbral físico razonable de potencia (W) para descartar picos por ruido del ADC.
# Ver config.py del proyecto: el ADC tiene ruido conocido y ha producido lecturas
# de decenas de miles de watts que NO son reales (ver sesión 2000-01-01_00-04-14
# y 2000-01-01_00-12-20 como ejemplo).
MAX_PLAUSIBLE_POWER_W = 6000.0

HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8765"))

mcp = FastMCP("energy-monitor", host=HOST, port=PORT)


# ----------------------------------------------------------
# Utilidades internas
# ----------------------------------------------------------

def _list_csv_files() -> list[str]:
    if not os.path.isdir(SESSIONS_DIR):
        return []
    return sorted(glob.glob(os.path.join(SESSIONS_DIR, "*.csv")))


def _resolve_path(filename: str) -> str:
    """
    Acepta tanto el nombre de archivo ('2026-06-14_23-18-56.csv') como
    la ruta completa, y siempre la resuelve dentro de SESSIONS_DIR
    (evita path traversal fuera de la carpeta de sesiones).
    """
    name = os.path.basename(filename)
    path = os.path.join(SESSIONS_DIR, name)
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"No se encontró la sesión '{filename}' en {SESSIONS_DIR}. "
            f"Usa list_sessions() para ver los archivos disponibles."
        )
    return path


def _load_dataframe(filename: str) -> pd.DataFrame:
    path = _resolve_path(filename)
    df = pd.read_csv(path)
    # Limpieza básica: columnas esperadas
    expected = ["timestamp", "hour", "voltage_v", "current_a", "power_w",
                "temperature_c", "humidity_pct", "zero_current_mv"]
    for col in expected:
        if col not in df.columns:
            df[col] = np.nan

    # Parseo robusto de timestamp (algunas sesiones tienen filas corruptas
    # con fechas imposibles, p. ej. día/mes fuera de rango) -> NaT y se ignoran
    # para cálculos temporales, pero no se descartan del conteo de filas.
    df["timestamp_parsed"] = pd.to_datetime(df["timestamp"], errors="coerce")

    for col in ["voltage_v", "current_a", "power_w", "temperature_c",
                "humidity_pct", "zero_current_mv"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def _valid_time_series(df: pd.DataFrame) -> pd.DataFrame:
    """Filas con timestamp válido, ordenadas cronológicamente."""
    d = df.dropna(subset=["timestamp_parsed"]).sort_values("timestamp_parsed")
    return d


def _compute_energy_kwh(df: pd.DataFrame, cap_power: bool = True) -> dict:
    """
    Integra la potencia en el tiempo (regla del trapecio) para estimar
    la energía consumida en kWh durante la sesión.

    cap_power=True descarta muestras de potencia físicamente implausibles
    (ruido del ADC / picos de calibración) antes de integrar.
    """
    d = _valid_time_series(df)
    if len(d) < 2:
        return {"energy_kwh": 0.0, "outliers_removed": 0, "duration_s": 0.0}

    power = d["power_w"].copy()
    outliers = 0
    if cap_power:
        mask = power > MAX_PLAUSIBLE_POWER_W
        outliers = int(mask.sum())
        power = power.where(~mask, np.nan)
        power = power.interpolate(limit_direction="both")

    # Segundos relativos al primer timestamp. Se usa timedelta.total_seconds()
    # en vez de castear a int64 directamente, porque pandas puede almacenar
    # datetime64 con resolución de ns, us o ms según la versión, y asumir
    # nanosegundos a ciegas produce resultados erróneos.
    t_seconds = (d["timestamp_parsed"] - d["timestamp_parsed"].iloc[0]).dt.total_seconds().to_numpy()
    _trapz = getattr(np, "trapezoid", None) or np.trapz  # NumPy 2.0+ renombró trapz -> trapezoid
    energy_ws = float(_trapz(power.to_numpy(), t_seconds))
    energy_kwh = max(energy_ws / 3600.0 / 1000.0, 0.0)
    duration_s = float(t_seconds[-1] - t_seconds[0])

    return {
        "energy_kwh": round(energy_kwh, 5),
        "outliers_removed": outliers,
        "duration_s": duration_s,
    }


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


# ----------------------------------------------------------
# Herramientas MCP
# ----------------------------------------------------------

@mcp.tool()
def list_sessions() -> str:
    """
    Lista todas las sesiones de monitoreo disponibles (archivos CSV en
    data/sessions), con su rango de fechas, número de filas y duración
    aproximada. Úsala primero para saber qué archivos existen antes de
    llamar a otras herramientas.
    """
    files = _list_csv_files()
    if not files:
        return f"No se encontraron archivos CSV en {SESSIONS_DIR}."

    lines = [f"Encontradas {len(files)} sesiones en {SESSIONS_DIR}:\n"]
    lines.append(f"{'Archivo':<32} {'Filas':>7} {'Inicio':>20} {'Fin':>20} {'Duración':>12}")
    lines.append("-" * 95)

    for path in files:
        name = os.path.basename(path)
        try:
            df = _load_dataframe(name)
        except Exception as e:
            lines.append(f"{name:<32} [error leyendo: {e}]")
            continue

        d = _valid_time_series(df)
        rows = len(df)
        if len(d) >= 1:
            start = d["timestamp_parsed"].iloc[0]
            end = d["timestamp_parsed"].iloc[-1]
            dur = (end - start).total_seconds()
            lines.append(
                f"{name:<32} {rows:>7} {str(start):>20} {str(end):>20} "
                f"{_fmt_duration(dur):>12}"
            )
        else:
            lines.append(f"{name:<32} {rows:>7} {'sin timestamps válidos':>20}")

    return "\n".join(lines)


@mcp.tool()
def session_summary(filename: str) -> str:
    """
    Calcula estadísticas de una sesión: voltaje/corriente/potencia
    promedio, mínima y máxima, energía total consumida (kWh), duración,
    y porcentaje de tiempo con carga activa.

    Parámetros:
        filename: nombre del archivo CSV, p. ej. '2026-06-14_23-18-56.csv'
                  (obtenido con list_sessions())
    """
    df = _load_dataframe(filename)
    d = _valid_time_series(df)
    energy = _compute_energy_kwh(df)

    if len(d) == 0:
        return f"'{filename}': no contiene timestamps válidos para analizar."

    active = d[d["power_w"] > 0]
    pct_active = 100.0 * len(active) / len(d) if len(d) else 0.0

    out = [
        f"Resumen de sesión: {filename}",
        f"  Periodo           : {d['timestamp_parsed'].iloc[0]}  →  {d['timestamp_parsed'].iloc[-1]}",
        f"  Duración          : {_fmt_duration(energy['duration_s'])}",
        f"  Muestras          : {len(df)} ({len(d)} con timestamp válido)",
        "",
        f"  Voltaje (V)       : min={d['voltage_v'].min():.1f}  "
        f"prom={d['voltage_v'].mean():.1f}  max={d['voltage_v'].max():.1f}",
        f"  Corriente (A)     : min={d['current_a'].min():.3f}  "
        f"prom={d['current_a'].mean():.3f}  max={d['current_a'].max():.3f}",
        f"  Potencia (W)      : min={d['power_w'].min():.1f}  "
        f"prom={d['power_w'].mean():.1f}  max={d['power_w'].max():.1f}",
        f"  Temperatura (°C)  : prom={d['temperature_c'].mean():.1f}",
        f"  Humedad (%)       : prom={d['humidity_pct'].mean():.1f}",
        "",
        f"  Tiempo con carga activa: {pct_active:.1f}%",
        f"  Energía consumida : {energy['energy_kwh']:.4f} kWh",
    ]
    if energy["outliers_removed"] > 0:
        out.append(
            f"  ⚠ Se ignoraron {energy['outliers_removed']} lecturas de potencia "
            f"> {MAX_PLAUSIBLE_POWER_W:.0f} W (ruido del ADC / picos de calibración) "
            f"antes de integrar la energía."
        )
    return "\n".join(out)


@mcp.tool()
def estimate_cost(filename: str, price_per_kwh: float, currency: str = "COP") -> str:
    """
    Estima el costo económico de la energía consumida en una sesión.

    Parámetros:
        filename: nombre del archivo CSV de la sesión.
        price_per_kwh: precio de la energía por kWh (usa la tarifa de tu
                       recibo de luz, en la moneda que prefieras).
        currency: código o símbolo de la moneda, solo para mostrarlo (default COP).
    """
    df = _load_dataframe(filename)
    energy = _compute_energy_kwh(df)
    cost = energy["energy_kwh"] * price_per_kwh

    lines = [
        f"Estimación de costo — {filename}",
        f"  Energía consumida : {energy['energy_kwh']:.4f} kWh",
        f"  Tarifa            : {price_per_kwh:.2f} {currency}/kWh",
        f"  Costo estimado    : {cost:,.2f} {currency}",
    ]
    if energy["outliers_removed"] > 0:
        lines.append(
            f"  ⚠ Cálculo excluye {energy['outliers_removed']} lecturas de potencia "
            f"anómalas (> {MAX_PLAUSIBLE_POWER_W:.0f} W)."
        )
    return "\n".join(lines)


@mcp.tool()
def compare_sessions(filenames: list[str], price_per_kwh: Optional[float] = None,
                      currency: str = "COP") -> str:
    """
    Compara energía consumida (y opcionalmente costo) entre varias sesiones.

    Parámetros:
        filenames: lista de nombres de archivos CSV a comparar.
        price_per_kwh: si se indica, también calcula el costo de cada una.
        currency: moneda a mostrar si se calcula el costo.
    """
    if not filenames:
        return "Debes indicar al menos un archivo en 'filenames'."

    rows = []
    for fname in filenames:
        try:
            df = _load_dataframe(fname)
            energy = _compute_energy_kwh(df)
            d = _valid_time_series(df)
            avg_power = d["power_w"].mean() if len(d) else 0.0
            rows.append((fname, energy["energy_kwh"], avg_power, energy["duration_s"]))
        except Exception as e:
            rows.append((fname, None, None, None))

    lines = [f"{'Sesión':<32} {'kWh':>10} {'P.prom(W)':>10} {'Duración':>12}"]
    lines.append("-" * 68)
    total_kwh = 0.0
    for fname, kwh, avgp, dur in rows:
        if kwh is None:
            lines.append(f"{fname:<32} {'ERROR':>10}")
            continue
        total_kwh += kwh
        lines.append(f"{fname:<32} {kwh:>10.4f} {avgp:>10.1f} {_fmt_duration(dur):>12}")

    lines.append("-" * 68)
    lines.append(f"{'TOTAL':<32} {total_kwh:>10.4f}")

    if price_per_kwh is not None:
        lines.append("")
        lines.append(f"Costo total estimado: {total_kwh * price_per_kwh:,.2f} {currency} "
                      f"(a {price_per_kwh:.2f} {currency}/kWh)")

    return "\n".join(lines)


@mcp.tool()
def read_session(filename: str, n_rows: int = 50, from_end: bool = False) -> str:
    """
    Devuelve las primeras (o últimas) N filas crudas de una sesión, para
    inspección rápida.

    Parámetros:
        filename: nombre del archivo CSV.
        n_rows: número de filas a mostrar (default 50).
        from_end: si es True, muestra las últimas N filas en vez de las primeras.
    """
    df = _load_dataframe(filename)
    view = df.tail(n_rows) if from_end else df.head(n_rows)
    cols = ["timestamp", "hour", "voltage_v", "current_a", "power_w",
            "temperature_c", "humidity_pct", "zero_current_mv"]
    return view[cols].to_string(index=False)


@mcp.tool()
def detect_anomalies(filename: str) -> str:
    """
    Detecta lecturas fuera de rango físico razonable en una sesión:
    voltajes muy bajos/altos, corrientes negativas, potencias implausibles
    y timestamps corruptos. Útil para evaluar la calidad de los datos
    antes de confiar en los cálculos de energía/costo.

    Parámetros:
        filename: nombre del archivo CSV.
    """
    df = _load_dataframe(filename)
    total = len(df)

    bad_ts = df["timestamp_parsed"].isna().sum()
    voltage_sag = ((df["voltage_v"] > 0) & (df["voltage_v"] < 90)).sum()
    voltage_over = (df["voltage_v"] > 135).sum()
    current_neg = (df["current_a"] < 0).sum()
    power_spike = (df["power_w"] > MAX_PLAUSIBLE_POWER_W).sum()

    lines = [
        f"Diagnóstico de calidad de datos — {filename}",
        f"  Total de filas                     : {total}",
        f"  Timestamps corruptos/no parseables : {bad_ts} ({100*bad_ts/total:.1f}%)",
        f"  Voltaje bajo (0 < V < 90)           : {voltage_sag}",
        f"  Voltaje alto (> 135 V)              : {voltage_over}",
        f"  Corriente negativa                 : {current_neg}",
        f"  Picos de potencia (> {MAX_PLAUSIBLE_POWER_W:.0f} W)         : {power_spike}",
    ]

    if bad_ts == 0 and voltage_sag == 0 and voltage_over == 0 and current_neg == 0 and power_spike == 0:
        lines.append("\n  ✓ No se detectaron anomalías evidentes.")
    else:
        lines.append(
            "\n  ⚠ Se detectaron anomalías. Revisa config.py del monitor: hay "
            "recomendaciones de hardware pendientes (impedancia de entrada, "
            "desacoplamiento) que reducirían el ruido del ADC."
        )

    return "\n".join(lines)


@mcp.tool()
def plot_power(filename: str) -> Image:
    """
    Genera una gráfica de potencia (W) vs. tiempo para una sesión y la
    devuelve como imagen PNG.

    Parámetros:
        filename: nombre del archivo CSV.
    """
    df = _load_dataframe(filename)
    d = _valid_time_series(df)
    if len(d) == 0:
        raise ValueError(f"'{filename}' no tiene timestamps válidos para graficar.")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(d["timestamp_parsed"], d["power_w"], linewidth=0.8, color="#d97706")
    ax.set_title(f"Potencia vs. tiempo — {filename}")
    ax.set_xlabel("Tiempo")
    ax.set_ylabel("Potencia (W)")
    ax.grid(alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout()

    buf_path = "/tmp/_mcp_plot_power.png"
    fig.savefig(buf_path, dpi=110)
    plt.close(fig)

    with open(buf_path, "rb") as f:
        data = f.read()
    return Image(data=data, format="png")


@mcp.tool()
def plot_voltage_current(filename: str) -> Image:
    """
    Genera una gráfica con dos ejes: voltaje (V) y corriente (A) vs.
    tiempo, para una sesión. Devuelve la imagen PNG.

    Parámetros:
        filename: nombre del archivo CSV.
    """
    df = _load_dataframe(filename)
    d = _valid_time_series(df)
    if len(d) == 0:
        raise ValueError(f"'{filename}' no tiene timestamps válidos para graficar.")

    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.plot(d["timestamp_parsed"], d["voltage_v"], color="#2563eb", linewidth=0.8, label="Voltaje (V)")
    ax1.set_xlabel("Tiempo")
    ax1.set_ylabel("Voltaje (V)", color="#2563eb")
    ax1.tick_params(axis="y", labelcolor="#2563eb")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))

    ax2 = ax1.twinx()
    ax2.plot(d["timestamp_parsed"], d["current_a"], color="#dc2626", linewidth=0.8, label="Corriente (A)")
    ax2.set_ylabel("Corriente (A)", color="#dc2626")
    ax2.tick_params(axis="y", labelcolor="#dc2626")

    fig.suptitle(f"Voltaje y Corriente — {filename}")
    fig.autofmt_xdate()
    fig.tight_layout()

    buf_path = "/tmp/_mcp_plot_vi.png"
    fig.savefig(buf_path, dpi=110)
    plt.close(fig)

    with open(buf_path, "rb") as f:
        data = f.read()
    return Image(data=data, format="png")


# ----------------------------------------------------------
# Punto de entrada
# ----------------------------------------------------------

if __name__ == "__main__":
    print(f"[energy-monitor MCP] Sirviendo sesiones desde: {SESSIONS_DIR}")
    print(f"[energy-monitor MCP] Escuchando en {HOST}:{PORT} (transporte streamable-http)")
    mcp.run(transport="streamable-http")
