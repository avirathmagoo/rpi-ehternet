#!/usr/bin/env python3
"""
ui.py  —  v4.0
Changes from v3.2:
  - Light theme (white bg, black text) for sunlight readability
  - Bigger FIRE button; console reduced to Connection, CPU temp, Latency
  - FIRE is hold-to-activate (press=relay ON, release=relay OFF)
  - Motor B buttons labelled LEFT / RIGHT instead of UP / DOWN
  - Timer slider 0–30s: if >0, a single press/release fires for that duration
  - Timer mode sends hold packets for the slider duration, then auto-releases
"""

import tkinter as tk
import tkinter.messagebox as msgbox
import time
import subprocess
from motor_daemon import MotorDaemon, CMD_STOP, CMD_UP, CMD_DOWN

REFRESH_MS = 100   # Faster refresh for hold-state responsiveness

# ── Light colour palette ───────────────────────────────────────
C_BG          = "#f0f0f0"
C_PANEL       = "#ffffff"
C_BORDER      = "#cccccc"
C_ACCENT      = "#1a1a8c"
C_TEXT        = "#111111"
C_DIM         = "#555555"
C_GREEN       = "#007a00"
C_RED         = "#cc0000"
C_YELLOW      = "#b07000"
C_BTN_NORMAL  = "#e8e8e8"
C_BTN_PRESS   = "#1a1a8c"
C_BTN_BORDER  = "#999999"
C_UP_TEXT     = "#007a00"
C_DOWN_TEXT   = "#cc0000"
C_SHUTDOWN    = "#8b0000"
C_FIRE_IDLE   = "#dddddd"
C_FIRE_PRESS  = "#cc0000"
C_FIRE_PRESS2 = "#ff4444"  # brighter when timer-countdown active

# ── Fonts ─────────────────────────────────────────────────────
F_TITLE   = ("Courier", 20, "bold")
F_BTN     = ("Courier", 33, "bold")
F_FIRE    = ("Courier", 42, "bold")
F_LABEL   = ("Courier", 17, "bold")
F_CONSOLE = ("Courier", 15)
F_VALUE   = ("Courier", 20, "bold")
F_STATUS  = ("Courier", 20, "bold")
F_MOTOR   = ("Courier", 24, "bold")
F_SECTION = ("Courier", 17, "bold")
F_SLIDER  = ("Courier", 17)


def get_pi_temp() -> str:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return f"{int(f.read()) / 1000:.1f}°C"
    except Exception:
        return "N/A"


def state_label(state: int) -> str:
    return {CMD_STOP: "STOP", CMD_UP: "UP  ", CMD_DOWN: "DOWN"}.get(state, "????")


class MotorControlApp:
    def __init__(self, root: tk.Tk, daemon: MotorDaemon):
        self.root   = root
        self.daemon = daemon

        self._ui_held        = {"a": CMD_STOP, "b": CMD_STOP}

        # FIRE hold state
        self._fire_held      = False      # True while finger is on button (manual hold)
        self._fire_timer_end = 0.0        # epoch time when timed hold expires (0=no timer)
        self._fire_active    = False      # relay is currently commanded ON

        self._build_ui()
        self._schedule_refresh()

    # ── UI Construction ───────────────────────────────────────

    def _build_ui(self):
        self.root.title("OPTICAL FIBER MOTOR CONTROL  v4.0")
        self.root.configure(bg=C_BG)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))

        self._build_statusbar()

        main = tk.Frame(self.root, bg=C_BG)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=4)
        main.columnconfigure(2, weight=3)
        main.rowconfigure(0, weight=1)

        self._build_motor_panel(main, "MOTOR  A", "a", col=0, up_label="▲\nUP", dn_label="▼\nDOWN",
                                up_color=C_UP_TEXT, dn_color=C_DOWN_TEXT)
        self._build_console(main, col=1)
        self._build_motor_panel(main, "MOTOR  B", "b", col=2, up_label="◀\nLEFT", dn_label="▶\nRIGHT",
                                up_color="#0044cc", dn_color="#884400")

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C_ACCENT, height=60)
        bar.pack(fill=tk.X)
        bar.pack_propagate(False)

        tk.Label(bar, text="▶  OPTICAL FIBER MOTOR CONTROL AND TRIGGER  v4.0",
                 font=F_TITLE, bg=C_ACCENT, fg="#ffffff").pack(side=tk.LEFT, padx=20)

        self._conn_var = tk.StringVar(value="● INITIALISING")
        self._conn_lbl = tk.Label(bar, textvariable=self._conn_var,
                                  font=F_STATUS, bg=C_ACCENT, fg="#ffff00")
        self._conn_lbl.pack(side=tk.RIGHT, padx=20)

    def _build_motor_panel(self, parent, label, motor_id, col,
                           up_label, dn_label, up_color, dn_color):
        outer = tk.Frame(parent, bg=C_BORDER, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew", padx=5, pady=2)

        frame = tk.Frame(outer, bg=C_PANEL)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.rowconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)

        tk.Label(frame, text=f"━━  {label}  ━━",
                 font=F_SECTION, bg=C_PANEL, fg=C_ACCENT).grid(row=0, column=0, pady=(10, 4))

        btn_up = tk.Button(frame, text=up_label, font=F_BTN,
                           bg=C_BTN_NORMAL, fg=up_color,
                           activebackground=C_BTN_PRESS, activeforeground="#ffffff",
                           relief="flat", borderwidth=0,
                           highlightbackground=C_BTN_BORDER, highlightthickness=2,
                           cursor="hand2")
        btn_up.grid(row=1, column=0, sticky="nsew", padx=12, pady=4)
        btn_up.bind("<ButtonPress-1>",   lambda e, m=motor_id: self._press(m, CMD_UP, btn_up, up_color))
        btn_up.bind("<ButtonRelease-1>", lambda e, m=motor_id: self._release(m, btn_up, up_color))

        state_var = tk.StringVar(value="STOP")
        state_lbl = tk.Label(frame, textvariable=state_var,
                             font=F_MOTOR, bg=C_PANEL, fg=C_DIM, width=6)
        state_lbl.grid(row=2, column=0, pady=6)

        btn_down = tk.Button(frame, text=dn_label, font=F_BTN,
                             bg=C_BTN_NORMAL, fg=dn_color,
                             activebackground=C_BTN_PRESS, activeforeground="#ffffff",
                             relief="flat", borderwidth=0,
                             highlightbackground=C_BTN_BORDER, highlightthickness=2,
                             cursor="hand2")
        btn_down.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        btn_down.bind("<ButtonPress-1>",   lambda e, m=motor_id: self._press(m, CMD_DOWN, btn_down, dn_color))
        btn_down.bind("<ButtonRelease-1>", lambda e, m=motor_id: self._release(m, btn_down, dn_color))

        tk.Frame(frame, bg=C_PANEL, height=8).grid(row=4, column=0)

        if motor_id == "a":
            self._state_var_a = state_var
            self._state_lbl_a = state_lbl
        else:
            self._state_var_b = state_var
            self._state_lbl_b = state_lbl

    def _build_console(self, parent, col):
        outer = tk.Frame(parent, bg=C_ACCENT, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew", padx=5, pady=2)

        frame = tk.Frame(outer, bg=C_PANEL)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=2)  # FIRE button takes more space
        frame.rowconfigure(1, weight=1)  # Slider takes some space
        frame.rowconfigure(4, weight=0)  # Info frame is minimal

        # FIRE button — MUCH bigger, full width, takes vertical space
        fire_outer = tk.Frame(frame, bg=C_BORDER, padx=2, pady=2)
        fire_outer.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 6))
        fire_outer.columnconfigure(0, weight=1)
        fire_outer.rowconfigure(0, weight=1)

        self._fire_btn = tk.Button(
            fire_outer, text="🔴  FIRE",
            font=F_FIRE,
            bg=C_FIRE_IDLE, fg=C_TEXT,
            activebackground=C_FIRE_PRESS, activeforeground="#ffffff",
            relief="flat", borderwidth=0,
            cursor="hand2", pady=24,
        )
        self._fire_btn.grid(row=0, column=0, sticky="nsew")
        self._fire_btn.bind("<ButtonPress-1>",   self._fire_press)
        self._fire_btn.bind("<ButtonRelease-1>", self._fire_release)

        # Timer slider — bigger, better use of space
        slider_frame = tk.Frame(frame, bg=C_PANEL)
        slider_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))
        slider_frame.columnconfigure(1, weight=1)
        slider_frame.rowconfigure(0, weight=1)

        tk.Label(slider_frame, text="TIMER:", font=F_SLIDER,
                 bg=C_PANEL, fg=C_DIM).grid(row=0, column=0, padx=(0, 6), sticky="w")

        self._timer_var = tk.IntVar(value=0)
        self._timer_slider = tk.Scale(
            slider_frame, from_=0, to=30,
            orient=tk.HORIZONTAL, variable=self._timer_var,
            bg=C_PANEL, fg=C_TEXT, troughcolor="#dddddd",
            highlightthickness=0, bd=0,
            font=F_SLIDER, showvalue=False,
            cursor="hand2", length=250, width=28,
        )
        self._timer_slider.grid(row=0, column=1, sticky="nsew", padx=(0, 8))

        self._timer_lbl = tk.Label(slider_frame, text="0 s",
                                   font=F_VALUE, bg=C_PANEL, fg=C_GREEN, width=5)
        self._timer_lbl.grid(row=0, column=2, padx=(0, 4), sticky="e")
        self._timer_var.trace_add("write", self._on_timer_change)

        # Countdown label
        self._countdown_var = tk.StringVar(value="")
        tk.Label(frame, textvariable=self._countdown_var,
                 font=F_SLIDER, bg=C_PANEL, fg=C_RED).grid(
                     row=2, column=0, pady=(2, 2))

        # Separator
        tk.Frame(frame, bg=C_BORDER, height=2).grid(row=3, column=0, sticky="ew", padx=10, pady=4)

        # ── Slim console: Connection, Latency, CPU Temp ──
        info_frame = tk.Frame(frame, bg=C_PANEL)
        info_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=4)
        info_frame.columnconfigure(1, weight=1)

        rows = [
            ("conn",    "CONNECTION"),
            ("latency", "LATENCY"),
            ("temp",    "CPU TEMP"),
        ]
        self._crows = {}
        for i, (key, lbl_text) in enumerate(rows):
            tk.Label(info_frame, text=lbl_text + ":",
                     font=F_LABEL, bg=C_PANEL, fg=C_DIM, anchor="w").grid(
                         row=i, column=0, sticky="w", pady=3)
            var = tk.StringVar(value="—")
            lbl = tk.Label(info_frame, textvariable=var,
                           font=F_VALUE, bg=C_PANEL, fg=C_TEXT, anchor="w")
            lbl.grid(row=i, column=1, sticky="w", padx=6)
            self._crows[key] = (var, lbl)

        # Separator (no spacer — buttons come right after)
        tk.Frame(frame, bg=C_BORDER, height=2).grid(row=5, column=0, sticky="ew", padx=10, pady=4)

        # Buttons (compact)
        tk.Button(frame, text="[ QUIT ]", font=("Courier", 15, "bold"),
                  bg=C_PANEL, fg=C_DIM, activebackground=C_PANEL,
                  relief="flat", command=self._quit, cursor="hand2").grid(row=6, column=0, pady=(2, 2))

        tk.Button(frame, text="⏻  SHUTDOWN PI", font=F_SECTION,
                  bg=C_SHUTDOWN, fg="#ffffff",
                  activebackground=C_SHUTDOWN, activeforeground="#ffffff",
                  relief="flat", command=self._confirm_shutdown, cursor="hand2").grid(
                      row=7, column=0, sticky="ew", padx=12, pady=(0, 8))

    # ── Timer slider callback ─────────────────────────────────

    def _on_timer_change(self, *_):
        v = self._timer_var.get()
        self._timer_lbl.configure(text=f"{v} s")
        # Timer label turns green when at 0, otherwise dim
        color = C_GREEN if v == 0 else C_DIM
        self._timer_lbl.configure(fg=color)

    # ── Motor button handlers ─────────────────────────────────

    def _press(self, motor_id: str, direction: int, btn: tk.Button, orig_fg: str):
        btn.configure(bg=C_BTN_PRESS, fg="#ffffff")
        self._ui_held[motor_id] = direction
        self.daemon.send_command(self._ui_held["a"], self._ui_held["b"], source="UI")

    def _release(self, motor_id: str, btn: tk.Button, orig_fg: str):
        btn.configure(bg=C_BTN_NORMAL, fg=orig_fg)
        self._ui_held[motor_id] = CMD_STOP
        self.daemon.send_command(self._ui_held["a"], self._ui_held["b"], source="UI")

    # ── FIRE button handlers ──────────────────────────────────

    def _fire_press(self, event=None):
        timer_secs = self._timer_var.get()

        if timer_secs > 0:
            # Timed mode: one press starts a timed fire; ignore if already counting
            if self._fire_timer_end > 0:
                return
            self._fire_timer_end = time.time() + timer_secs
            self._fire_held      = False   # not manual hold; timer drives it
        else:
            # Manual hold mode
            self._fire_held = True

        self._fire_active = True
        self.daemon.send_fire_hold(source="UI")
        self._fire_btn.configure(bg=C_FIRE_PRESS, fg="#ffffff")

    def _fire_release(self, event=None):
        if self._fire_timer_end > 0:
            return   # Timed mode — release is ignored; timer controls end
        # Manual hold mode — stop on release
        self._fire_held   = False
        self._fire_active = False
        self.daemon.send_fire_off(source="UI")
        self._fire_btn.configure(bg=C_FIRE_IDLE, fg=C_TEXT)
        self._countdown_var.set("")

    # ── Helpers ───────────────────────────────────────────────

    def _set_row(self, key: str, value: str, color: str = C_TEXT):
        if key in self._crows:
            var, lbl = self._crows[key]
            var.set(value)
            lbl.configure(fg=color)

    def _quit(self):
        self.daemon.stop()
        self.root.destroy()

    def _confirm_shutdown(self):
        if msgbox.askyesno("Shutdown", "Shutdown the Raspberry Pi?\n\nAll motor commands will stop.",
                           icon=msgbox.WARNING, default=msgbox.NO):
            self.daemon.stop()
            subprocess.run(["sudo", "shutdown", "-h", "now"])

    # ── Refresh loop ──────────────────────────────────────────

    def _schedule_refresh(self):
        self._refresh()
        self.root.after(REFRESH_MS, self._schedule_refresh)

    def _refresh(self):
        s = self.daemon.get_status()

        # ── Status bar ──
        if not s["socket_ready"]:
            self._conn_var.set("◌  WAITING FOR NETWORK")
            self._conn_lbl.configure(fg="#ffff00")
        elif s["connected"]:
            self._conn_var.set("●  LINK  OK")
            self._conn_lbl.configure(fg="#00ff44")
        else:
            self._conn_var.set("✖  COMMS  LOST")
            self._conn_lbl.configure(fg="#ff4444")

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
        if not s["socket_ready"]:
            self._set_row("conn", "NO SOCKET", C_DIM)
        elif s["connected"]:
            self._set_row("conn", "LINK OK", C_GREEN)
        else:
            self._set_row("conn", "LOST", C_RED)

        if s["connected"]:
            lat = s["latency_ms"]
            self._set_row("latency", f"{lat} ms",
                          C_GREEN if lat < 50 else C_YELLOW)
        else:
            self._set_row("latency", "—", C_DIM)

        temp_str = get_pi_temp()
        try:
            tv = float(temp_str.replace("°C", ""))
            tc = C_RED if tv > 75 else (C_YELLOW if tv > 60 else C_GREEN)
        except Exception:
            tc = C_TEXT
        self._set_row("temp", temp_str, tc)

        # ── FIRE timer countdown ──
        now = time.time()
        if self._fire_timer_end > 0:
            remaining = self._fire_timer_end - now
            if remaining > 0:
                self._countdown_var.set(f"FIRING  {remaining:.1f}s")
                self._fire_btn.configure(bg=C_FIRE_PRESS2, fg="#ffffff")
                # Keep sending hold packets via daemon (daemon handles periodic send)
                self.daemon.send_fire_hold(source="UI")
            else:
                # Timer expired — release
                self._fire_timer_end = 0.0
                self._fire_active    = False
                self.daemon.send_fire_off(source="UI")
                self._fire_btn.configure(bg=C_FIRE_IDLE, fg=C_TEXT)
                self._countdown_var.set("")


# ── Entry point ───────────────────────────────────────────────

def main():
    daemon = MotorDaemon()
    daemon.start()

    root = tk.Tk()
    MotorControlApp(root, daemon)

    try:
        root.mainloop()
    finally:
        daemon.stop()


if __name__ == "__main__":
    main()