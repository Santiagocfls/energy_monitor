# ============================================================
# display/terminal_ui.py — Interfaz de usuario en terminal
# ============================================================
# DISEÑO:
#   La pantalla se divide en 3 zonas:
#
#   ┌─────────────────────────────────────────────────────────┐
#   │  ENCABEZADO: título + nombre de sesión CSV              │
#   ├─────────────────────────────────────────────────────────┤
#   │  LECTURA ACTUAL: V, I, P en tiempo real                 │
#   ├─────────────────────────────────────────────────────────┤
#   │  HISTORIAL: últimas N lecturas con timestamp del RTC    │
#   ├─────────────────────────────────────────────────────────┤
#   │  AMBIENTE: temperatura, humedad, punto cero WCS1600     │
#   └─────────────────────────────────────────────────────────┘
#
# HISTORIAL:
#   Se almacena en una lista FIFO (collections.deque) con un
#   máximo de HISTORY_ROWS entradas. Cada entrada incluye el
#   timestamp del RTC, lo que permite ver la evolución temporal
#   de las últimas lecturas sin salir del programa.
#
# TÉCNICA DE REFRESCO:
#   En lugar de os.system('clear') que parpadea, usamos secuencias
#   ANSI para mover el cursor al inicio y sobrescribir el contenido.
#   Esto produce una pantalla más suave y profesional.
# ============================================================

import os
from collections import deque
from config import HISTORY_ROWS, DECIMAL_PRECISION, CURRENT_PRECISION


# ---- Constantes de color ANSI ----
# Funcionan en la mayoría de terminales Linux (SSH, tmux, etc.)
class Color:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    CYAN   = "\033[96m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    WHITE  = "\033[97m"
    DIM    = "\033[2m"
    BLUE   = "\033[94m"


class TerminalUI:
    """
    Renderiza el dashboard de monitoreo en la terminal.

    Mantiene un historial de las últimas HISTORY_ROWS lecturas
    con sus timestamps del RTC para visualización en tiempo real.
    """

    W = 62  # Ancho interior del panel (entre los bordes │ ...)

    def __init__(self):
        self._history: deque = deque(maxlen=HISTORY_ROWS)
        self._session_file: str = "—"
        self._first_render = True

    # ----------------------------------------------------------
    # Configuración inicial
    # ----------------------------------------------------------

    def set_session_file(self, filename: str):
        """
        Informa a la UI el nombre del archivo CSV activo.
        Se muestra en el encabezado como referencia para el operador.
        """
        self._session_file = filename

    # ----------------------------------------------------------
    # Pantalla de arranque
    # ----------------------------------------------------------

    def show_boot_screen(self):
        """Muestra la pantalla de inicio durante la calibración."""
        os.system('clear')
        W = self.W
        print(Color.CYAN + "╔" + "═" * W + "╗")
        print(f"║{Color.BOLD + Color.WHITE}{'SISTEMA DE MONITOREO ENERGÉTICO':^{W}}{Color.RESET + Color.CYAN}║")
        print(f"║{'Raspberry Pi  ·  MCP3008  ·  WCS1600  ·  ZMPT101B':^{W}}║")
        print("╠" + "═" * W + "╣")
        print(f"║{Color.YELLOW}  ⚙  Iniciando calibración de sensores...{' ' * (W - 42)}{Color.CYAN}║")
        print(f"║{'  ·  Sin carga activa para mayor precisión':^{W}}║")
        print("╚" + "═" * W + "╝" + Color.RESET)
        print()

    # ----------------------------------------------------------
    # Render principal (llamar cada ~1 segundo)
    # ----------------------------------------------------------

    def render(self, timestamp: str, voltage: float, current: float,
               power: float, temperature: float, humidity: float):
        """
        Actualiza el dashboard completo en pantalla.

        Parámetros:
            timestamp   : String 'YYYY-MM-DD HH:MM:SS' del RTC
            voltage     : Voltaje RMS en V
            current     : Corriente RMS en A
            power       : Potencia aparente en W
            temperature : Temperatura en °C
            humidity    : Humedad relativa en %
        """
        # Agregar la lectura actual al historial
        self._history.appendleft({
            "ts" : timestamp,
            "v"  : voltage,
            "i"  : current,
            "p"  : power,
        })

        W = self.W

        # Construir las líneas del panel
        lines = []
        add = lines.append  # Alias para brevedad

        # ---- Encabezado ----
        add(Color.CYAN + "╔" + "═" * W + "╗")
        add(f"║{Color.BOLD + Color.WHITE}{'SISTEMA DE MONITOREO ENERGÉTICO':^{W}}{Color.RESET + Color.CYAN}║")
        add("╠" + "═" * W + "╣")

        # ---- Fecha y Hora (RTC) ----
        ts_line = f"  » {Color.YELLOW}{timestamp}{Color.CYAN}"
        ts_pad  = W - len(f"  » {timestamp}")
        add(f"║ {Color.WHITE}FECHA Y HORA (RTC){Color.CYAN}{' ' * (W - 19)}║")
        add(f"║{ts_line}{' ' * ts_pad}║")

        # ---- Mediciones actuales ----
        add("╠" + "═" * 20 + "╦" + "═" * 20 + "╦" + "═" * 20 + "╣")
        add(f"║{Color.BOLD}{'  VOLTAJE':^20}{Color.RESET + Color.CYAN}║"
            f"{Color.BOLD}{'  CORRIENTE':^20}{Color.RESET + Color.CYAN}║"
            f"{Color.BOLD}{'  POTENCIA':^20}{Color.RESET + Color.CYAN}║")
        add("╠" + "═" * 20 + "╬" + "═" * 20 + "╬" + "═" * 20 + "╣")

        # Color dinámico para corriente y potencia
        v_color = Color.GREEN  if voltage > 0   else Color.DIM
        i_color = Color.GREEN  if current > 0   else Color.DIM
        p_color = Color.YELLOW if power   > 100 else (Color.GREEN if power > 0 else Color.DIM)

        v_str = f"{voltage:>{6}.{DECIMAL_PRECISION}f} V"
        i_str = f"{current:>{6}.{CURRENT_PRECISION}f} A"
        p_str = f"{power:>{6}.{DECIMAL_PRECISION}f} W"

        add(f"║{v_color}{v_str:^20}{Color.CYAN}║"
            f"{i_color}{i_str:^20}{Color.CYAN}║"
            f"{p_color}{p_str:^20}{Color.CYAN}║")

        # ---- Historial de lecturas ----
        add("╠" + "═" * 20 + "╩" + "═" * 20 + "╩" + "═" * 20 + "╣")
        add(f"║ {Color.WHITE}HISTORIAL (últimas {HISTORY_ROWS} lecturas){Color.CYAN}"
            f"{' ' * (W - 31 - len(str(HISTORY_ROWS)))}║")
        add("╠" + "═" * W + "╣")

        # Cabecera de la tabla de historial
        header = f"  {'TIMESTAMP':<21} {'VOLTAJE':>9} {'CORRIENTE':>10} {'POTENCIA':>9}"
        add(f"║{Color.DIM}{header:<{W}}{Color.RESET + Color.CYAN}║")
        add("║" + "─" * W + "║")

        # Filas del historial (la más reciente primero)
        for i, row in enumerate(self._history):
            row_color = Color.WHITE if i == 0 else Color.DIM
            line = (
                f"  {row['ts']:<21} "
                f"{row['v']:>7.{DECIMAL_PRECISION}f} V  "
                f"{row['i']:>7.{CURRENT_PRECISION}f} A  "
                f"{row['p']:>7.{DECIMAL_PRECISION}f} W"
            )
            add(f"║{row_color}{line:<{W}}{Color.RESET + Color.CYAN}║")

        # Rellenar filas vacías si el historial aún no está lleno
        empty_rows = HISTORY_ROWS - len(self._history)
        for _ in range(empty_rows):
            add(f"║{' ' * W}║")

        # ---- Condiciones Ambientales ----
        add("╠" + "═" * W + "╣")
        add(f"║ {Color.WHITE}CONDICIONES AMBIENTALES{Color.CYAN}{' ' * (W - 24)}║")

        dht_line = (f"  » Temp: {Color.YELLOW}{temperature:.1f} °C{Color.CYAN}"
                    f"      » Humedad: {Color.YELLOW}{humidity:.1f} %{Color.CYAN}")
        dht_pad  = W - len(f"  » Temp: {temperature:.1f} °C      » Humedad: {humidity:.1f} %")
        add(f"║{dht_line}{' ' * dht_pad}║")

        ses_line = f"  » Sesión CSV: {self._session_file}"
        add(f"║{Color.DIM}{ses_line:<{W}}{Color.RESET + Color.CYAN}║")

        # ---- Pie ----
        add("╚" + "═" * W + "╝" + Color.RESET)
        add(f"{Color.DIM}  Presiona Ctrl+C para guardar y salir{Color.RESET}")

        # ---- Renderizar usando ANSI para evitar parpadeo ----
        if self._first_render:
            os.system('clear')
            self._first_render = False
        else:
            # Mover el cursor al inicio de la pantalla sin borrar
            print("\033[H", end="")

        print("\n".join(lines))
