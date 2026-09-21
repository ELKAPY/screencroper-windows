import os
import sys

# Clean up stale or non-existent TCL/TK environment variables from previous runs
for var in ("TCL_LIBRARY", "TK_LIBRARY"):
    val = os.environ.get(var)
    if val and not os.path.exists(val):
        del os.environ[var]

if getattr(sys, 'frozen', False):
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    for t_name, var in [('_tcl_data', 'TCL_LIBRARY'), ('_tk_data', 'TK_LIBRARY'), ('tcl', 'TCL_LIBRARY'), ('tk', 'TK_LIBRARY')]:
        cand = os.path.join(base_dir, t_name)
        if os.path.exists(cand):
            os.environ[var] = cand

import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont
import threading
from math import gcd
import subprocess
import json

# --- Localization ---
STRINGS = {
    "en": {
        "tab_presets":       "  Presets  ",
        "screen_lbl":        "Screen:",
        "scale_lbl":         "Scale:",
        "hz":                "Hz",
        "current_tag":       " (Current)",
        "active":            "Active",
        "preview":           "Preview",
        "phys_screen":       "Physical screen",
        "scale_word":        "Scale",
        "freq_word":         "Freq",
        "scale_for_res":     "Scale for this resolution:",
        "applied":           "Applied",
        "apply":             "Apply Settings",
        "err_mode":          "Failed to apply mode:\n{w}×{h} @ {freq}Hz not supported!",
        "first_run_title":   "First Launch",
        "first_run_msg":     "Create ScreenCroper shortcuts on the Desktop and Start Menu?",
        "done_title":        "Done",
        "shortcuts_ok":      "Shortcuts created successfully!",
    },
    "ru": {
        "tab_presets":       "  Пресеты  ",
        "screen_lbl":        "Экран:",
        "scale_lbl":         "Масштаб:",
        "hz":                "Гц",
        "current_tag":       " (Текущее)",
        "active":            "Активно",
        "preview":           "Предпросмотр",
        "phys_screen":       "Физический экран",
        "scale_word":        "Масштаб",
        "freq_word":         "Частота",
        "scale_for_res":     "Масштаб для этого разрешения:",
        "applied":           "Применено",
        "apply":             "Применить настройки",
        "err_mode":          "Ошибка применения режима:\n{w}×{h} @ {freq}Гц не поддерживается!",
        "first_run_title":   "Первый запуск",
        "first_run_msg":     "Создать ярлыки приложения ScreenCroper на Рабочем столе и в меню Пуск?",
        "done_title":        "Готово",
        "shortcuts_ok":      "Ярлыки успешно созданы!",
    }
}

def t(key):
    return STRINGS.get(current_lang, STRINGS["en"]).get(key, key)

# --- Windows API helpers ---
def get_special_folder(folder_id):
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, folder_id, None, 0, buf)
    return buf.value

def create_shortcut(target_path, shortcut_path, working_dir, icon_location=None):
    try:
        ps_cmd = (
            f'$WshShell = New-Object -ComObject WScript.Shell; '
            f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}"); '
            f'$Shortcut.TargetPath = "{target_path}"; '
            f'$Shortcut.WorkingDirectory = "{working_dir}"; '
        )
        if icon_location:
            ps_cmd += f'$Shortcut.IconLocation = "{icon_location}"; '
        ps_cmd += '$Shortcut.Save()'
        subprocess.run(
            ["powershell", "-Command", ps_cmd],
            shell=True,
            creationflags=0x08000000
        )
        return True
    except Exception:
        return False

# --- DEVMODEW structure ---
class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
        ("dmOrientation", ctypes.c_short), ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short), ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short), ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short), ("dmPrintQuality", ctypes.c_short),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
        ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
        ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
        ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
        ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
        ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
        ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong)
    ]

# Explicit Windows API signatures to prevent 64-bit calling convention / pointer crashes
user32 = ctypes.windll.user32
user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
user32.EnumDisplaySettingsW.restype = wintypes.BOOL
user32.ChangeDisplaySettingsW.argtypes = [ctypes.c_void_p, wintypes.DWORD]
user32.ChangeDisplaySettingsW.restype = wintypes.LONG

ENUM_CURRENT_SETTINGS = -1
CDS_UPDATEREGISTRY = 0x01
DISP_CHANGE_SUCCESSFUL = 0

def get_all_resolutions():
    user32 = ctypes.windll.user32
    i = 0
    modes = {}
    current_mode = DEVMODEW()
    current_mode.dmSize = ctypes.sizeof(DEVMODEW)
    if user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(current_mode)):
        current_bpp = current_mode.dmBitsPerPel
    else:
        current_bpp = 32
    while True:
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(None, i, ctypes.byref(mode)):
            break
        if mode.dmBitsPerPel == current_bpp:
            key = (mode.dmPelsWidth, mode.dmPelsHeight)
            freq = mode.dmDisplayFrequency
            if key not in modes or freq > modes[key]:
                modes[key] = freq
        i += 1
    res_list = sorted([(w, h, freq) for (w, h), freq in modes.items()], key=lambda x: (x[0], x[1]), reverse=True)
    return res_list if res_list else [(1920, 1080, 60)]

def get_aspect_ratio(w, h):
    if (w, h) in [(1366, 768), (1364, 768)]: return "16:9"
    divisor = gcd(w, h)
    aspect_w = w // divisor
    aspect_h = h // divisor
    if aspect_w == 8 and aspect_h == 5: return "16:10"
    return f"{aspect_w}:{aspect_h}"

def get_current_resolution_info():
    user32 = ctypes.windll.user32
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        return (mode.dmPelsWidth, mode.dmPelsHeight, mode.dmDisplayFrequency)
    return (1920, 1080, 60)

# --- Config ---
if getattr(sys, 'frozen', False):
    _APP_DIR = os.path.dirname(sys.executable)
else:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_APP_DIR, "config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass

user_config = load_config()

# Language: default English
current_lang = user_config.get("lang", "en")

presets = user_config.get("presets", [
    {"w": 2880, "h": 1920, "freq": 120, "dpi": 200, "name": "3:2 (2880 × 1920) — Scale 200%"},
    {"w": 1920, "h": 1080, "freq": 60,  "dpi": 125, "name": "16:9 (1920 × 1080) — Scale 125%"}
])

def get_preset_display_name(preset):
    w, h, freq, dpi = preset["w"], preset["h"], preset["freq"], preset["dpi"]
    ratio = get_aspect_ratio(w, h)
    return f"{ratio} ({w} × {h}) — {t('scale_word')} {dpi}%"

def get_dpi_for_resolution(w, h):
    key = f"{w}x{h}"
    if key in user_config:
        return int(user_config[key])
    return get_recommended_dpi(w, h)

def get_recommended_dpi(w, h):
    ratio = get_aspect_ratio(w, h)
    if ratio == "3:2":     return 200
    elif ratio in ["16:9", "16:10"]: return 125
    elif ratio == "4:3":   return 100
    else:                  return 100

def stop_all_animations():
    global canvas_anim_id, button_anims
    for anim_id in list(button_anims.values()):
        try:
            root.after_cancel(anim_id)
        except Exception:
            pass
    button_anims.clear()
    if canvas_anim_id:
        try:
            root.after_cancel(canvas_anim_id)
        except Exception:
            pass
        canvas_anim_id = None

def change_screen_settings(w, h, freq):
    stop_all_animations()
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    if not user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        mode.dmFields = 0
    mode.dmPelsWidth = w
    mode.dmPelsHeight = h
    mode.dmDisplayFrequency = freq
    # Set only the fields being modified to prevent invalid driver expectations
    mode.dmFields = (0x00080000 | 0x00100000 | 0x00400000)
    result = user32.ChangeDisplaySettingsW(ctypes.byref(mode), CDS_UPDATEREGISTRY)
    if result == DISP_CHANGE_SUCCESSFUL:
        dpi = get_dpi_for_resolution(w, h)
        try:
            subprocess.run(f"setdpi {dpi}", shell=True, creationflags=0x08000000)
        except Exception:
            pass
        # Defer GUI refresh slightly to allow OS to settle after display switch
        root.after(60, lambda: refresh_gui_after_change(w, h, freq))
    else:
        if root.winfo_exists() and preview_canvas.winfo_exists():
            preview_canvas.delete("all")
            preview_canvas.create_text(
                205, 80,
                text=t("err_mode").format(w=w, h=h, freq=freq),
                fill="#e81123",
                font=("Segoe UI", 12, "bold"),
                justify="center"
            )

# --- GUI root ---
root = tk.Tk()
root.title("ScreenCroper")

try:
    if getattr(sys, 'frozen', False):
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    ico_path = os.path.join(base_dir, "logo.ico")
    if os.path.exists(ico_path):
        root.iconbitmap(ico_path)
except Exception:
    pass

window_width = 450
window_height = 720
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()
x_coord = (screen_width - window_width) // 2
y_coord = (screen_height - window_height) // 2
root.geometry(f"{window_width}x{window_height}+{x_coord}+{y_coord}")
root.configure(bg="#1e1e1e")

# Window Dark Theme (DWM)
root.update_idletasks()
try:
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(root.winfo_id(), 2) # GA_ROOT
    if not hwnd:
        hwnd = root.winfo_id()
    rendering_policy = ctypes.c_int(1)
    ctypes.windll.dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    ctypes.windll.dwmapi.DwmSetWindowAttribute.restype = wintypes.LONG
    res = ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering_policy), ctypes.sizeof(rendering_policy))
    if res != 0:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(rendering_policy), ctypes.sizeof(rendering_policy))
except Exception:
    pass

BG = "#1e1e1e"
FG = "#e0e0e0"
ACCENT = "#007acc"
ACCENT_ACTIVE = "#1f97e5"
CARD_BG = "#2d2d2d"
CARD_BG_ACTIVE = "#3e3e3e"

style = ttk.Style()
style.theme_use('clam')
style.configure("TNotebook", background=BG, borderwidth=0, lightcolor=BG, darkcolor=BG, tabmargins=(0, 0, 0, 0))
style.configure("TNotebook.Tab", background=CARD_BG, foreground=FG, borderwidth=0, focuscolor="", padding=(12, 6), lightcolor=BG, darkcolor=BG, font=("Segoe UI", 10, "bold"))
style.map("TNotebook.Tab", background=[("selected", BG), ("active", CARD_BG_ACTIVE)], foreground=[("selected", ACCENT)])
style.configure("TFrame", background=BG)
style.configure("TButton", background=CARD_BG, foreground=FG, borderwidth=0, focuscolor="", padding=8, font=("Segoe UI", 10, "bold"))
style.map("TButton", background=[("active", CARD_BG_ACTIVE), ("pressed", ACCENT)], foreground=[("active", "#ffffff")])
style.configure("TCombobox", fieldbackground=CARD_BG, background=CARD_BG, foreground=FG, arrowcolor=FG, borderwidth=0)
style.map("TCombobox",
          fieldbackground=[("readonly", CARD_BG), ("active", CARD_BG_ACTIVE)],
          background=[("readonly", CARD_BG), ("active", CARD_BG_ACTIVE)],
          foreground=[("readonly", FG)])
root.option_add("*TCombobox*Listbox.background", CARD_BG)
root.option_add("*TCombobox*Listbox.foreground", FG)
root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
style.configure("Vertical.TScrollbar", background=CARD_BG, troughcolor=BG, borderwidth=0, arrowsize=0)

# --- UI Styling & Native Canvas Rounded Buttons ---
class PresetCard(tk.Canvas):
    def __init__(self, parent, text="", select_cmd=None, delete_cmd=None, height=36, radius=7):
        super().__init__(parent, height=height, bg=BG, bd=0, highlightthickness=0, cursor="hand2")
        self.select_cmd = select_cmd
        self.delete_cmd = delete_cmd
        self.height = height
        self.radius = radius
        self.text = text

        self.poly_id = self.create_polygon([0,0,0,0], smooth=True, fill=CARD_BG, outline="#383838")
        self.text_id = self.create_text(14, height // 2, text=text, fill=FG, font=("Segoe UI", 10, "bold"), anchor="w")

        self.del_bg_id = self.create_oval(0, 0, 0, 0, fill="", outline="")
        self.del_id = self.create_text(0, 0, text="×", fill="#888888", font=("Segoe UI", 12, "bold"))

        self.bind("<Configure>", self._on_resize)
        self.bind("<Enter>", self._on_card_enter)
        self.bind("<Leave>", self._on_card_leave)
        self.bind("<Button-1>", self._on_card_click)

        self.tag_bind(self.del_id, "<Enter>", self._on_del_enter)
        self.tag_bind(self.del_id, "<Leave>", self._on_del_leave)
        self.tag_bind(self.del_id, "<Button-1>", self._on_del_click)
        self.tag_bind(self.del_bg_id, "<Enter>", self._on_del_enter)
        self.tag_bind(self.del_bg_id, "<Leave>", self._on_del_leave)
        self.tag_bind(self.del_bg_id, "<Button-1>", self._on_del_click)

    def _on_resize(self, event):
        w = event.width
        h = self.height
        pts = draw_round_rect_points(1, 1, w - 2, h - 2, self.radius)
        self.coords(self.poly_id, *pts)
        del_x = w - 18
        del_y = h // 2
        self.coords(self.del_id, del_x, del_y)
        self.coords(self.del_bg_id, del_x - 11, del_y - 11, del_x + 11, del_y + 11)

    def _on_card_enter(self, e):
        self.itemconfigure(self.poly_id, fill=CARD_BG_ACTIVE)
    def _on_card_leave(self, e):
        self.itemconfigure(self.poly_id, fill=CARD_BG)
    def _on_card_click(self, e):
        if self.select_cmd:
            self.select_cmd()

    def _on_del_enter(self, e):
        self.itemconfigure(self.del_bg_id, fill="#4d1f1f", outline="#882222")
        self.itemconfigure(self.del_id, fill="#ff5555")
    def _on_del_leave(self, e):
        self.itemconfigure(self.del_bg_id, fill="", outline="")
        self.itemconfigure(self.del_id, fill="#888888")
    def _on_del_click(self, e):
        if self.delete_cmd:
            self.delete_cmd()
        return "break"

def draw_round_rect_points(x1, y1, x2, y2, r):
    r = max(2, min(int(r), int(abs(x2 - x1)) // 2, int(abs(y2 - y1)) // 2))
    return [
        x1 + r, y1, x1 + r, y1,
        x2 - r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r, x2, y1 + r,
        x2, y2 - r, x2, y2 - r,
        x2, y2, x2 - r, y2, x2 - r, y2,
        x1 + r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y2 - r,
        x1, y1 + r, x1, y1 + r, x1, y1
    ]

def draw_round_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = draw_round_rect_points(x1, y1, x2, y2, r)
    return canvas.create_polygon(points, **kwargs, smooth=True)

class RoundedButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, width=None, height=34, radius=7,
                 bg_color=CARD_BG, hover_bg=CARD_BG_ACTIVE, active_bg=ACCENT, disabled_bg="#1f1f1f",
                 fg_color=FG, hover_fg="#ffffff", active_fg="#ffffff", disabled_fg="#4a4a4a",
                 outline="#383838", active_outline=ACCENT, disabled_outline="#2a2a2a",
                 font=("Segoe UI", 9, "bold"), padx=14, cursor="hand2", anchor="center", **kwargs):
        self.btn_font = font
        self.parent_bg = parent.cget("bg") if hasattr(parent, "cget") and "bg" in parent.keys() else BG
        self.command = command
        self.radius = radius
        self.height = height
        self.width_param = width
        self.padx = padx
        self.anchor = anchor

        self.bg_color = bg_color
        self.hover_bg = hover_bg
        self.active_bg = active_bg
        self.disabled_bg = disabled_bg

        self.fg_color = fg_color
        self.hover_fg = hover_fg
        self.active_fg = active_fg
        self.disabled_fg = disabled_fg

        self.outline = outline
        self.active_outline = active_outline
        self.disabled_outline = disabled_outline

        self.is_active = False
        self.is_disabled = False
        self.is_hovered = False

        super().__init__(parent, height=height, bg=self.parent_bg,
                         bd=0, highlightthickness=0, cursor=cursor, **kwargs)

        self.calc_w = self._measure_width(text)
        self.configure(width=self.calc_w)

        self.poly_id = draw_round_rect(self, 1, 1, self.calc_w - 2, height - 2, radius,
                                       fill=bg_color, outline=outline, width=1)
        tx = self.padx if self.anchor == "w" else (self.calc_w // 2)
        self.text_id = self.create_text(tx, height // 2, text=text, fill=fg_color, font=font, anchor=self.anchor)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _measure_width(self, text):
        if self.width_param:
            return self.width_param
        try:
            f = tkfont.Font(font=self.btn_font)
            req = f.measure(text) + 2 * self.padx
        except Exception:
            req = len(text) * 9 + 2 * self.padx
        return max(req, 26)

    def set_text(self, text):
        self.calc_w = self._measure_width(text)
        self.configure(width=self.calc_w)
        self.coords(self.text_id, self.calc_w // 2, self.height // 2)
        self.itemconfigure(self.text_id, text=text)
        self.delete(self.poly_id)
        self.poly_id = draw_round_rect(self, 1, 1, self.calc_w - 2, self.height - 2, self.radius,
                                       fill=self.bg_color, outline=self.outline, width=1)
        self.tag_lower(self.poly_id)
        self._update_appearance()

    def set_state(self, state):
        self.is_disabled = (state == "disabled")
        self.configure(cursor="" if self.is_disabled else "hand2")
        self._update_appearance()

    def set_active(self, active):
        self.is_active = active
        self._update_appearance()

    def configure(self, cnf=None, **kwargs):
        if "text" in kwargs:
            self.set_text(kwargs.pop("text"))
        if "state" in kwargs:
            self.set_state(kwargs.pop("state"))
        if "fg" in kwargs or "foreground" in kwargs:
            val = kwargs.pop("fg", None) if "fg" in kwargs else kwargs.pop("foreground", None)
            self.fg_color = val
            self.itemconfigure(self.text_id, fill=val)
        if "bg" in kwargs or "background" in kwargs:
            val = kwargs.pop("bg", None) if "bg" in kwargs else kwargs.pop("background", None)
            self.bg_color = val
            self.itemconfigure(self.poly_id, fill=val)
        if kwargs:
            super().configure(cnf, **kwargs)

    config = configure

    def cget(self, key):
        if key == "state":
            return "disabled" if self.is_disabled else "normal"
        if key == "text":
            return self.itemcget(self.text_id, "text")
        if key in ["bg", "background"]:
            return self.bg_color
        if key in ["fg", "foreground"]:
            return self.fg_color
        return super().cget(key)

    def _update_appearance(self):
        if self.is_disabled:
            fill = self.disabled_bg
            fg = self.disabled_fg
            out = self.disabled_outline
        elif self.is_active:
            fill = self.active_bg
            fg = self.active_fg
            out = self.active_outline
        elif self.is_hovered:
            fill = self.hover_bg
            fg = self.hover_fg
            out = self.outline
        else:
            fill = self.bg_color
            fg = self.fg_color
            out = self.outline

        self.itemconfigure(self.poly_id, fill=fill, outline=out)
        self.itemconfigure(self.text_id, fill=fg)

    def _on_enter(self, e):
        if not self.is_disabled:
            self.is_hovered = True
            self._update_appearance()

    def _on_leave(self, e):
        self.is_hovered = False
        self._update_appearance()

    def _on_click(self, e):
        if not self.is_disabled and self.command:
            self.command()

# --- Animations ---
def interpolate_color(color1, color2, progress):
    try:
        r1, g1, b1 = int(color1[1:3], 16), int(color1[3:5], 16), int(color1[5:7], 16)
        r2, g2, b2 = int(color2[1:3], 16), int(color2[3:5], 16), int(color2[5:7], 16)
        r = int(r1 + (r2 - r1) * progress)
        g = int(g1 + (g2 - g1) * progress)
        b = int(b1 + (b2 - b1) * progress)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return color2

button_anims = {}

def animate_button_bg(btn, target_color):
    if not root.winfo_exists():
        return
    try:
        if not btn.winfo_exists():
            return
        start_color = btn.cget("bg")
    except Exception:
        return
    if start_color == target_color:
        return
    btn_id = id(btn)
    if btn_id in button_anims:
        try:
            root.after_cancel(button_anims[btn_id])
        except Exception:
            pass
        del button_anims[btn_id]
    steps = 8
    step_time = 120 // steps

    def step_anim(step):
        if not root.winfo_exists() or not btn.winfo_exists():
            if btn_id in button_anims:
                del button_anims[btn_id]
            return
        if step > steps:
            try:
                btn.configure(bg=target_color)
            except Exception:
                pass
            if btn_id in button_anims:
                del button_anims[btn_id]
            return
        current_color = interpolate_color(start_color, target_color, step / steps)
        try:
            btn.configure(bg=current_color)
        except Exception:
            return
        if root.winfo_exists() and btn.winfo_exists():
            button_anims[btn_id] = root.after(step_time, lambda: step_anim(step + 1))

    step_anim(1)

canvas_anim_id = None
current_coords = None
current_fill = None
current_outline = None

def draw_preview_static(sx0, sy0, sx1, sy1, fill_color, outline_color, text_content):
    if not root.winfo_exists() or not preview_canvas.winfo_exists():
        return
    try:
        preview_canvas.delete("all")
        canvas_w = 410
        canvas_h = 160
        if not all_res:
            return
        max_w, max_h = all_res[0][0], all_res[0][1]
        pad_x, pad_y = 20, 25
        avail_w = canvas_w - 2 * pad_x
        avail_h = canvas_h - 2 * pad_y
        scale = min(avail_w / max_w, avail_h / max_h)
        phys_w = max_w * scale
        phys_h = max_h * scale
        x0 = pad_x + (avail_w - phys_w) / 2
        y0 = pad_y + (avail_h - phys_h) / 2
        x1 = x0 + phys_w
        y1 = y0 + phys_h
        preview_canvas.create_rectangle(x0, y0, x1, y1, outline="#666666", dash=(4, 4), width=2)
        preview_canvas.create_text(x0, y0 - 12, text=f"{t('phys_screen')} ({max_w}×{max_h})", fill="#a0a0a0", anchor="w", font=("Segoe UI", 9, "bold"))
        preview_canvas.create_rectangle(sx0, sy0, sx1, sy1, fill=fill_color, outline=outline_color, width=3)
        preview_canvas.create_text(
            (x0 + x1) / 2, (y0 + y1) / 2,
            text=text_content,
            fill="#ffffff",
            font=("Segoe UI", 11, "bold"),
            justify="center"
        )
    except Exception:
        pass

def animate_preview_to(w, h, freq, label_text=""):
    global canvas_anim_id, current_coords, current_fill, current_outline
    if not root.winfo_exists() or not preview_canvas.winfo_exists():
        return
    canvas_w = 410
    canvas_h = 160
    if not all_res:
        return
    max_w, max_h = all_res[0][0], all_res[0][1]
    pad_x, pad_y = 20, 25
    avail_w = canvas_w - 2 * pad_x
    avail_h = canvas_h - 2 * pad_y
    scale = min(avail_w / max_w, avail_h / max_h)
    phys_w = max_w * scale
    phys_h = max_h * scale
    x0 = pad_x + (avail_w - phys_w) / 2
    y0 = pad_y + (avail_h - phys_h) / 2
    sel_w = w * scale
    sel_h = h * scale
    tx0 = x0 + (phys_w - sel_w) / 2
    ty0 = y0 + (phys_h - sel_h) / 2
    tx1 = tx0 + sel_w
    ty1 = ty0 + sel_h

    if label_text == "_current_":
        t_fill = "#1e3a27"
        t_outline = "#38a169"
        text_prefix = t("active")
    else:
        t_fill = "#1a365d"
        t_outline = "#3182ce"
        text_prefix = t("preview")

    dpi = get_dpi_for_resolution(w, h)
    ratio = get_aspect_ratio(w, h)
    target_text = f"{text_prefix}: {w} × {h} ({ratio})\n{t('scale_word')}: {dpi}%  |  {t('freq_word')}: {freq} {t('hz')}"

    if canvas_anim_id:
        try:
            root.after_cancel(canvas_anim_id)
        except Exception:
            pass
        canvas_anim_id = None
    if current_coords is None:
        current_coords = [tx0, ty0, tx1, ty1]
        current_fill = t_fill
        current_outline = t_outline

    steps = 8
    step_time = 120 // steps

    def step_anim(step):
        global canvas_anim_id, current_coords, current_fill, current_outline
        if not root.winfo_exists() or not preview_canvas.winfo_exists():
            canvas_anim_id = None
            return
        if step > steps:
            current_coords = [tx0, ty0, tx1, ty1]
            current_fill = t_fill
            current_outline = t_outline
            draw_preview_static(tx0, ty0, tx1, ty1, t_fill, t_outline, target_text)
            canvas_anim_id = None
            return
        progress = step / steps
        cx0 = current_coords[0] + (tx0 - current_coords[0]) * progress
        cy0 = current_coords[1] + (ty0 - current_coords[1]) * progress
        cx1 = current_coords[2] + (tx1 - current_coords[2]) * progress
        cy1 = current_coords[3] + (ty1 - current_coords[3]) * progress
        c_fill = interpolate_color(current_fill, t_fill, progress)
        c_outline = interpolate_color(current_outline, t_outline, progress)
        draw_preview_static(cx0, cy0, cx1, cy1, c_fill, c_outline, target_text)
        if root.winfo_exists() and preview_canvas.winfo_exists():
            canvas_anim_id = root.after(step_time, lambda: step_anim(step + 1))

    step_anim(1)

all_res = get_all_resolutions()

current_res_info = get_current_resolution_info()
current_applied_res = (current_res_info[0], current_res_info[1])
current_applied_freq = current_res_info[2]
current_applied_dpi = get_dpi_for_resolution(current_applied_res[0], current_applied_res[1])
selected_res_info = [current_applied_res[0], current_applied_res[1], current_applied_freq]
buttons_dict = {}

def refresh_gui_after_change(w, h, freq):
    global current_applied_res, current_applied_freq, current_applied_dpi
    current_applied_res = (w, h)
    current_applied_freq = freq
    current_applied_dpi = get_dpi_for_resolution(w, h)
    on_select_resolution(w, h, freq)

def on_select_resolution(w, h, freq):
    global selected_res_info
    selected_res_info = [w, h, freq]
    dpi = get_dpi_for_resolution(w, h)
    dpi_combobox.set(f"{dpi}%")
    for (bw, bh), btn in buttons_dict.items():
        btn_dpi = get_dpi_for_resolution(bw, bh)
        btn_text = f"{bw} × {bh} ({btn_dpi}%)"
        if (bw, bh) == current_applied_res:
            btn_text += t("current_tag")
        btn.configure(text=btn_text)
        is_sel = (bw, bh) == (w, h)
        target_color = ACCENT if is_sel else CARD_BG
        target_fg = "#ffffff" if is_sel else FG
        btn.configure(fg=target_fg)
        animate_button_bg(btn, target_color)
    if (w, h) == current_applied_res and dpi == current_applied_dpi:
        animate_preview_to(w, h, freq, "_current_")
        set_apply_btn_state(False, t("applied"))
    else:
        animate_preview_to(w, h, freq, "_preview_")
        set_apply_btn_state(True, t("apply"))

def on_dpi_combo_change(event=None):
    val_str = dpi_combobox.get()
    digits = "".join([c for c in val_str if c.isdigit()])
    if not digits:
        return
    val = max(100, min(500, int(digits)))
    w, h, freq = selected_res_info
    user_config[f"{w}x{h}"] = val
    on_select_resolution(w, h, freq)

def on_apply_click():
    w, h, freq = selected_res_info
    val_str = dpi_combobox.get()
    digits = "".join([c for c in val_str if c.isdigit()])
    val = max(100, min(500, int(digits) if digits else 100))
    user_config[f"{w}x{h}"] = val
    save_config(user_config)
    change_screen_settings(w, h, freq)

# --- Scrollable Tab Control ---
class ScrollableNotebook(tk.Frame):
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, bg=BG, *args, **kwargs)
        self._tabs = {}
        self._tab_order = []
        self.current_tab = None
        self.selected_text = None
        self._scroll_anim_id = None

        self.header_frame = tk.Frame(self, bg=BG)
        self.header_frame.pack(fill="x", side="top", pady=(0, 8))

        # Left scroll button on the left
        self.nav_left = RoundedButton(
            self.header_frame, text="‹", width=28, height=32, radius=6,
            command=self.scroll_left, font=("Segoe UI", 11, "bold"), padx=6
        )
        self.nav_left.pack(side="left", fill="y", padx=(0, 4))

        # Right scroll button on the right
        self.nav_right = RoundedButton(
            self.header_frame, text="›", width=28, height=32, radius=6,
            command=self.scroll_right, font=("Segoe UI", 11, "bold"), padx=6
        )
        self.nav_right.pack(side="right", fill="y", padx=(4, 0))

        self.canvas = tk.Canvas(self.header_frame, bg=BG, height=36, borderwidth=0, highlightthickness=0)
        self.tabs_container = tk.Frame(self.canvas, bg=BG)
        self.window_id = self.canvas.create_window((0, 0), window=self.tabs_container, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)

        self.tabs_container.bind("<Configure>", self._on_container_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.tabs_container.bind("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if not self.winfo_exists():
            return "break"
        delta = int(-1 * (event.delta / 120))
        cur = self.canvas.xview()[0]
        step = 0.08 * delta
        self.smooth_scroll_to(cur + step)
        return "break"

    def smooth_scroll_to(self, target_frac):
        target_frac = max(0.0, min(1.0, target_frac))
        if self._scroll_anim_id:
            try:
                root.after_cancel(self._scroll_anim_id)
            except Exception:
                pass
            self._scroll_anim_id = None

        steps = 6
        step_time = 12

        def step_fn(s, start_frac):
            if not self.winfo_exists() or not self.canvas.winfo_exists():
                return
            if s > steps:
                self.canvas.xview_moveto(target_frac)
                self._update_scroll_buttons()
                self._scroll_anim_id = None
                return
            prog = s / steps
            # Smooth ease-out curve
            cur_prog = 1.0 - (1.0 - prog) * (1.0 - prog)
            curr = start_frac + (target_frac - start_frac) * cur_prog
            self.canvas.xview_moveto(curr)
            self._update_scroll_buttons()
            self._scroll_anim_id = root.after(step_time, lambda: step_fn(s + 1, start_frac))

        start = self.canvas.xview()[0]
        step_fn(1, start)

    def scroll_left(self):
        cur = self.canvas.xview()[0]
        self.smooth_scroll_to(cur - 0.15)

    def scroll_right(self):
        cur = self.canvas.xview()[0]
        self.smooth_scroll_to(cur + 0.15)

    def _on_container_configure(self, event=None):
        self._update_scroll()

    def _on_canvas_configure(self, event=None):
        self._update_scroll()

    def _update_scroll(self):
        if not self.winfo_exists():
            return
        self.tabs_container.update_idletasks()
        req_w = self.tabs_container.winfo_reqwidth()
        self.canvas.configure(scrollregion=(0, 0, req_w, 36))
        self._update_scroll_buttons()

    def _update_scroll_buttons(self):
        if not self.winfo_exists():
            return
        xview = self.canvas.xview()
        if xview[0] <= 0.005:
            self.nav_left.set_state("disabled")
        else:
            self.nav_left.set_state("normal")

        if xview[1] >= 0.995:
            self.nav_right.set_state("disabled")
        else:
            self.nav_right.set_state("normal")

    def add(self, child, text=""):
        clean_text = text.strip()
        btn = RoundedButton(
            self.tabs_container, text=clean_text, height=32, radius=7,
            command=lambda: self.select(child), font=("Segoe UI", 9, "bold"), padx=12
        )
        btn.pack(side="left", padx=(0, 4))

        def _tab_wheel(e):
            return self._on_mousewheel(e)

        btn.bind("<MouseWheel>", _tab_wheel)

        self._tabs[child] = {"text": clean_text, "btn": btn}
        self._tab_order.append(child)

        # Restore previously selected tab if matching
        if self.selected_text and (clean_text == self.selected_text or
                                   (self.selected_text in ["Presets", "Пресеты"] and clean_text in ["Presets", "Пресеты"])):
            self.select(child)
        elif self.current_tab is None:
            self.select(child)
        self._update_scroll()

    def select(self, child):
        if child not in self._tabs:
            return
        if self.current_tab and self.current_tab in self._tabs:
            old_btn = self._tabs[self.current_tab]["btn"]
            old_btn.set_active(False)
            self.current_tab.pack_forget()

        self.current_tab = child
        self.selected_text = self._tabs[child]["text"]
        btn = self._tabs[child]["btn"]
        btn.set_active(True)
        child.pack(fill="both", expand=True, side="top")
        self._scroll_to_tab(btn)
        self._update_scroll_buttons()

    def _scroll_to_tab(self, btn):
        self.tabs_container.update_idletasks()
        try:
            bx1 = btn.winfo_x()
            bw = btn.winfo_width()
            bx2 = bx1 + bw
            cw = self.canvas.winfo_width()
            total_w = self.tabs_container.winfo_reqwidth()
            if total_w <= cw:
                return
            x_vis_left = self.canvas.canvasx(0)
            x_vis_right = x_vis_left + cw
            if bx1 < x_vis_left:
                target = max(0.0, (bx1 - 6) / total_w)
                self.smooth_scroll_to(target)
            elif bx2 > x_vis_right:
                target = min(1.0, (bx2 - cw + 6) / total_w)
                self.smooth_scroll_to(target)
        except Exception:
            pass
        self._update_scroll_buttons()

    def tabs(self):
        return list(self._tab_order)

    def forget(self, child):
        if child in self._tabs:
            data = self._tabs[child]
            try:
                data["btn"].destroy()
            except Exception:
                pass
            if self.current_tab == child:
                child.pack_forget()
                self.current_tab = None
            try:
                child.destroy()
            except Exception:
                pass
            del self._tabs[child]
            if child in self._tab_order:
                self._tab_order.remove(child)
        self._update_scroll()

# --- Notebook rebuild ---
def _on_canvas_mousewheel(event, canvas):
    if root.winfo_exists() and canvas.winfo_exists():
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

def rebuild_notebook():
    global button_anims, canvas_anim_id, all_res, buttons_dict
    stop_all_animations()

    for tab in notebook.tabs():
        try:
            notebook.forget(tab)
        except Exception:
            pass

    all_res = get_all_resolutions()
    buttons_dict = {}

    # Presets tab
    preset_frame = ttk.Frame(notebook)
    notebook.add(preset_frame, text=t("tab_presets"))
    preset_canvas = tk.Canvas(preset_frame, borderwidth=0, highlightthickness=0, bg=BG)
    preset_scrollbar = ttk.Scrollbar(preset_frame, orient="vertical", command=preset_canvas.yview)
    preset_scrollable = ttk.Frame(preset_canvas)
    preset_scrollable.bind("<Configure>", lambda e, c=preset_canvas: c.configure(scrollregion=c.bbox("all")))
    preset_canvas.create_window((0, 0), window=preset_scrollable, anchor="nw")
    preset_canvas.configure(yscrollcommand=preset_scrollbar.set)
    preset_canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
    preset_scrollbar.pack(side="right", fill="y")
    
    def _on_preset_mousewheel(e):
        preset_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        return "break"
    preset_canvas.bind("<MouseWheel>", _on_preset_mousewheel)
    preset_scrollable.bind("<MouseWheel>", _on_preset_mousewheel)

    constructor_frame = tk.Frame(preset_scrollable, bg=BG)
    constructor_frame.pack(fill="x", padx=10, pady=(5, 12))

    res_label_w = tk.Label(constructor_frame, text=t("screen_lbl"), font=("Segoe UI", 9, "bold"), fg=FG, bg=BG)
    res_label_w.grid(row=0, column=0, sticky="w", padx=(0, 2), pady=2)
    res_options = [f"{w}×{h} @ {freq}{t('hz')}" for w, h, freq in all_res]
    preset_res_combo = ttk.Combobox(constructor_frame, values=res_options, width=16, font=("Segoe UI", 9, "bold"), state="readonly")
    preset_res_combo.grid(row=0, column=1, padx=(0, 8), pady=2)
    if res_options:
        preset_res_combo.set(f"{current_applied_res[0]}×{current_applied_res[1]} @ {current_applied_freq}{t('hz')}")

    scale_label_w = tk.Label(constructor_frame, text=t("scale_lbl"), font=("Segoe UI", 9, "bold"), fg=FG, bg=BG)
    scale_label_w.grid(row=0, column=2, sticky="w", padx=(0, 2), pady=2)
    dpi_values_list = ["100%", "125%", "150%", "175%", "200%", "225%", "250%", "300%", "350%", "400%", "450%", "500%"]
    preset_scale_combo = ttk.Combobox(constructor_frame, values=dpi_values_list, width=6, font=("Segoe UI", 9, "bold"))
    preset_scale_combo.grid(row=0, column=3, padx=(0, 8), pady=2)
    preset_scale_combo.set(f"{current_applied_dpi}%")

    create_btn = RoundedButton(
        constructor_frame, text="+", width=30, height=28, radius=6,
        command=lambda: on_add_preset_from_constructor(preset_res_combo.get(), preset_scale_combo.get()),
        font=("Segoe UI", 10, "bold"), padx=4
    )
    create_btn.grid(row=0, column=4, pady=2)

    for idx, preset in enumerate(presets):
        pw, ph = preset["w"], preset["h"]
        pfreq, pdpi = preset["freq"], preset["dpi"]
        pname = get_preset_display_name(preset)
        card = PresetCard(
            preset_scrollable, text=pname, height=36, radius=7,
            select_cmd=lambda w=pw, h=ph, freq=pfreq, dpi=pdpi: on_select_preset(w, h, freq, dpi),
            delete_cmd=lambda i=idx: on_delete_preset(i)
        )
        card.pack(fill="x", padx=10, pady=4)

        def make_preset_handlers(c_card, w, h, freq):
            def on_enter(e):
                animate_preview_to(w, h, freq, "_preview_")
            def on_leave(e):
                is_cur = (selected_res_info[0], selected_res_info[1]) == current_applied_res
                animate_preview_to(selected_res_info[0], selected_res_info[1], selected_res_info[2],
                                   "_current_" if is_cur else "_preview_")
            return on_enter, on_leave

        on_p_enter, on_p_leave = make_preset_handlers(card, pw, ph, pfreq)
        card.bind("<Enter>", on_p_enter, add="+")
        card.bind("<Leave>", on_p_leave, add="+")
        card.bind("<MouseWheel>", _on_preset_mousewheel)

    # Resolution tabs by aspect ratio
    grouped_res = {}
    for w, h, freq in all_res:
        ratio = get_aspect_ratio(w, h)
        if ratio not in grouped_res:
            grouped_res[ratio] = []
        grouped_res[ratio].append((w, h, freq))

    priority_formats = ["3:2", "16:9", "16:10", "4:3"]
    sorted_formats = sorted(grouped_res.keys(), key=lambda x: priority_formats.index(x) if x in priority_formats else 99)

    for fmt in sorted_formats:
        resolutions = grouped_res[fmt]
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=f"  {fmt}  ")
        canvas = tk.Canvas(frame, borderwidth=0, highlightthickness=0, bg=BG)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.pack(side="right", fill="y")

        def _make_res_wheel(c):
            def _w(e):
                c.yview_scroll(int(-1 * (e.delta / 120)), "units")
                return "break"
            return _w
        res_wheel = _make_res_wheel(canvas)
        canvas.bind("<MouseWheel>", res_wheel)
        scrollable_frame.bind("<MouseWheel>", res_wheel)

        for w, h, freq in resolutions:
            dpi = get_dpi_for_resolution(w, h)
            btn_text = f"{w} × {h} ({dpi}%)"
            is_sel = (w, h) == (selected_res_info[0], selected_res_info[1])
            if (w, h) == current_applied_res:
                btn_text += t("current_tag")
            btn = RoundedButton(
                scrollable_frame, text=btn_text, height=36, radius=7,
                active_bg=ACCENT, active_outline=ACCENT,
                font=("Segoe UI", 10, "bold"), padx=12,
                command=lambda width=w, height=h, frequency=freq: on_select_resolution(width, height, frequency)
            )
            btn.set_active(is_sel)
            btn.pack(pady=4, padx=10, fill="x")
            btn.bind("<MouseWheel>", res_wheel)
            buttons_dict[(w, h)] = btn

            def make_hover_handlers(button, width, height, frequency):
                def on_enter(e):
                    animate_preview_to(width, height, frequency, "_preview_")
                def on_leave(e):
                    is_sel_current = (selected_res_info[0], selected_res_info[1]) == current_applied_res
                    animate_preview_to(selected_res_info[0], selected_res_info[1], selected_res_info[2],
                                       "_current_" if is_sel_current else "_preview_")
                return on_enter, on_leave

            on_enter, on_leave = make_hover_handlers(btn, w, h, freq)
            btn.bind("<Enter>", on_enter, add="+")
            btn.bind("<Leave>", on_leave, add="+")

# --- Preset handlers ---
def on_add_preset_from_constructor(res_str, scale_str):
    try:
        res_part, freq_part = res_str.split("@")
        w_str, h_str = res_part.split("×")
        w = int(w_str.strip())
        h = int(h_str.strip())
        freq = int("".join([c for c in freq_part if c.isdigit()]))
    except Exception:
        return
    digits = "".join([c for c in scale_str if c.isdigit()])
    dpi = max(100, min(500, int(digits) if digits else 100))
    ratio = get_aspect_ratio(w, h)
    name = f"{ratio} ({w} × {h}) — {t('scale_word')} {dpi}%"
    preset = {"w": w, "h": h, "freq": freq, "dpi": dpi, "name": name}
    exists = any(p["w"] == w and p["h"] == h and p["dpi"] == dpi for p in presets)
    if not exists:
        presets.append(preset)
        user_config["presets"] = presets
        save_config(user_config)
        rebuild_notebook()

def on_delete_preset(idx):
    if 0 <= idx < len(presets):
        presets.pop(idx)
        user_config["presets"] = presets
        save_config(user_config)
        rebuild_notebook()

def on_select_preset(w, h, freq, dpi):
    user_config[f"{w}x{h}"] = dpi
    dpi_combobox.set(f"{dpi}%")
    on_select_resolution(w, h, freq)

def check_and_create_shortcuts():
    from tkinter import messagebox
    try:
        root.deiconify(); root.focus_force()
        root.attributes("-topmost", True)
    except Exception:
        pass
    answer = messagebox.askyesno(t("first_run_title"), t("first_run_msg"), parent=root)
    try:
        root.attributes("-topmost", False)
    except Exception:
        pass
    if answer:
        desktop = get_special_folder(0)
        start_menu = get_special_folder(2)
        exe_path = sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.argv[0])
        working_dir = os.path.dirname(exe_path)
        
        # Определяем путь к иконке для ярлыка
        if getattr(sys, 'frozen', False):
            icon_location = f"{exe_path},0"
        else:
            icon_location = os.path.join(working_dir, "logo.ico")
            
        create_shortcut(exe_path, os.path.join(desktop, "ScreenCroper.lnk"), working_dir, icon_location)
        create_shortcut(exe_path, os.path.join(start_menu, "ScreenCroper.lnk"), working_dir, icon_location)
        messagebox.showinfo(t("done_title"), t("shortcuts_ok"), parent=root)
    user_config["first_run"] = False
    save_config(user_config)

def do_restart_explorer():
    def _do_restart():
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass
        try:
            subprocess.run("taskkill /f /im explorer.exe", shell=True, creationflags=0x08000000, capture_output=True)
        except Exception:
            pass
        try:
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            explorer_dir = os.path.join(local_app_data, "Microsoft", "Windows", "Explorer")
            if os.path.exists(explorer_dir):
                for f in os.listdir(explorer_dir):
                    if f.startswith("iconcache_") and f.endswith(".db"):
                        try: os.remove(os.path.join(explorer_dir, f))
                        except Exception: pass
            old_cache = os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "IconCache.db")
            if os.path.exists(old_cache):
                try: os.remove(old_cache)
                except Exception: pass
        except Exception:
            pass
        try:
            subprocess.Popen("explorer.exe", shell=True)
        except Exception:
            pass
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass
    threading.Thread(target=_do_restart, daemon=True).start()

def set_lang(lang):
    global current_lang
    current_lang = lang
    user_config["lang"] = lang
    save_config(user_config)
    lang_btn.configure(text="EN" if lang == "ru" else "RU")
    scale_label.configure(text=t("scale_for_res"))
    w, h, freq = selected_res_info
    dpi = get_dpi_for_resolution(w, h)
    if (w, h) == current_applied_res and dpi == current_applied_dpi:
        set_apply_btn_state(False, t("applied"))
    else:
        set_apply_btn_state(True, t("apply"))
    rebuild_notebook()
    on_select_resolution(selected_res_info[0], selected_res_info[1], selected_res_info[2])

# --- Build UI ---
top_frame = tk.Frame(root, bg=BG)
top_frame.pack(fill="x", padx=10, pady=(6, 2))

lang_btn = RoundedButton(
    top_frame, text="EN" if current_lang == "ru" else "RU",
    command=lambda: set_lang("ru" if current_lang == "en" else "en"),
    height=28, radius=6, font=("Segoe UI", 9, "bold"), padx=12
)
lang_btn.pack(side="right")

notebook = ScrollableNotebook(root)
notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

bottom_frame = tk.Frame(root, bg=BG)
bottom_frame.pack(fill="x", padx=10, pady=(0, 10), side="bottom")

preview_canvas = tk.Canvas(bottom_frame, width=410, height=160, bg="#121212",
                            borderwidth=0, highlightthickness=1, highlightbackground="#333333")
preview_canvas.pack(fill="x", pady=(0, 10))

scale_frame = tk.Frame(bottom_frame, bg=BG)
scale_frame.pack(fill="x", pady=(0, 10))

scale_label = tk.Label(scale_frame, text=t("scale_for_res"), font=("Segoe UI", 10, "bold"), fg=FG, bg=BG)
scale_label.pack(side="left")

dpi_values = ["100%", "125%", "150%", "175%", "200%", "225%", "250%", "300%", "350%", "400%", "450%", "500%"]
dpi_combobox = ttk.Combobox(scale_frame, values=dpi_values, width=8, font=("Segoe UI", 10, "bold"))
dpi_combobox.pack(side="right")
dpi_combobox.bind("<<ComboboxSelected>>", on_dpi_combo_change)
dpi_combobox.bind("<Return>", on_dpi_combo_change)
dpi_combobox.bind("<FocusOut>", on_dpi_combo_change)

# Button row: Apply | ↺
btn_row = tk.Frame(bottom_frame, bg=BG)
btn_row.pack(fill="x")

apply_btn = RoundedButton(
    btn_row, text=t("applied"), height=38, radius=8,
    active_bg=ACCENT, active_outline=ACCENT_ACTIVE,
    font=("Segoe UI", 10, "bold"), command=on_apply_click
)
apply_btn.pack(side="left", fill="x", expand=True)

restart_btn = RoundedButton(
    btn_row, text="↺", width=38, height=38, radius=8,
    font=("Segoe UI", 11, "bold"), command=do_restart_explorer, padx=4
)
restart_btn.pack(side="left", padx=(6, 0))

def set_apply_btn_state(enabled, text):
    if not enabled:
        apply_btn.set_text(text)
        apply_btn.set_state("disabled")
    else:
        apply_btn.set_text(text)
        apply_btn.set_state("normal")
        apply_btn.set_active(True)

rebuild_notebook()
on_select_resolution(current_applied_res[0], current_applied_res[1], current_applied_freq)

first_run = user_config.get("first_run", True)
if first_run:
    root.after(500, check_and_create_shortcuts)

if __name__ == "__main__":
    root.mainloop()