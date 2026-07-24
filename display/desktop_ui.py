#!/usr/bin/env python3
# ============================================================
# display/desktop_ui.py — Interfaz gráfica moderna para monitoreo
# ============================================================
# Diseño:
#   - Ventana oscura con acentos naranja/ámbar
#   - Tarjetas grandes para voltaje, corriente y potencia
#   - Gráfica en tiempo real del historial de potencia
#   - Tabla de últimas lecturas + condiciones ambientales
#   - Indicador visual del estado del CSV
#
# Nota:
#   Usa Tkinter de forma nativa y, si está disponible,
#   aprovecha CustomTkinter para un aspecto más moderno.
# ============================================================

from __future__ import annotations

from collections import deque
import tkinter as tk
from tkinter import ttk

try:
    import customtkinter as ctk  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    ctk = None

from display.terminal_ui import TerminalUI

Tk = tk.Tk


class DesktopUI:
    """Interfaz gráfica basada en Tkinter con un diseño tipo dashboard."""

    def __init__(self):
        self._history: deque = deque(maxlen=20)
        self._session_file = "—"
        self._available = False
        self._root: tk.Tk | None = None
        self._terminal_fallback = TerminalUI()
        self._recording = True
        self._first_render = True

        self._timestamp_var = None
        self._session_var = None
        self._voltage_var = None
        self._current_var = None
        self._power_var = None
        self._environment_var = None
        self._status_var = None

        self._timestamp_text = "—"
        self._session_text = "Archivo CSV: —"
        self._voltage_text = "0.00 V"
        self._current_text = "0.000 A"
        self._power_text = "0.00 W"
        self._environment_text = "Temp: —  ·  Hum: —"
        self._status_text = "Grabando"

        self._tree: ttk.Treeview | None = None
        self._canvas: tk.Canvas | None = None

        try:
            self._create_window()
            self._available = True
        except Exception as exc:  # pragma: no cover - depends on display availability
            self._available = False
            self._error = str(exc)
            self._terminal_fallback.show_boot_screen()

    # ------------------------------------------------------------------
    # Configuración inicial
    # ------------------------------------------------------------------

    def set_session_file(self, filename: str):
        self._session_file = filename
        if self._available:
            self._set_text("session", f"Archivo CSV: {filename}")
        else:
            self._terminal_fallback.set_session_file(filename)

    def show_boot_screen(self):
        if self._available:
            self._set_text("timestamp", "Iniciando...")
            self._set_text("session", "Archivo CSV: preparando sesión")
            self._set_text("voltage", "0.00 V")
            self._set_text("current", "0.000 A")
            self._set_text("power", "0.00 W")
            self._set_text("environment", "Temp: —  ·  Hum: —")
            self._set_text("status", "Calibrando")
            self._refresh_window()
        else:
            self._terminal_fallback.show_boot_screen()

    # ------------------------------------------------------------------
    # Render principal
    # ------------------------------------------------------------------

    def render(self, timestamp: str, voltage: float, current: float,
               power: float, temperature: float, humidity: float,
               recording: bool = True):
        if not self._available:
            self._terminal_fallback.render(
                timestamp=timestamp,
                voltage=voltage,
                current=current,
                power=power,
                temperature=temperature,
                humidity=humidity,
            )
            return

        self._recording = recording
        self._history.append({
            "ts": timestamp,
            "v": voltage,
            "i": current,
            "p": power,
        })

        self._set_text("timestamp", timestamp)
        self._set_text("session", f"Archivo CSV: {self._session_file}")
        self._set_text("voltage", f"{voltage:6.2f} V")
        self._set_text("current", f"{current:6.3f} A")
        self._set_text("power", f"{power:6.2f} W")
        self._set_text("environment", f"Temp: {temperature:.1f} °C  ·  Hum: {humidity:.1f}%")
        self._set_text("status", "Grabando" if recording else "Pausado")

        self._refresh_window()

    # ------------------------------------------------------------------
    # Construcción de la ventana
    # ------------------------------------------------------------------

    def _create_window(self):
        if ctk is not None:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("dark-blue")
            self._root = ctk.CTk()
            self._root.title("Energy Monitor Desktop")
            self._root.geometry("1180x780")
            self._root.minsize(1024, 720)
            self._root.configure(fg_color="#0f1117")
        else:
            self._root = Tk()
            self._root.title("Energy Monitor Desktop")
            self._root.geometry("1180x780")
            self._root.minsize(1024, 720)
            self._root.configure(bg="#0f1117")

        assert self._root is not None
        self._root.option_add("*Font", "Segoe UI 10")
        self._init_stringvars()

        main = tk.Frame(self._root, bg="#0f1117")
        main.pack(fill="both", expand=True, padx=18, pady=18)

        header = tk.Frame(main, bg="#0f1117")
        header.pack(fill="x", pady=(0, 14))

        title = tk.Label(
            header,
            text="Monitor de energía",
            font=("Segoe UI", 24, "bold"),
            fg="#ffb347",
            bg="#0f1117",
            anchor="w",
        )
        title.pack(side="left")

        clock_frame = tk.Frame(header, bg="#0f1117")
        clock_frame.pack(side="right")
        tk.Label(
            clock_frame,
            textvariable=self._timestamp_var,
            font=("Segoe UI", 12, "bold"),
            fg="#f5f5f5",
            bg="#0f1117",
        ).pack(anchor="e")
        tk.Label(
            clock_frame,
            textvariable=self._session_var,
            font=("Segoe UI", 10),
            fg="#9aa0a6",
            bg="#0f1117",
        ).pack(anchor="e")

        cards = tk.Frame(main, bg="#0f1117")
        cards.pack(fill="x", pady=(0, 14))

        self._build_card(cards, "Voltaje", self._voltage_var, "#ffb347")
        self._build_card(cards, "Corriente", self._current_var, "#f4b942")
        self._build_card(cards, "Potencia", self._power_var, "#ff8c25")

        content = tk.Frame(main, bg="#0f1117")
        content.pack(fill="both", expand=True)

        left = tk.Frame(content, bg="#0f1117")
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        chart_frame = tk.LabelFrame(
            left,
            text="Historial de potencia",
            fg="#ffb347",
            bg="#161b24",
            bd=1,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
        )
        chart_frame.pack(fill="both", expand=True, pady=(0, 10))
        self._canvas = tk.Canvas(chart_frame, bg="#161b24", highlightthickness=0, height=260)
        self._canvas.pack(fill="both", expand=True, padx=10, pady=10)

        bottom = tk.Frame(content, bg="#0f1117")
        bottom.pack(side="right", fill="y")

        history_frame = tk.LabelFrame(
            bottom,
            text="Últimas lecturas",
            fg="#ffb347",
            bg="#161b24",
            bd=1,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
        )
        history_frame.pack(fill="both", padx=(0, 0), pady=(0, 10))
        self._tree = ttk.Treeview(history_frame, columns=("ts", "v", "i", "p"), show="headings", height=8)
        self._tree.heading("ts", text="Tiempo")
        self._tree.heading("v", text="V")
        self._tree.heading("i", text="I")
        self._tree.heading("p", text="P")
        self._tree.column("ts", width=140, anchor="center")
        self._tree.column("v", width=80, anchor="center")
        self._tree.column("i", width=80, anchor="center")
        self._tree.column("p", width=80, anchor="center")
        self._tree.pack(fill="both", expand=True, padx=10, pady=10)

        env_frame = tk.LabelFrame(
            bottom,
            text="Ambiente y grabación",
            fg="#ffb347",
            bg="#161b24",
            bd=1,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
        )
        env_frame.pack(fill="x")
        tk.Label(
            env_frame,
            textvariable=self._environment_var,
            font=("Segoe UI", 11),
            fg="#f5f5f5",
            bg="#161b24",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        status_row = tk.Frame(env_frame, bg="#161b24")
        status_row.pack(fill="x", padx=12, pady=(0, 10))
        indicator = tk.Label(status_row, text="●", font=("Segoe UI", 16), fg="#3ddc97", bg="#161b24")
        indicator.pack(side="left")
        tk.Label(
            status_row,
            textvariable=self._status_var,
            font=("Segoe UI", 11),
            fg="#f5f5f5",
            bg="#161b24",
        ).pack(side="left", padx=(6, 0))
        self._status_indicator = indicator

        self._refresh_window()

    def _init_stringvars(self):
        self._timestamp_var = tk.StringVar(value=self._timestamp_text)
        self._session_var = tk.StringVar(value=self._session_text)
        self._voltage_var = tk.StringVar(value=self._voltage_text)
        self._current_var = tk.StringVar(value=self._current_text)
        self._power_var = tk.StringVar(value=self._power_text)
        self._environment_var = tk.StringVar(value=self._environment_text)
        self._status_var = tk.StringVar(value=self._status_text)

    def _set_text(self, name: str, value: str):
        setattr(self, f"_{name}_text", value)
        var = getattr(self, f"_{name}_var", None)
        if var is not None:
            var.set(value)

    def _build_card(self, parent, title: str, variable: tk.StringVar, accent: str):
        frame = tk.Frame(parent, bg="#161b24", padx=14, pady=14, bd=0)
        frame.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(frame, text=title, font=("Segoe UI", 11), fg="#d4d4d4", bg="#161b24").pack(anchor="w")
        tk.Label(frame, textvariable=variable, font=("Segoe UI", 24, "bold"), fg=accent, bg="#161b24").pack(anchor="w", pady=(4, 0))
        return frame

    def _refresh_window(self):
        if self._canvas is not None:
            self._draw_chart()
        if self._tree is not None:
            self._populate_history()
        if self._status_indicator is not None:
            color = "#3ddc97" if self._recording else "#ff8c25"
            self._status_indicator.configure(fg=color)
        if self._root is not None:
            self._root.update_idletasks()
            self._root.update()

    def _populate_history(self):
        if self._tree is None:
            return
        for row in self._tree.get_children():
            self._tree.delete(row)
        for item in list(self._history)[-8:]:
            self._tree.insert(
                "",
                "end",
                values=(
                    item["ts"],
                    f"{item['v']:.2f}",
                    f"{item['i']:.3f}",
                    f"{item['p']:.2f}",
                ),
            )

    def _draw_chart(self):
        if self._canvas is None:
            return
        self._canvas.delete("all")
        width = 620
        height = 240
        pad = 30

        self._canvas.create_rectangle(0, 0, width, height, fill="#161b24", outline="#161b24")
        for y in range(4):
            y_pos = pad + (height - 2 * pad) * y / 3
            self._canvas.create_line(pad, y_pos, width - pad, y_pos, fill="#2b3242", width=1)
        for x in range(5):
            x_pos = pad + (width - 2 * pad) * x / 4
            self._canvas.create_line(x_pos, pad, x_pos, height - pad, fill="#2b3242", width=1)

        if not self._history:
            self._canvas.create_text(width // 2, height // 2, text="Sin lecturas aún", fill="#f5f5f5")
            return

        values = [entry["p"] for entry in self._history]
        max_value = max(values) if max(values) > 0 else 1.0
        min_value = min(values) if min(values) < 0 else 0.0
        if max_value == min_value:
            max_value = min_value + 1.0
        points = []
        for index, value in enumerate(values):
            x = pad + (index / max(1, len(values) - 1)) * (width - 2 * pad)
            y = height - pad - ((value - min_value) / (max_value - min_value)) * (height - 2 * pad)
            points.append((x, y))

        for idx in range(1, len(points)):
            x1, y1 = points[idx - 1]
            x2, y2 = points[idx]
            self._canvas.create_line(x1, y1, x2, y2, fill="#ffb347", width=2)

        for x, y in points:
            self._canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#ff8c25", outline="#ff8c25")
