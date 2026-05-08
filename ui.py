#!/usr/bin/env python3
"""
ui.py  —  v2.0
Industrial SCADA-style touchscreen UI for motor control.
Pure tkinter, no external UI libraries.
Buttons change color only on press, not on hover.
"""

import tkinter as tk
import time
import subprocess
from motor_daemon import MotorDaemon, CMD_STOP, CMD_UP, CMD_DOWN

# ── Refresh rate ──────────────────────────────────────────────
REFRESH_MS = 250   # UI polls status at 4Hz

# ── Color palette — industrial dark theme ─────────────────────
C_BG          = "#0d0d0d"   # Near-black background
C_PANEL       = "#141414"   # Slightly lighter panel
C_BORDER      = "#2a2a2a"   # Subtle borders
C_ACCENT      = "#c8a800"   # Amber — industrial accent
C_TEXT        = "#d0d0d0"   # Main text
C_DIM         = "#555555"   # Dimmed / label text
C_GREEN       = "#00c853"   # Connected / OK
C_RED         = "#d50000"   # Fault / disconnected
C_YELLOW      = "#ffd600"   # Warning
C_BTN_NORMAL  = "#1a1a1a"   # Button resting state
C_BTN_PRESS   = "#c8a800"   # Button pressed — amber flash
C_BTN_BORDER  = "#333333"
C_UP_TEXT     = "#00c853"
C_DOWN_TEXT   = "#d50000"

# ── Fonts ─────────────────────────────────────────────────────
F_TITLE    = ("Courier", 13, "bold")
F_BTN      = ("Courier", 20, "bold")
F_LABEL    = ("Courier",  9, "bold")
F_CONSOLE  = ("Courier", 10)
F_VALUE    = ("Courier", 10, "bold")
F_STATUS   = ("Courier", 12, "bold")
F_MOTOR    = ("Courier", 16, "bold")
F_SECTION  = ("Courier",  9, "bold")


def get_pi_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read()) / 1000:.1f}°C"
    except Exception:
        return "N/A"


def get_pi_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        h, m = divmod(int(secs), 3600)
        m, s = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return "N/A"


def get_cpu_percent() -> str:
    try:
        result = subprocess.run(
            ["top", "-bn1"],
            capture_output=True, text=True, timeout=1
        )
        for line in result.stdout.splitlines():
            if "Cpu(s)" in line or "%Cpu" in line:
                # Parse idle and subtract from 100
                parts = line.split()
                for i, p in enumerate(parts):
                    if "id" in p and i > 0:
                        idle = float(parts[i-1].replace(",", "."))
                        return f"{100 - idle:.1f}%"
    except Exception:
        pass
    return "N/A"


def state_label(state: int) -> str:
    return {CMD_STOP: "STOP", CMD_UP: "UP  ", CMD_DOWN: "DOWN"}.get(state, "????")


def fmt_session(secs: float) -> str:
    if secs <= 0:
        return "—"
    h, m = divmod(int(secs), 3600)
    m, s = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


class MotorControlApp:
    def __init__(self, root: tk.Tk, daemon: MotorDaemon):
        self.root   = root
        self.daemon = daemon
        self._ui_held = {"a": CMD_STOP, "b": CMD_STOP}
        self._build_ui()
        self._schedule_refresh()

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        self.root.title("MOTOR CONTROL  v2.0")
        self.root.configure(bg=C_BG)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.attributes(
            "-fullscreen", False))

        # ── Top status bar ──
        self._build_statusbar()

        # ── Main area ──
        main = tk.Frame(self.root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(4, 10))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=4)
        main.columnconfigure(2, weight=3)
        main.rowconfigure(0, weight=1)

        self._build_motor_panel(main, "MOTOR  A", "a", col=0)
        self._build_console(main, col=1)
        self._build_motor_panel(main, "MOTOR  B", "b", col=2)

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C_PANEL, height=42,
                       highlightbackground=C_ACCENT,
                       highlightthickness=1)
        bar.pack(fill=tk.X, padx=0, pady=0)
        bar.pack_propagate(False)

        # Left: system name
        tk.Label(bar, text="▶  MOTOR CONTROL SYSTEM  v2.0",
                 font=F_TITLE, bg=C_PANEL, fg=C_ACCENT).pack(
                     side=tk.LEFT, padx=16)

        # Right: connection pill
        self._conn_var = tk.StringVar(value="● INITIALISING")
        self._conn_lbl = tk.Label(bar, textvariable=self._conn_var,
                                  font=F_STATUS, bg=C_PANEL, fg=C_YELLOW)
        self._conn_lbl.pack(side=tk.RIGHT, padx=16)

        # Right: latency
        self._lat_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self._lat_var,
                 font=F_CONSOLE, bg=C_PANEL, fg=C_DIM).pack(
                     side=tk.RIGHT, padx=6)

    def _build_motor_panel(self, parent, label, motor_id, col):
        outer = tk.Frame(parent, bg=C_BORDER, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)

        frame = tk.Frame(outer, bg=C_PANEL)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)

        # Section header
        tk.Label(frame, text=f"━━  {label}  ━━",
                 font=F_SECTION, bg=C_PANEL, fg=C_ACCENT).grid(
                     row=0, column=0, pady=(10, 4))

        # UP button
        btn_up = tk.Button(
            frame, text="▲\nUP",
            font=F_BTN, bg=C_BTN_NORMAL, fg=C_UP_TEXT,
            activebackground=C_BTN_NORMAL,   # No hover change
            activeforeground=C_UP_TEXT,
            relief="flat", borderwidth=0,
            highlightbackground=C_BTN_BORDER,
            highlightthickness=2,
            cursor="hand2"
        )
        btn_up.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        btn_up.bind("<ButtonPress-1>",
                    lambda e, m=motor_id: self._press(m, CMD_UP, btn_up))
        btn_up.bind("<ButtonRelease-1>",
                    lambda e, m=motor_id: self._release(m, btn_up))

        # State indicator
        state_var = tk.StringVar(value="STOP")
        state_lbl = tk.Label(frame, textvariable=state_var,
                             font=F_MOTOR, bg=C_PANEL, fg=C_TEXT,
                             width=6)
        state_lbl.grid(row=2, column=0, pady=6)

        # DOWN button
        btn_down = tk.Button(
            frame, text="▼\nDOWN",
            font=F_BTN, bg=C_BTN_NORMAL, fg=C_DOWN_TEXT,
            activebackground=C_BTN_NORMAL,   # No hover change
            activeforeground=C_DOWN_TEXT,
            relief="flat", borderwidth=0,
            highlightbackground=C_BTN_BORDER,
            highlightthickness=2,
            cursor="hand2"
        )
        btn_down.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        btn_down.bind("<ButtonPress-1>",
                      lambda e, m=motor_id: self._press(m, CMD_DOWN, btn_down))
        btn_down.bind("<ButtonRelease-1>",
                      lambda e, m=motor_id: self._release(m, btn_down))

        tk.Frame(frame, bg=C_PANEL, height=8).grid(row=4, column=0)

        if motor_id == "a":
            self._state_var_a = state_var
            self._state_lbl_a = state_lbl
        else:
            self._state_var_b = state_var
            self._state_lbl_b = state_lbl

    def _build_console(self, parent, col):
        outer = tk.Frame(parent, bg=C_ACCENT, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)

        frame = tk.Frame(outer, bg=C_PANEL)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

        tk.Label(frame, text="━━  SYSTEM CONSOLE  ━━",
                 font=F_SECTION, bg=C_PANEL, fg=C_ACCENT).grid(
                     row=0, column=0, columnspan=2, pady=(10, 8))

        # Console rows: (key, label, initial, color_fn)
        self._crows = {}
        rows = [
            # ── Comms ──
            ("_hdr_comms",   "── COMMUNICATIONS ──", None, None),
            ("eth_status",   "ETH LINK",       "—",    None),
            ("latency",      "LATENCY",         "—",    None),
            ("hb_rate",      "HB RATE",         "—",    None),
            ("last_pkt_age", "LAST PKT AGE",    "—",    None),
            ("lost",         "PKTS LOST",       "0",    None),
            # ── Motors ──
            ("_hdr_motors",  "── MOTORS ──",    None,   None),
            ("motor_a",      "MOTOR A",         "STOP", None),
            ("motor_b",      "MOTOR B",         "STOP", None),
            ("cmd_source",   "CMD SOURCE",      "—",    None),
            # ── System ──
            ("_hdr_sys",     "── SYSTEM ──",    None,   None),
            ("pi_temp",      "PI TEMP",         "—",    None),
            ("cpu",          "CPU LOAD",        "—",    None),
            ("session",      "SESSION TIME",    "—",    None),
            ("uptime",       "UPTIME",          "—",    None),
            ("gpio",         "HW BUTTONS",      "—",    None),
        ]

        for i, (key, label, default, _) in enumerate(rows, start=1):
            if key.startswith("_hdr"):
                # Section divider
                tk.Label(frame, text=label, font=("Courier", 8, "bold"),
                         bg=C_PANEL, fg=C_DIM).grid(
                             row=i, column=0, columnspan=2,
                             sticky="w", padx=14, pady=(8, 2))
                continue

            tk.Label(frame, text=label + ":", font=F_LABEL,
                     bg=C_PANEL, fg=C_DIM, anchor="w").grid(
                         row=i, column=0, sticky="w", padx=14, pady=1)

            var = tk.StringVar(value=default or "—")
            lbl = tk.Label(frame, textvariable=var, font=F_VALUE,
                           bg=C_PANEL, fg=C_TEXT, anchor="w")
            lbl.grid(row=i, column=1, sticky="w", padx=4, pady=1)
            self._crows[key] = (var, lbl)

        # Quit button
        tk.Frame(frame, bg=C_BORDER, height=1).grid(
            row=len(rows) + 2, column=0, columnspan=2,
            sticky="ew", padx=10, pady=8)
        tk.Button(frame, text="[ QUIT ]",
                  font=("Courier", 10, "bold"),
                  bg=C_PANEL, fg=C_RED,
                  activebackground=C_PANEL,
                  relief="flat",
                  command=self.root.destroy,
                  cursor="hand2").grid(
                      row=len(rows) + 3, column=0,
                      columnspan=2, pady=(0, 10))

    # ── Button handlers ───────────────────────────────────────

    def _press(self, motor_id: str, direction: int, btn: tk.Button):
        btn.configure(bg=C_BTN_PRESS, fg=C_BG)
        self._ui_held[motor_id] = direction
        self.daemon.send_command(
            self._ui_held["a"], self._ui_held["b"], source="UI")

    def _release(self, motor_id: str, btn: tk.Button):
        btn.configure(bg=C_BTN_NORMAL,
                      fg=C_UP_TEXT if "UP" in str(btn.cget("text")) else C_DOWN_TEXT)
        # Restore text color properly
        text = btn.cget("text")
        btn.configure(fg=C_UP_TEXT if "UP" in text else C_DOWN_TEXT)
        self._ui_held[motor_id] = CMD_STOP
        self.daemon.send_command(
            self._ui_held["a"], self._ui_held["b"], source="UI")

    # ── Refresh ───────────────────────────────────────────────

    def _set_row(self, key: str, value: str, color: str = C_TEXT):
        if key in self._crows:
            var, lbl = self._crows[key]
            var.set(value)
            lbl.configure(fg=color)

    def _schedule_refresh(self):
        self._refresh()
        self.root.after(REFRESH_MS, self._schedule_refresh)

    def _refresh(self):
        s = self.daemon.get_status()

        # ── Status bar ──
        if s["connected"]:
            self._conn_var.set("●  LINK  OK")
            self._conn_lbl.configure(fg=C_GREEN)
            self._lat_var.set(f"RTT {s['latency_ms']} ms")
        else:
            self._conn_var.set("✖  COMMS  LOST")
            self._conn_lbl.configure(fg=C_RED)
            self._lat_var.set("")

        # ── Motor state labels ──
        def motor_color(state):
            if state == CMD_UP:   return C_GREEN
            if state == CMD_DOWN: return C_RED
            return C_DIM

        self._state_var_a.set(state_label(s["motor_a"]))
        self._state_lbl_a.configure(fg=motor_color(s["motor_a"]))
        self._state_var_b.set(state_label(s["motor_b"]))
        self._state_lbl_b.configure(fg=motor_color(s["motor_b"]))

        # ── Console rows ──
        eth_c = C_GREEN if s["connected"] else C_RED
        self._set_row("eth_status",
                      "OK" if s["connected"] else "LOST", eth_c)

        self._set_row("latency",
                      f"{s['latency_ms']} ms",
                      C_GREEN if s["latency_ms"] < 50 else C_YELLOW)

        self._set_row("hb_rate",   f"{s['hb_rate_hz']} Hz")

        age = s["last_pkt_age_ms"]
        age_c = C_GREEN if age < 300 else (C_YELLOW if age < 600 else C_RED)
        self._set_row("last_pkt_age", f"{age} ms", age_c)

        lost = s["lost_since_conn"]
        self._set_row("lost", str(lost),
                      C_RED if lost > 5 else C_TEXT)

        self._set_row("motor_a",
                      state_label(s["motor_a"]), motor_color(s["motor_a"]))
        self._set_row("motor_b",
                      state_label(s["motor_b"]), motor_color(s["motor_b"]))

        self._set_row("cmd_source", s["cmd_source"],
                      C_ACCENT if s["cmd_source"] == "HW Button" else C_TEXT)

        temp_str = get_pi_temp()
        try:
            temp_val = float(temp_str.replace("°C", ""))
            temp_c = C_RED if temp_val > 75 else (
                C_YELLOW if temp_val > 60 else C_GREEN)
        except Exception:
            temp_c = C_TEXT
        self._set_row("pi_temp", temp_str, temp_c)

        self._set_row("cpu",     get_cpu_percent())
        self._set_row("session", fmt_session(s["session_time_s"]))
        self._set_row("uptime",  get_pi_uptime())

        gpio_str = "ENABLED" if s["gpio_enabled"] else "DISABLED"
        gpio_c   = C_GREEN   if s["gpio_enabled"] else C_DIM
        self._set_row("gpio", gpio_str, gpio_c)


# ── Entry point ───────────────────────────────────────────────

def main():
    daemon = MotorDaemon()
    daemon.start()

    root = tk.Tk()
    app  = MotorControlApp(root, daemon)

    try:
        root.mainloop()
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()
