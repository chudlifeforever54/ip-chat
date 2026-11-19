import sys
import traceback

_crash_root = None   # set once the real Tk root exists, so later errors can pop up
                      # a window alongside it instead of a brand new one


def _show_crash_window(text, parent=None):
    """Best-effort error window with the full traceback and a Copy button - the only
    way to ever see an error once the program runs as a console-less .pyw. Returns
    False (does nothing else) if tkinter truly isn't available to show it with."""
    try:
        import tkinter as _tk
    except Exception:
        return False
    try:
        win = _tk.Toplevel(parent) if parent is not None else _tk.Tk()
        win.title("IP Chat - error")
        win.geometry("640x420")
        try:
            win.attributes("-topmost", True)
        except _tk.TclError:
            pass
        _tk.Label(win, text="IP Chat ran into an error. Copy it below and send it to "
                             "whoever made this program.",
                  anchor="w", justify="left", padx=10, pady=8).pack(fill="x")
        box = _tk.Frame(win)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        sb = _tk.Scrollbar(box)
        txt = _tk.Text(box, wrap="word", yscrollcommand=sb.set, font=("Consolas", 9))
        sb.config(command=txt.yview)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        def copy():
            win.clipboard_clear()
            win.clipboard_append(text)
            copy_btn.config(text="Copied!")
            win.after(1500, lambda: copy_btn.config(text="Copy"))

        row = _tk.Frame(win)
        row.pack(fill="x", padx=10, pady=(0, 10))
        copy_btn = _tk.Button(row, text="Copy", command=copy, width=10)
        copy_btn.pack(side="left")
        _tk.Button(row, text="Close", command=win.destroy, width=10).pack(side="left", padx=(8, 0))
        win.lift()
        win.focus_force()
        if parent is None:
            win.mainloop()   # nothing else is running an event loop at this point
        return True
    except Exception:
        return False


def _pause_on_crash(kind, value, tb):
    """Top-level crash, e.g. before the GUI exists yet. Show it in a window - a .pyw
    build has no console for a printed traceback to land in - falling back to the
    old print-and-wait behaviour only if a window truly can't be shown."""
    text = "".join(traceback.format_exception(kind, value, tb))
    try:
        print(text, file=sys.stderr)
    except Exception:
        pass
    if not _show_crash_window(text):
        print("\n" + "=" * 60)
        print("IP Chat crashed. Copy the error above (select it, then right-click)")
        print("and send it to whoever made this program.")
        print("=" * 60)
        try:
            input("\nPress Enter to close this window...")
        except (EOFError, RuntimeError, OSError):
            pass


def _report_tk_callback_exception(kind, value, tb):
    """Wired up as the running app's report_callback_exception - this is where almost
    every in-app error actually surfaces (button clicks, timers, network callbacks
    marshalled onto the GUI thread), and unlike a top-level crash the app keeps
    running afterward, so this one never blocks on mainloop()."""
    text = "".join(traceback.format_exception(kind, value, tb))
    try:
        print(text, file=sys.stderr)
    except Exception:
        pass
    _show_crash_window(text, parent=_crash_root)


_crash_queue = None   # a queue.Queue(), created once queue is imported below


def _report_thread_exception(args):
    """threading.excepthook target: an error in a background networking thread
    reaches neither sys.excepthook nor Tk's callback hook, so without this it would
    just end the thread in silence. Tk isn't thread-safe, so this only ever queues
    the text - _poll_crash_queue (running on the GUI thread) is what shows it."""
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    try:
        print(text, file=sys.stderr)
    except Exception:
        pass
    if _crash_queue is not None:
        _crash_queue.put(text)


def _poll_crash_queue():
    """Runs on the GUI thread (scheduled via root.after) and shows any crash text that
    background threads queued up since the last check."""
    try:
        while True:
            _show_crash_window(_crash_queue.get_nowait(), parent=_crash_root)
    except Exception:
        pass
    if _crash_root is not None:
        _crash_root.after(400, _poll_crash_queue)


sys.excepthook = _pause_on_crash
try:
    import threading as _threading_early
    import queue as _queue_early
    _crash_queue = _queue_early.Queue()
    _threading_early.excepthook = _report_thread_exception
except Exception:
    pass

import atexit
import collections
import colorsys
import ctypes
import hashlib
import hmac
import importlib.util
import itertools
import json
import os
import queue
import re
import secrets
import socket
import string
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request
from tkinter import filedialog, messagebox

CREATE_NO_WINDOW = 0x08000000
# Optional packages: (name, module to look for, what it does, pip arguments, required)
PACKAGES = [
    ("spake2", "spake2", "Checks the room password without ever sending it over the network.", ["spake2"], True),
    ("cryptography", "cryptography", "Encrypts every message and file, and makes your friend ID.", ["cryptography"], True),
    ("Pillow", "PIL", "Shows emoji in full colour instead of black and white.", ["pillow"], False),
    ("emoji", "emoji", "Lets you type emoji with shortcodes, like :sob:.", ["emoji"], False),
    ("safetext", "safetext", "A big swear-word list, so Filter words catches more.",
     ["--no-deps", "safetext", "pysrt", "requests", "python-dotenv"], False),
    ("paho-mqtt", "paho.mqtt.client", "Lets you host or join a room over the internet through a "
     "relay, without needing an IP address.", ["paho-mqtt>=2"], False),
]



def run_pip(args):
    """pip install <args> without a console window. Returns (ok, error text)."""
    base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    out = ""
    for extra in (["--user"], []):            # per-user first: school PCs rarely allow more
        try:
            r = subprocess.run(base + extra + list(args), capture_output=True, text=True,
                               timeout=900, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        if r.returncode == 0:
            importlib.invalidate_caches()
            return True, ""
        out = (r.stdout + r.stderr).strip()[-400:]
    return False, out



def _installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing_required_dialog():
    """Shown when the two packages the chat can't run without are missing: explains
    what they do and installs them (same commands as the .txt files: pip --user first)."""
    import tkinter as _tk
    bg, panel, text, muted, accent = "#0f172a", "#1e293b", "#e2e8f0", "#94a3b8", "#3b82f6"
    root = _tk.Tk()
    root.title("IP Chat - setup")
    root.configure(bg=bg)
    root.resizable(False, False)
    card = _tk.Frame(root, bg=panel, padx=28, pady=24)
    card.pack(padx=20, pady=20)
    _tk.Label(card, text="Missing packages", font=("Segoe UI", 16, "bold"),
              bg=panel, fg=text).pack()
    _tk.Label(card, text="IP Chat can't start without these. Press Install and they are "
              "downloaded for you.", font=("Segoe UI", 10), bg=panel, fg=muted,
              wraplength=360, justify="center").pack(pady=(4, 12))
    rows = {}
    for name, module, info, args, required in PACKAGES:
        if not required:
            continue
        r = _tk.Frame(card, bg=panel)
        r.pack(fill="x", pady=3)
        _tk.Label(r, text=name, font=("Segoe UI", 10, "bold"), bg=panel, fg=text,
                  anchor="w").pack(fill="x")
        _tk.Label(r, text=info, font=("Segoe UI", 9), bg=panel, fg=muted, anchor="w",
                  wraplength=360, justify="left").pack(fill="x")
        st = _tk.Label(r, text="Installed \u2713" if _installed(module) else "Missing",
                       font=("Segoe UI", 9), bg=panel, fg="#22c55e" if _installed(module) else "#f59e0b",
                       anchor="w")
        st.pack(fill="x")
        rows[name] = (module, args, st)
    note = _tk.Label(card, text="", font=("Segoe UI", 9), bg=panel, fg="#ef4444",
                     wraplength=360, justify="left", anchor="w")
    note.pack(fill="x", pady=(8, 0))
    state = {"done": False, "results": None, "restart": False}
    btn = _tk.Button(card, text="Install", bg=accent, fg="white", relief="flat",
                     font=("Segoe UI", 10, "bold"), padx=14, pady=8, cursor="hand2",
                     activebackground="#2563eb", activeforeground="white")
    btn.pack(fill="x", pady=(12, 0))
    close = _tk.Button(card, text="Close", bg="#334155", fg="white", relief="flat",
                       font=("Segoe UI", 10), padx=14, pady=6, command=root.destroy,
                       activebackground="#475569", activeforeground="white")
    close.pack(fill="x", pady=(8, 0))

    def work(todo):
        out = []
        for name in todo:
            out.append((name,) + run_pip(rows[name][1]))
        state["results"] = out

    def poll():
        if state["results"] is None:
            root.after(200, poll)
            return
        failed = [(n, e) for n, ok, e in state["results"] if not ok]
        for n, ok, e in state["results"]:
            rows[n][2].config(text="Installed \u2713" if ok else "Failed",
                              fg="#22c55e" if ok else "#ef4444")
        if failed:
            note.config(text="Could not install: " + "; ".join(
                f"{n} ({e[-120:] or 'unknown error'})" for n, e in failed))
            btn.config(text="Try again", state="normal", command=go)
        else:
            state["restart"] = True
            note.config(text="Done! IP Chat is starting again...", fg="#22c55e")
            root.after(900, root.destroy)

    def go():
        todo = [n for n, (m, a, st) in rows.items() if not _installed(m)]
        if not todo:
            state["restart"] = True
            root.destroy()
            return
        for n in todo:
            rows[n][2].config(text="Installing...", fg="#f59e0b")
        note.config(text="", fg="#ef4444")
        btn.config(text="Installing... (this can take a minute)", state="disabled")
        state["results"] = None
        threading.Thread(target=work, args=(todo,), daemon=True).start()
        poll()
    btn.config(command=go)
    root.update_idletasks()
    x = (root.winfo_screenwidth() - root.winfo_width()) // 2
    y = (root.winfo_screenheight() - root.winfo_height()) // 3
    root.geometry(f"+{x}+{y}")
    root.mainloop()
    if state["restart"]:
        script = os.path.abspath(sys.argv[0])
        try:
            subprocess.Popen([sys.executable, script] + sys.argv[1:],
                             cwd=os.path.dirname(script) or None)
        except OSError:
            pass
    raise SystemExit(0)

try:
    import paho.mqtt.client as mqtt_lib
except ImportError:
    mqtt_lib = None

try:
    from cryptography.exceptions import InvalidSignature, InvalidTag
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from spake2 import SPAKE2_A, SPAKE2_B
except ImportError:
    missing_required_dialog()

PORT = 5002
PASSWORD_LENGTH = 6
PASSWORD_CHARS = string.ascii_letters + string.digits
MAX_MESSAGE_CHARS = 4000
NICK_MAX = 20
DEFAULT_ROOM_PEOPLE = 2              # room size when the host doesn't choose one
MAX_ROOM_PEOPLE = 100                # hard limit (the host counts as one person)
MAX_PENDING = 10                     # connections allowed to be busy logging in at once
MAX_PENDING_PER_IP = 3               # of those, how many one address may hold at once
HOST_ID = 0                          # the host's id inside a room
BULK_QUEUE = 8                       # file pieces allowed to wait in line per connection
MQTT_INFLIGHT_WINDOW = 16            # relay: pieces that may be unacknowledged at once (pipelined,
                                      # instead of waiting for each one's ack before sending the next)
MQTT_PUBLISH_RETRY_WAIT = 20         # how long we let the oldest unacknowledged piece sit before
                                      # moving on anyway (a slow ack doesn't mean the link is dead -
                                      # the heartbeat already watches for that separately)
HANDLED = object()                   # "already dealt with" marker used inside guest_loop
MAX_FILE_BYTES = 500 * 1024 * 1024   # biggest file that can be sent
CHUNK_SIZE = 32 * 1024               # files travel in pieces of this size
CARD_W = 250                         # width of a file card in the chat
RISKY_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs",
                    ".js", ".jar", ".lnk", ".reg", ".dll", ".hta"}

# kinds of messages that travel through the encrypted channel
K_TEXT = b"T"     # chat message
K_OFFER = b"O"    # "I'd like to send you this file"      (sender -> receiver)
K_ACCEPT = b"A"   # "yes, send it"                        (receiver -> sender)
K_REJECT = b"R"   # "no" / "stop"                         (receiver -> sender)
K_CHUNK = b"C"    # a piece of the file                   (sender -> receiver)
K_END = b"E"      # last piece sent + checksum            (sender -> receiver)
K_ABORT = b"X"    # "I cancel the transfer"               (sender -> receiver)
K_DONE = b"F"     # "file saved" / "file failed"          (receiver -> sender)
K_MSG = b"M"      # chat message with its sender's name   (host -> guests)
K_SYS = b"S"      # notice such as "Bob joined the room"  (host -> guests)
K_ROSTER = b"L"   # who is in the room                    (host -> guests)
K_BYE = b"B"      # "you're out" (room full / closed)     (host -> guests)
K_FRIEND = b"G"   # friend request / answer, end-to-end   (person <-> person, via the host)
K_LEAVE = b"V"    # "I'm disconnecting on purpose"         (guest -> host)
K_PING = b"P"     # "I'm still here" - relay only          (either direction)
K_TYPING = b"Y"   # "I'm typing a message"    (guest -> host; host -> guests carries a 2-byte id)
# K_LEAVE exists because closing a connection is not, by itself, something the other side
# can always notice: over a real TCP socket it is (the other side's recv() fails), but over
# the relay there is no such signal - closing one side's pipe is purely local. Saying so
# explicitly works everywhere.
# File messages carry a 2-byte person id in front: guest -> host it says who the
# message is FOR, host -> guest it says who it is FROM. The host passes them on
# between guests, so any two people in a room can exchange files.
FILE_KINDS = (K_OFFER, K_ACCEPT, K_REJECT, K_CHUNK, K_END, K_ABORT, K_DONE)
MAX_FRAME_BYTES = 64 * 1024
HANDSHAKE_TIMEOUT = 10  # seconds
RULE_NAME = "IP Chat"
ROOM_CODE_LENGTH = 10
RELAY_HOST, RELAY_PORT = "broker.emqx.io", 8883   # a free public relay, used over TLS
RELAY_PREFIX = "ipchat-relay-v1/"    # not secret - the room password is what protects a room
LOBBY_TOPIC = RELAY_PREFIX + "lobby/"  # friend-only "I'm hosting" beacons, one inbox per uid
LOBBY_INTERVAL = 2.0                 # how often a relay host re-announces to its friends
LOBBY_STALE_AFTER = 6.0              # a friend's room disappears from search after this long
RELAY_PING_INTERVAL = 5.0            # how often each side says "I'm still here" over the relay
RELAY_PING_TIMEOUT = 12.0            # how long with nothing at all before it's considered dead
TYPING_SEND_INTERVAL = 3.0           # how often we re-announce "still typing" while typing
TYPING_EXPIRE = 6.0                  # stop showing someone as typing this long after their last ping
TYPING_TICK_MS = 300                 # how often the typing indicator's dots animate
TYPING_DOT_FRAMES = ["●··", "·●·", "··●"]  # ●·· ·●· ··●
DISCOVERY_PORT = 50021               # rooms announce themselves here (UDP, same network only)
KNOCK_PORT = 50022                   # a host listens here for "I'd like to join" messages (UDP)
APP_TAG = "IPChat1"                  # marks our own announcements

# --- updates ---------------------------------------------------------------
# No version number to remember to bump anywhere but the script itself. Releasing a
# new version is just: bump APP_VERSION below, then push a file named
# "ip-chat<version>.py" (e.g. ip-chat1.0.2.py) to the repo named by UPDATE_REPO_OWNER/
# UPDATE_REPO_NAME - whichever ip-chatX.Y[.Z].py file in that repo has the highest
# version number IS "latest" (and if it's lower than what's currently running, that's
# a downgrade, offered the same way). Old versions can just stay in the repo, so
# anyone can be rolled back to one by removing the newer files.
#
# update.json at the repo root is optional and purely cosmetic - a version -> notes
# map, e.g. {"1.0.2": "Fixed the file-transfer stall bug."}, shown in the update
# dialog if present. Nothing breaks if it's missing or doesn't mention a version.
APP_VERSION = "1.1.5"
UPDATE_REPO_OWNER = "chudlifeforever54"
UPDATE_REPO_NAME = "ip-chat"
UPDATE_FILE_RE = re.compile(r"^ip-chat(\d+(?:\.\d+){1,2})\.py$", re.IGNORECASE)
UPDATE_CHECK_TIMEOUT = 10
UPDATE_DOWNLOAD_TIMEOUT = 30
# The window/taskbar icon - also fetched from GitHub, straight into the same AppData
# folder the installed copy of the program and its shortcut live in (see
# ensure_installed() below). A missing icon never stops anything; things just fall
# back to no icon / Tk's default.
ICON_URL = ("https://raw.githubusercontent.com/chudlifeforever54/ip-chat"
            "/refs/heads/main/iPC.ico")
# The quiet auto-check doesn't run every launch - just every UPDATE_CHECK_EVERY of them
# (counted down in a number saved in settings.json), so it isn't hitting GitHub's API
# on every single startup. Right after installing an update, that countdown gets set
# to UPDATE_CHECK_AFTER_UPDATE instead - there's no point checking again right away.
UPDATE_CHECK_EVERY = 7
UPDATE_CHECK_AFTER_UPDATE = 10
ID_LENGTH = 10                       # your friend ID: 10 letters and numbers
ID_CHARS = string.digits + string.ascii_lowercase + string.ascii_uppercase
FRIEND_NAME_MAX = 20
FRIEND_TIMEOUT = 300                 # an unanswered friend request is forgotten after 5 minutes
TAMPER_MESSAGE = ("Please don't alter your ID.json file, this is heavily tied to you "
                  "and shouldn't be touched.")
STALE_AFTER = 5.0                    # a room that stopped announcing disappears after this
# ---------- look & feel ----------
BG = "#0f172a"        # window background
PANEL = "#1e293b"     # cards, header, input bar
INPUT = "#0b1220"     # text boxes
LINE = "#334155"      # borders / dividers
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2563eb"
GREEN = "#16a34a"
GREEN_HOVER = "#15803d"
RED = "#ef4444"
RED_HOVER = "#dc2626"
BUBBLE_ME = "#2563eb"
BUBBLE_FRIEND = "#334155"
STATE_COLORS = {"wait": "#f59e0b", "ok": "#22c55e", "bad": "#ef4444"}
SPOILER = "#64748b"        # a blurred word: a bar of this colour
SPOILER_OPEN = "#0f172a"   # a word that was clicked open

STRIP = "#162033"     # the bars under the header
HOVER = "#475569"     # grey buttons when the mouse is over them

# Colour themes. Green/red buttons keep their meaning in every theme.
THEMES = {
    "default": {"name": "Default", "BG": "#0f172a", "PANEL": "#1e293b", "INPUT": "#0b1220",
                "LINE": "#334155", "STRIP": "#162033", "HOVER": "#475569", "TEXT": "#e2e8f0",
                "MUTED": "#94a3b8", "ACCENT": "#3b82f6", "ACCENT_HOVER": "#2563eb",
                "BUBBLE_ME": "#2563eb", "BUBBLE_FRIEND": "#334155", "SPOILER": "#64748b",
                "SPOILER_OPEN": "#0f172a"},
    "red": {"name": "Red", "BG": "#1a0b0e", "PANEL": "#2a1519", "INPUT": "#12080a",
            "LINE": "#4a2a30", "STRIP": "#221014", "HOVER": "#6b3b43", "TEXT": "#f5e6e8",
            "MUTED": "#c4a1a8", "ACCENT": "#e11d48", "ACCENT_HOVER": "#be123c",
            "BUBBLE_ME": "#be123c", "BUBBLE_FRIEND": "#4a2a30", "SPOILER": "#7a5159",
            "SPOILER_OPEN": "#12080a"},
    "blue": {"name": "Blue", "BG": "#08122b", "PANEL": "#10224a", "INPUT": "#060d20",
             "LINE": "#1f3a73", "STRIP": "#0c1a3b", "HOVER": "#2f56a8", "TEXT": "#e6eeff",
             "MUTED": "#8fa8d6", "ACCENT": "#2f7bff", "ACCENT_HOVER": "#1d63e0",
             "BUBBLE_ME": "#1d63e0", "BUBBLE_FRIEND": "#1f3a73", "SPOILER": "#4a6aa8",
             "SPOILER_OPEN": "#060d20"},
    "green": {"name": "Green", "BG": "#08170f", "PANEL": "#10281a", "INPUT": "#06110a",
              "LINE": "#1f4a30", "STRIP": "#0c1f14", "HOVER": "#2f7048", "TEXT": "#e4f5ea",
              "MUTED": "#8fc4a3", "ACCENT": "#16a34a", "ACCENT_HOVER": "#15803d",
              "BUBBLE_ME": "#15803d", "BUBBLE_FRIEND": "#1f4a30", "SPOILER": "#4a8560",
              "SPOILER_OPEN": "#06110a"},
}


def _hsl(h, sat, light):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, light, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _dark(name, hue, sat=0.45, accent=(0.55, 0.52)):
    """A dark theme tinted with one colour."""
    acc, acc_h = _hsl(hue, accent[0], accent[1]), _hsl(hue, accent[0], accent[1] - 0.10)
    return {"name": name, "BG": _hsl(hue, sat, 0.07), "PANEL": _hsl(hue, sat * 0.85, 0.14),
            "INPUT": _hsl(hue, sat, 0.045), "LINE": _hsl(hue, sat * 0.7, 0.25),
            "STRIP": _hsl(hue, sat * 0.9, 0.10), "HOVER": _hsl(hue, sat * 0.7, 0.36),
            "TEXT": _hsl(hue, 0.30, 0.92), "MUTED": _hsl(hue, 0.20, 0.70),
            "ACCENT": acc, "ACCENT_HOVER": acc_h,
            "BUBBLE_ME": _hsl(hue, accent[0], min(0.40, accent[1] - 0.08)),
            "BUBBLE_FRIEND": _hsl(hue, sat * 0.7, 0.25), "SPOILER": _hsl(hue, 0.25, 0.45),
            "SPOILER_OPEN": _hsl(hue, sat, 0.045)}


def _pastel(name, hue):
    """A light theme in a soft colour (message bubbles stay dark enough to read)."""
    return {"name": name, "BG": _hsl(hue, 0.60, 0.95), "PANEL": _hsl(hue, 0.50, 0.89),
            "INPUT": _hsl(hue, 0.45, 0.985), "LINE": _hsl(hue, 0.35, 0.76),
            "STRIP": _hsl(hue, 0.55, 0.92), "HOVER": _hsl(hue, 0.35, 0.68),
            "TEXT": _hsl(hue, 0.40, 0.14), "MUTED": _hsl(hue, 0.20, 0.36),
            "ACCENT": _hsl(hue, 0.58, 0.58), "ACCENT_HOVER": _hsl(hue, 0.58, 0.50),
            "BUBBLE_ME": _hsl(hue, 0.45, 0.38), "BUBBLE_FRIEND": _hsl(hue, 0.18, 0.40),
            "SPOILER": _hsl(hue, 0.20, 0.58), "SPOILER_OPEN": _hsl(hue, 0.40, 0.12)}


def _neutral(name, bg, panel, inp, line, strip, hover, text, muted, accent, accent_h, me, friend):
    return {"name": name, "BG": bg, "PANEL": panel, "INPUT": inp, "LINE": line, "STRIP": strip,
            "HOVER": hover, "TEXT": text, "MUTED": muted, "ACCENT": accent,
            "ACCENT_HOVER": accent_h, "BUBBLE_ME": me, "BUBBLE_FRIEND": friend,
            "SPOILER": "#8a8f98", "SPOILER_OPEN": "#16181c"}


THEMES.update({
    "yellow": _dark("Yellow", 0.14, accent=(0.95, 0.52)),
    "purple": _dark("Purple", 0.76),
    "pink": _dark("Pink", 0.92, accent=(0.75, 0.60)),
    "orange": _dark("Orange", 0.07, accent=(0.90, 0.52)),
    "black": _neutral("Black", "#000000", "#141414", "#050505", "#2a2a2a", "#0b0b0b",
                      "#454545", "#f2f2f2", "#9a9a9a", "#d4d4d8", "#a1a1aa", "#3f3f46", "#27272a"),
    "white": _neutral("White", "#ffffff", "#f1f5f9", "#ffffff", "#cbd5e1", "#f8fafc",
                      "#94a3b8", "#0f172a", "#475569", "#2563eb", "#1d4ed8", "#2563eb", "#64748b"),
    "gray": _neutral("Gray", "#26282c", "#34373d", "#1c1d21", "#4b4e56", "#2d3035",
                     "#666a73", "#eceef1", "#a5a9b2", "#8b909b", "#757a86", "#5d626d", "#474b54"),
    "cyan": _dark("Cyan", 0.50, accent=(0.85, 0.46)),
    "lightgreen": _dark("Light green", 0.29, sat=0.35, accent=(0.70, 0.58)),
    "gold": _dark("Gold", 0.115, sat=0.50, accent=(0.80, 0.46)),
    "silver": _neutral("Silver", "#d9dce1", "#c6cad1", "#eef0f3", "#a9aeb8", "#cfd3d9",
                       "#8e94a0", "#1f2328", "#4a5058", "#5b6572", "#48525e", "#4f5966", "#737c89"),
    "pastelred": _pastel("Pastel red", 0.0),
    "pastelgreen": _pastel("Pastel green", 0.33),
    "pastelblue": _pastel("Pastel blue", 0.58),
    "pastelpurple": _pastel("Pastel purple", 0.76),
    "pastelyellow": _pastel("Pastel yellow", 0.14),
})
CURRENT_THEME = ["default"]


def on_color(bg):
    """White or near-black text, whichever is easier to read on `bg`."""
    r, g, b = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    return "#ffffff" if (0.299 * r + 0.587 * g + 0.114 * b) < 150 else "#111827"


def blend_hex(c1, c2, t):
    """c1 and c2 faded between by t (0 = c1, 1 = c2); used for the chat bubbles'
    fade-in pop so it tracks whatever theme is active at the moment, not a fixed colour."""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


# *italic*, **bold**, ***bold+italic*** in chat messages. Greedy {1,3} tries the
# longest run of asterisks first, so "***x***" matches all three before falling back
# to "**x**" or "*x*"; the backreference then requires the SAME number of asterisks to
# close. Content can't itself contain "*" (no nesting - the fixed three forms are all
# that's asked for) and can't start/end with whitespace, which is what keeps an
# ordinary "5 * 3 * 2" from being misread as emphasis around " 3 ".
MARKDOWN_RE = re.compile(r'(\*{1,3})(?!\s)((?:(?!\*).)+?)(?<!\s)\1')


def parse_markdown(text):
    """Strips *markdown* emphasis out of `text` and returns (clean_text, ranges),
    where ranges is a list of (start, end, bold, italic) - positions in clean_text,
    not in the original text - for each stretch that should render bold and/or
    italic. A stray, unpaired asterisk is left exactly as typed."""
    clean_parts = []
    ranges = []
    cursor = pos = 0
    for m in MARKDOWN_RE.finditer(text):
        if m.start() > pos:
            plain = text[pos:m.start()]
            clean_parts.append(plain)
            cursor += len(plain)
        delim, content = m.group(1), m.group(2)
        bold, italic = len(delim) >= 2, len(delim) in (1, 3)
        ranges.append((cursor, cursor + len(content), bold, italic))
        clean_parts.append(content)
        cursor += len(content)
        pos = m.end()
    if pos < len(text):
        clean_parts.append(text[pos:])
    return "".join(clean_parts), ranges


def apply_theme(key):
    """Switches the colours used for everything built from now on."""
    theme = THEMES.get(key) or THEMES["default"]
    CURRENT_THEME[0] = key if key in THEMES else "default"
    g = globals()
    for name, value in theme.items():
        if name != "name":
            g[name] = value


def _documents_dir():
    """The user's real "Documents" folder - what Explorer shows as "Documenten" on a
    Dutch-language Windows, "Mes documents" in French, and so on, but which is still
    the one folder that's always there and always writable. Asks Windows for its
    actual (possibly redirected, e.g. onto OneDrive) location when possible, falling
    back to the ordinary default path."""
    if os.name == "nt":
        try:
            CSIDL_PERSONAL = 5   # "My Documents"
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf) == 0:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def _can_use_as_folder(path):
    """True if `path` already exists, or can be created, and is actually writable -
    not just creatable (a locked-down AppData can let you mkdir but then refuse the
    file itself, which os.makedirs alone wouldn't catch)."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".ipchat_write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


# Decided once per run, the first time anything asks for it: the normal AppData/.config
# location if it can actually be created and written to, or - if not (locked-down
# permissions, odd account setups, whatever stopped a friend's AppData\IPChat from ever
# appearing) - the Documents folder instead, which is always there. Everything (settings,
# the installed script, its icon, its shortcut) then lives under "<that base>\IPChat",
# so the only thing that changes is which folder is standing in as "AppData" this run.
_BASE_DIR_CACHE = [None]


def _base_dir():
    if _BASE_DIR_CACHE[0] is not None:
        return _BASE_DIR_CACHE[0]
    if os.name == "nt":
        preferred = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        preferred = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    base = preferred if _can_use_as_folder(os.path.join(preferred, "IPChat")) else _documents_dir()
    _BASE_DIR_CACHE[0] = base
    return base


def settings_path():
    return os.path.join(_base_dir(), "IPChat", "settings.json")


def appdata_dir():
    """The per-user "IP Chat" folder - already used for settings.json, and now also
    where the installed copy of the program, its window/shortcut icon, and its
    "IP Chat.lnk" shortcut all live, so it's one place instead of whatever folder the
    program happened to be downloaded or copied into."""
    return os.path.dirname(settings_path())


def icon_path():
    return os.path.join(appdata_dir(), "iPC.ico")


def download_bytes(url, timeout=UPDATE_DOWNLOAD_TIMEOUT, max_bytes=50 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": "IPChat"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def ensure_icon():
    """Best-effort: makes sure iPC.ico is sitting in the appdata folder, fetching it
    from GitHub if it isn't there yet. Never raises - a missing icon just means the
    window and shortcut keep their defaults instead of IP Chat's own icon."""
    path = icon_path()
    if os.path.exists(path):
        return path
    try:
        data = download_bytes(ICON_URL, timeout=UPDATE_CHECK_TIMEOUT, max_bytes=5 * 1024 * 1024)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path
    except Exception:
        return path if os.path.exists(path) else None


# ---------- one ordinary IP Chat at a time ----------
# A second copy launched the normal way (the shortcut, or double-clicking the
# installed script) shouldn't silently open a second window - it should say so and
# quit instead. The hidden testing "Open a new client" button is the one deliberate
# exception, via --ipchat-allow-multiple (see open_new_client() and __main__ below).
ARG_RELAUNCH = "--ipchat-relaunch"
ARG_ALLOW_MULTIPLE = "--ipchat-allow-multiple"
ARG_HALF_PREFIX = "--ipchat-half="


def lock_path():
    return os.path.join(appdata_dir(), "running.lock")


def _pid_alive(pid):
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True   # exists but isn't ours (e.g. permission denied) - still alive
    except Exception:
        return False


def acquire_single_instance_lock(steal=False):
    """True if this process now owns the lock (no ordinary second copy is running) -
    False means another copy is already running and this one should quit without
    ever showing a window. `steal` is for a process that's intentionally replacing
    itself (restarting after installing packages or after an update) - it takes the
    lock over without checking who held it before, since that old process is already
    on its way out and would otherwise lose the race against its own replacement."""
    path = lock_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError:
        return True   # can't even manage a lock file - never block someone over this
    if not steal:
        try:
            with open(path) as f:
                other = int(f.read().strip())
        except (OSError, ValueError):
            other = -1
        if other != os.getpid() and _pid_alive(other):
            return False
    try:
        with open(path, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    return True


def release_single_instance_lock():
    try:
        with open(lock_path()) as f:
            if int(f.read().strip()) == os.getpid():
                os.remove(lock_path())
    except (OSError, ValueError):
        pass


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(**changes):
    """Remembers settings (like the theme) for the next time the program starts."""
    data = load_settings()
    data.update(changes)
    path = settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 8)


# ======================================================================
#  Windows firewall helpers (only the HOST needs this: incoming connections)
# ======================================================================
def _is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _firewall_rule_exists(rule=RULE_NAME):
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0
    except OSError:
        return False


def ensure_firewall_rule(rule=RULE_NAME, protocol="TCP", ports=None):
    """Creates (once) an inbound Windows firewall rule for our port.
    Asks for administrator rights through the normal UAC window."""
    ports = ports or str(PORT)
    if os.name != "nt" or _firewall_rule_exists(rule):
        return True

    if _is_admin():
        try:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "add", "rule",
                 f"name={rule}", "dir=in", "action=allow",
                 f"protocol={protocol}", f"localport={ports}", "profile=any"],
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError:
            return False
    else:
        args = (f'advfirewall firewall add rule name="{rule}" dir=in '
                f'action=allow protocol={protocol} localport={ports} profile=any')
        # "runas" shows the UAC window; a result <= 32 means it did not start
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0) <= 32:
            return False

    for _ in range(20):  # wait max. 10 seconds for the rule to appear
        if _firewall_rule_exists(rule):
            return True
        time.sleep(0.5)
    return False


def create_shortcut(target_script, icon=None):
    """Builds "IP Chat.lnk" in the appdata folder, pointed at `target_script` (so it
    works on whatever computer it was built on, not a path baked in ahead of time),
    using `icon` (a .ico path) as its icon when one is given and actually exists.

    Windows has quietly blocked apps from pinning themselves to the taskbar on some
    versions, so this no longer even tries - it just makes the shortcut; the Settings
    button that calls this opens the folder and asks the person to drag it onto the
    taskbar themselves, which always works. Raises OSError/subprocess.TimeoutExpired
    on anything going wrong enough that even the shortcut couldn't be created."""
    exe = sys.executable
    if os.name == "nt" and target_script.lower().endswith(".pyw"):
        pyw_exe = os.path.join(os.path.dirname(sys.executable) or "", "pythonw.exe")
        if os.path.exists(pyw_exe):
            exe = pyw_exe
    working_dir = os.path.dirname(target_script) or os.getcwd()
    folder = appdata_dir()
    os.makedirs(folder, exist_ok=True)
    lnk_path = os.path.join(folder, "IP Chat.lnk")
    icon_line = f'$sc.IconLocation = "{icon},0"' if icon and os.path.exists(icon) else ""

    ps = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{lnk_path}")
$sc.TargetPath = "{exe}"
$sc.Arguments = '"{target_script}"'
$sc.WorkingDirectory = "{working_dir}"
{icon_line}
$sc.Save()
'''
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    return lnk_path


# ======================================================================
#  Networking helpers
# ======================================================================
def get_local_ip():
    """Returns the IP other devices on your network can use to reach this PC."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # sends no data, just picks the right interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def my_lan_ips():
    """All addresses this computer currently answers to, for recognising a same-PC test
    connection even when it didn't arrive over plain localhost - joining your own room
    through "Search for rooms" sees your real network address (e.g. 192.168.1.5), not
    127.0.0.1, so that has to count as "this is me" too."""
    ips = {"127.0.0.1", "::1", "localhost"}
    ips.add(get_local_ip())
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return ips


def generate_password():
    """6 random characters (a-z, A-Z, 0-9) from the OS's secure random source."""
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(PASSWORD_LENGTH))


def generate_room_code():
    """10 random characters: stands in for an IP address when using the relay."""
    return "".join(secrets.choice(PASSWORD_CHARS) for _ in range(ROOM_CODE_LENGTH))


def clean_nickname(text):
    """Trims a nickname, drops control characters and limits the length."""
    text = "".join(ch for ch in text if ch.isprintable() or ch.isspace())
    return " ".join(text.split())[:NICK_MAX]


def clean_text(text, limit):
    """Printable characters only, one line, cut to `limit` characters."""
    text = "".join(ch for ch in str(text) if ch.isprintable() or ch.isspace())
    return " ".join(text.split())[:limit]


def parse_version(v):
    """'1.2.10' -> (1, 2, 10), so versions compare numerically instead of as text
    (where "1.9" would wrongly look newer than "1.10"). Tolerant of odd formatting -
    a non-numeric part just becomes 0 - since this reads a file hosted elsewhere."""
    parts = []
    for p in str(v).split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()   # so "1.0" and "1.0.0" compare equal, not as two different versions
    return tuple(parts) or (0,)


def fetch_update_notes(version):
    """The optional version -> notes map at update.json. Any problem (missing file,
    bad JSON, no entry for this version) just means no notes - never an error, since
    this is cosmetic and the real version check doesn't depend on it."""
    url = (f"https://raw.githubusercontent.com/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}"
           f"/main/update.json")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IPChat"})
        with urllib.request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as resp:
            raw = resp.read(1 << 20)
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            return str(data.get(version) or "")
    except Exception:
        pass
    return ""


def fetch_latest_release():
    """Lists the repo's files on GitHub's API and picks whichever ip-chatX.Y[.Z].py
    has the highest version number in its name - that's "latest" (or, if it's lower
    than what's running now, the one to roll back to). No hand-maintained version
    number anywhere else to go stale. Raises on any network/format problem; callers
    decide what to do about that."""
    api_url = f"https://api.github.com/repos/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/contents/"
    req = urllib.request.Request(api_url, headers={"User-Agent": "IPChat",
                                                    "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=UPDATE_CHECK_TIMEOUT) as resp:
        raw = resp.read(1 << 20)   # a directory listing is small - 1 MB is already absurd
    entries = json.loads(raw.decode("utf-8"))
    if not isinstance(entries, list):
        raise ValueError("unexpected response listing the repo's files")

    best = None   # (version_tuple, version_str, download_url, git_blob_sha)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        m = UPDATE_FILE_RE.match(str(entry.get("name", "")))
        if not m:
            continue
        vstr = m.group(1)
        vtuple = parse_version(vstr)
        if best is None or vtuple > best[0]:
            best = (vtuple, vstr, entry.get("download_url"), entry.get("sha"))
    if best is None or not best[2]:
        raise ValueError(f"no ip-chatX.Y.Z.py files found in {UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}")

    return {"version": best[1], "url": best[2], "git_sha": best[3],
            "notes": fetch_update_notes(best[1])}


def git_blob_sha1(content):
    """The same hash GitHub shows as a file's "sha" - lets a download be checked
    against what the API already said it should be, with no manual checksum to
    maintain anywhere."""
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def ban_hash(rid, ip):
    """A short fingerprint of an IP address. Hosts announce these for banned
    computers, so a banned person can see (without the IP being shown to anyone)
    that they cannot join."""
    return hashlib.sha256(f"{rid}:{ip}".encode("utf-8")).hexdigest()[:8]


def broadcast_targets():
    """Where a room announces itself: the whole network, plus this PC (for testing)."""
    targets = ["255.255.255.255", "127.0.0.1"]
    ip = get_local_ip()
    if not ip.startswith("127.") and ip.count(".") == 3:
        targets.append(ip.rsplit(".", 1)[0] + ".255")
    return targets


def package_installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def invite_key(shared, rid):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"ipchat-invite:" + rid.encode("utf-8")).derive(shared)


def raw_public(key):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


class Spoiler(tk.Label):
    """Hidden text: hover to peek, click to keep it open (click again to hide)."""

    def __init__(self, parent, bg=None):
        super().__init__(parent, text="", font=FONT_BOLD, bg=bg or LINE, fg=MUTED, padx=4, pady=1,
                         cursor="hand2")
        self.secret, self.pinned, self.hover = "", False, False
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False))
        self.bind("<Button-1>", self._click)

    def set(self, text):
        self.secret, self.pinned, self.hover = text, False, False
        self.config(width=len(text) + 1)      # fixed width, so nothing jumps when revealed
        self.draw()

    def _click(self, event=None):
        if self.pinned:                      # second click: hide it, even with the mouse on it
            self._set(pinned=False, hover=False)
        else:
            self._set(pinned=True)

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def draw(self):
        show = self.pinned or self.hover
        self.config(text=self.secret if show else "\u2022" * len(self.secret),
                    bg=INPUT if show else LINE, fg=TEXT if show else MUTED)


def human_size(n):
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.2f} GB"


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
                   | {f"LPT{i}" for i in range(1, 10)}


def safe_filename(name):
    """Turns a name received from the network into a harmless file name:
    no folders (so nothing can be written outside the download folder),
    no characters Windows doesn't allow, no reserved names."""
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"/\\|?*')
    name = name.strip(" .")
    stem, ext = os.path.splitext(name)
    if not stem:
        stem, ext = "file", ""
    if stem.upper() in WINDOWS_RESERVED:
        stem = "_" + stem
    return stem[:100] + ext[:20]


def download_dir():
    return os.path.join(os.path.expanduser("~"), "Downloads", "IP Chat")


def unique_path(folder, name):
    """folder/name, or folder/name (1), (2)... if that already exists."""
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path) or os.path.exists(path + ".part"):
        path = os.path.join(folder, f"{base} ({n}){ext}")
        n += 1
    return path


def reveal_in_folder(path):
    try:
        if os.name == "nt":
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass


def enable_tcp_keepalive(sock):
    """A direct (LAN) connection is a real TCP socket, so the usual assumption is
    that a dropped connection always surfaces as a closed-socket error. That's true
    for a clean close, but a link that just goes silent - Wi-Fi dropping, the other
    machine sleeping or losing power, a router falling over - sends neither a FIN
    nor a RST, so without this a blocked recv() could sit there for a very long
    time (sometimes indefinitely) without ever finding out. Turning on the OS's own
    TCP keepalive probing catches that: after a stretch of silence it probes a few
    times, and gives up (handing recv() a normal connection error) well within a
    minute - all for free, with no extra thread or polling needed. Best-effort and
    a no-op wherever a option isn't available (older platforms, or the relay's own
    faked-up connection, which already has its own ping-based heartbeat instead -
    see ping_loop/RELAY_PING_TIMEOUT)."""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
    except (AttributeError, OSError, ValueError):
        pass


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return bytes(buf)


def send_frame(sock, data):
    """TCP is a stream, so every message is sent with a 4-byte length in front."""
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock, limit=MAX_FRAME_BYTES):
    (length,) = struct.unpack(">I", recv_exact(sock, 4))
    if length > limit:
        raise ConnectionError("frame too large")
    return recv_exact(sock, length)


# ======================================================================
#  Secure channel
#
#  The room password is NEVER sent over the network, not even hashed.
#  Both sides run SPAKE2 (a password-authenticated key exchange): they swap
#  a few random-looking values and each end up with the same secret key
#  only if they typed the same password. An eavesdropper who records the
#  whole exchange can't use it to guess the password offline.
#  That key then encrypts and authenticates every chat message.
# ======================================================================
class HandshakeError(Exception):
    pass


class SecureChannel:
    """An encrypted connection. Sending never blocks the caller: messages are
    put in a queue and a small background thread encrypts and sends them.
    That way one slow or frozen person can't make the host (or its window)
    wait. File pieces are the only exception: only BULK_QUEUE of them may wait
    in line, so a big file can't flood memory and chat messages never have
    more than a few pieces in front of them. The queue is priority-ordered
    (FIFO within the same priority) rather than plain FIFO: a K_PING always
    jumps ahead of everything else, and ordinary messages jump ahead of file
    pieces. Without that, a ping sent while a big file is going out could end
    up stuck behind a whole backlog of chunks - over a slow relay that's
    easily long enough to trip RELAY_PING_TIMEOUT, making the other side look
    like it's gone quiet when really its heartbeat was just stuck in line
    behind its own transfer."""

    def __init__(self, sock, send_key, recv_key):
        self.sock = sock
        self._send = ChaCha20Poly1305(send_key)
        self._recv = ChaCha20Poly1305(recv_key)
        self._send_count = 0
        self._recv_count = 0
        self._out = queue.PriorityQueue()
        self._seq = itertools.count()
        self._bulk_slots = threading.Semaphore(BULK_QUEUE)
        self._error = None
        self._closed = False
        threading.Thread(target=self._writer, daemon=True).start()

    @staticmethod
    def _nonce(count):
        return b"\x00\x00\x00\x00" + count.to_bytes(8, "big")

    def _writer(self):
        try:
            while True:
                _, _, item = self._out.get()
                if item is None:       # everything before this was sent: close now
                    break
                kind, payload, bulk = item
                data = self._send.encrypt(self._nonce(self._send_count), kind + payload, None)
                self._send_count += 1
                try:
                    send_frame(self.sock, data)
                finally:
                    if bulk:
                        self._bulk_slots.release()
        except OSError as e:
            self._error = e
        finally:
            self._hard_close()

    def _hard_close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, kind, payload=b"", bulk=False):
        """Queues one message (1 byte kind + payload). Raises OSError when the
        connection is gone. bulk=True (file pieces) waits while too many are queued."""
        if self._error is not None or self._closed:
            raise OSError("connection closed")
        if bulk:
            while not self._bulk_slots.acquire(timeout=0.2):
                if self._error is not None or self._closed:
                    raise OSError("connection closed")
        # K_PING always jumps the queue. Every other file-transfer message (not
        # just K_CHUNK, which is the only one marked bulk=True) has to stay at
        # the SAME priority as the chunks, and in the order it was sent in: a
        # K_END that jumped ahead of chunks still waiting to go out would reach
        # the other side before all the bytes it's vouching for did, and they'd
        # reasonably conclude the file arrived short. Plain chat/control
        # messages have no such ordering to protect, so they're free to jump
        # ahead of a file backlog.
        if kind == K_PING:
            priority = 0
        elif kind in FILE_KINDS:
            priority = 2
        else:
            priority = 1
        self._out.put((priority, next(self._seq), (kind, payload, bulk)))

    def close(self, flush=False):
        """flush=True sends everything that is still queued first (used for a
        last 'goodbye' message); otherwise the connection is cut right away."""
        was_closed, self._closed = self._closed, True
        if flush:
            if not was_closed:
                self._out.put((3, next(self._seq), None))
        else:
            self._hard_close()
            self._out.put((3, next(self._seq), None))

    def recv(self):
        """Returns (kind, payload)."""
        data = recv_frame(self.sock)
        # Raises InvalidTag if the data was tampered with, replayed or reordered.
        plain = self._recv.decrypt(self._nonce(self._recv_count), data, None)
        self._recv_count += 1
        if not plain:
            raise ValueError("empty message")
        return plain[:1], plain[1:]

    def send_text(self, text):
        self.send(K_TEXT, text.encode("utf-8"))

    def recv_text(self):
        kind, payload = self.recv()
        if kind != K_TEXT:
            raise ValueError("unexpected message type")
        return payload.decode("utf-8", errors="replace")


# ======================================================================
#  Your identity (ID.json) and your friends (friends.json)
#
#  Your ID comes from a secret key made on this PC: ID = a fingerprint of the
#  matching public key, written as 10 letters/numbers. Nobody can claim your ID
#  without your secret key, and friends are recognised by proof, not by name.
# ======================================================================
def uid_from_pub(pub):
    n = int.from_bytes(hashlib.sha256(b"ipchat-id-v1" + pub).digest(), "big")
    out = []
    for _ in range(ID_LENGTH):
        n, r = divmod(n, len(ID_CHARS))
        out.append(ID_CHARS[r])
    return "".join(out)


def verify_sig(pub_hex, sig_hex, data):
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(sig_hex), data)
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


class Identity:
    def __init__(self, key_bytes, name):
        self.key_bytes = key_bytes
        self._key = Ed25519PrivateKey.from_private_bytes(key_bytes)
        self.pub = raw_public(self._key)
        self.pub_hex = self.pub.hex()
        self.uid = uid_from_pub(self.pub)
        self.name = name
        # A second, static key pair - for Diffie-Hellman, not signing - used so a friend
        # can find a room you are hosting over the relay without you two being connected
        # right now. Derived from the same secret rather than stored separately, so it
        # needs no change to ID.json and works for identities made before this existed.
        x_seed = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                      info=b"ipchat-static-x25519|" + self.uid.encode("utf-8")).derive(key_bytes)
        self.x_priv = X25519PrivateKey.from_private_bytes(x_seed)
        self.x_pub = raw_public(self.x_priv)
        self.x_pub_hex = self.x_pub.hex()

    @classmethod
    def create(cls, name):
        key = Ed25519PrivateKey.generate()
        from cryptography.hazmat.primitives.serialization import (
            Encoding, NoEncryption, PrivateFormat)
        raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        return cls(raw, name)

    def sign(self, data):
        return self._key.sign(data)

    def check_value(self):
        mac = hmac.new(b"ipchat-id-file|" + self.key_bytes, f"{self.uid}|{self.name}".encode("utf-8"),
                       hashlib.sha256)
        return mac.hexdigest()

    def to_bytes(self):
        return json.dumps({"id": self.uid, "name": self.name, "key": self.key_bytes.hex(),
                           "check": self.check_value()}, indent=2).encode("utf-8")


def parse_identity(raw):
    """The Identity inside an ID.json file, or None if it is damaged or was edited."""
    try:
        d = json.loads(raw.decode("utf-8"))
        name, key = d["name"], bytes.fromhex(d["key"])
        if not isinstance(name, str) or not (1 <= len(name) <= FRIEND_NAME_MAX) or len(key) != 32:
            return None
        ident = Identity(key, name)
        if d["id"] != ident.uid or not hmac.compare_digest(str(d["check"]), ident.check_value()):
            return None
        if raw != ident.to_bytes():
            return None
        return ident
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


class IdentityStore:
    """ID.json plus two hidden backup copies. If the file is changed, it is put back."""

    def __init__(self, data_dir):
        self.main = os.path.join(data_dir, "ID.json")
        alt = data_dir + "-backup"
        if os.name == "nt" and os.environ.get("LOCALAPPDATA") and \
                os.path.normcase(data_dir) == os.path.normcase(os.path.dirname(settings_path())):
            alt = os.path.join(os.environ["LOCALAPPDATA"], "IPChat")
        self.backups = [self.main + ".bak", os.path.join(alt, "ID.bak")]

    @staticmethod
    def _read(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    @staticmethod
    def _write(path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
            return True
        except OSError:
            return False

    def _save_all(self, data):
        ok = self._write(self.main, data)
        for b in self.backups:
            self._write(b, data)
        return ok

    def boot(self, ask_name, on_tamper):
        """Returns (Identity or None, tampered). `ask_name()` is called when a new
        identity has to be made; `on_tamper()` when the file was changed."""
        raw = self._read(self.main)
        tampered = False
        if raw is not None:
            good = next((b for b in (self._read(p) for p in self.backups)
                         if b is not None and parse_identity(b)), None)
            ident = parse_identity(raw)
            if ident is not None and (good is None or good == raw):
                for p in self.backups:                   # keep the backups up to date
                    if self._read(p) != raw:
                        self._write(p, raw)
                return ident, False
            tampered = True
            on_tamper()
            if good is not None:                         # put the old file back
                self._write(self.main, good)
                for p in self.backups:
                    if self._read(p) != good:
                        self._write(p, good)
                return parse_identity(good), True
        name = ask_name()
        if not name:
            return None, tampered
        ident = Identity.create(name)
        self._save_all(ident.to_bytes())
        return ident, tampered


class FriendStore:
    """friends.json: who your friends are (their ID, public key and real name)."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "friends.json")
        self.data = {}
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data = {k: v for k, v in loaded.items() if isinstance(v, dict)
                             and isinstance(v.get("name"), str) and isinstance(v.get("pk"), str)}
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=1)
            os.replace(self.path + ".tmp", self.path)
        except OSError:
            pass

    def add(self, uid, pk, name, nick, xpk=None):
        old = self.data.get(uid) or {}
        self.data[uid] = {"name": name, "pk": pk, "nick": nick,
                          "since": old.get("since", time.strftime("%Y-%m-%d")),
                          "xpk": xpk or old.get("xpk")}
        self.save()

    def remove(self, uid):
        if self.data.pop(uid, None) is not None:
            self.save()


def friend_keys(shared, a_eph, b_eph):
    """Two keys for a friend exchange: requester->acceptor and acceptor->requester."""
    keys = HKDF(algorithm=hashes.SHA256(), length=64, salt=None,
                info=b"ipchat-friend|" + a_eph + b_eph).derive(shared)
    return keys[:32], keys[32:]


def lobby_key(identity, friend_xpk_hex):
    """A key only you and one specific friend can compute, with no need to be connected
    right now - used to encrypt "I'm hosting a room" beacons for the relay search."""
    shared = identity.x_priv.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(friend_xpk_hex)))
    context = b"ipchat-lobby|" + b"|".join(sorted([identity.x_pub_hex.encode("utf-8"),
                                                    friend_xpk_hex.encode("utf-8")]))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=context).derive(shared)


def handshake(sock, password, is_host, nickname, identity=None, slow_fail=None):
    """Returns (SecureChannel, nickname_of_the_other_person),
    or raises HandshakeError (e.g. wrong password)."""
    sock.settimeout(HANDSHAKE_TIMEOUT)
    chan = None
    try:
        pw = password.encode("utf-8")
        ids = {"idA": b"ipchat-host", "idB": b"ipchat-client"}
        spake = SPAKE2_A(pw, **ids) if is_host else SPAKE2_B(pw, **ids)

        send_frame(sock, spake.start())
        shared = spake.finish(recv_frame(sock, limit=256))

        keys = HKDF(algorithm=hashes.SHA256(), length=64, salt=None,
                    info=b"ipchat v1 keys").derive(shared)
        host_to_client, client_to_host = keys[:32], keys[32:]
        if is_host:
            chan = SecureChannel(sock, host_to_client, client_to_host)
        else:
            chan = SecureChannel(sock, client_to_host, host_to_client)

        # Key confirmation: SPAKE2 itself doesn't fail on a wrong password,
        # the two sides just end up with different keys. Decrypting this
        # first message only works if the keys (= passwords) match.
        # The nicknames travel inside these (encrypted) messages.
        hello = "ipchat-ready:"
        if is_host:
            theirs = chan.recv_text()
            chan.send_text(hello + nickname)
        else:
            chan.send_text(hello + nickname)
            theirs = chan.recv_text()
        if not theirs.startswith(hello):
            raise HandshakeError("bad confirmation")
        peer_name = clean_nickname(theirs[len(hello):]) or "Friend"

        # Who is it really? Each side proves it owns its friend ID by signing something
        # only this connection knows. (Sent encrypted, after the password was checked.)
        binding = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                       info=b"ipchat id binding").derive(shared)
        mine = b"host" if is_host else b"client"
        theirs_role = b"client" if is_host else b"host"
        note = "{}"
        if identity is not None:
            note = json.dumps({"pk": identity.pub_hex,
                               "sig": identity.sign(b"ipchat-id|" + mine + binding).hex()})
        if is_host:
            their_note = chan.recv_text()
            chan.send_text("ipchat-id:" + note)
        else:
            chan.send_text("ipchat-id:" + note)
            their_note = chan.recv_text()
        chan.peer_identity = None
        if their_note.startswith("ipchat-id:"):
            try:
                d = json.loads(their_note[len("ipchat-id:"):])
                if d and verify_sig(d["pk"], d["sig"], b"ipchat-id|" + theirs_role + binding):
                    chan.peer_identity = (uid_from_pub(bytes.fromhex(d["pk"])), d["pk"])
            except (ValueError, KeyError, TypeError):
                chan.peer_identity = None

        sock.settimeout(None)
        return chan, peer_name
    except Exception as e:
        if is_host and slow_fail is not None:
            slow_fail()          # delay BEFORE the socket closes, or it throttles nothing
        if chan is not None:
            chan.close()
        raise HandshakeError(str(e)) from e


# ======================================================================
#  File transfer state
# ======================================================================
class FileTransfer:
    """One file on its way out (outgoing=True) or in (outgoing=False).

    outgoing states: waiting -> active -> finishing -> done
    incoming states: offered -> active -> done
    either one can also end as: rejected, cancelled or failed."""

    def __init__(self, tid, name, size, outgoing, path=None, peer=None):
        self.id = tid
        self.peer = peer              # id of the other person (receiver if outgoing, sender if not)
        self.name = name
        self.size = size
        self.outgoing = outgoing
        self.path = path              # source file (outgoing) / final location (incoming)
        self.part = None              # incoming: the temporary ".part" file
        self.state = "waiting" if outgoing else "offered"
        self.cancel = threading.Event()   # outgoing: tells the sender thread to stop
        self.lock = threading.Lock()      # incoming: guards file, checksum and counters
        self.file = None
        self.hash = hashlib.sha256()
        self.done = 0
        self.frac = 0.0
        self.last_post = 0.0
        self.status_lbl = self.bar = self.btn_row = None   # widgets of its chat card


# ======================================================================
#  Rooms (what the host keeps track of)
# ======================================================================
class Member:
    """Someone who got into the room (the host itself is not a Member)."""

    def __init__(self, mid, name, chan, addr):
        self.id = mid
        self.name = name
        self.chan = chan
        self.addr = addr
        self.uid = None           # friend ID (verified), if their program has one
        self.pk = None
        self.kicked = False       # the host removed this person
        self.reason = None        # how to word it in the room: "was kicked from the room"
        self.last_seen = time.monotonic()   # relay only: last time anything arrived from them


class Room:
    """Everything the host knows about the room it is running. Network threads
    and the window both use it, so every change goes through the lock."""

    def __init__(self, session, host_name, password, max_people, server_sock):
        self.session = session
        self.host_name = host_name
        self.password = password
        self.max_people = max_people       # total, including the host
        self.server_sock = server_sock
        self.lock = threading.RLock()
        self.members = {}                  # id -> Member
        self.next_id = 1
        self.pending = set()               # sockets that are still logging in
        self.pending_ip = {}               # IP address -> how many of those are theirs
        self.closed = False
        self.fail_lock = threading.Lock()  # makes wrong-password delays queue up
        self.host_uid = None               # the host's own friend ID and public key
        self.host_pk = None
        self.rid = secrets.token_hex(4)    # identifies this room in announcements
        self.hidden = False                # hidden rooms do not announce themselves
        self.knock_port = 0                # where "request to join" messages arrive (0 = none)
        self.knock_seen = {}               # (ip, kind) -> when we last showed one
        self.banned = {}                   # IP address -> name the person had when banned
        self.banned_uids = {}              # friend ID -> name, for bans that must survive
        self.ban_notice = {}               # IP address -> when the host last heard about an attempt
        self.relay = False                 # True when this room runs over the internet relay
        self.room_code = None

    def people(self):
        """[{"id", "name"}] for everyone, the host first."""
        with self.lock:
            return [{"id": HOST_ID, "name": self.host_name, "uid": self.host_uid,
                     "pk": self.host_pk}] + \
                   [{"id": m.id, "name": m.name, "uid": m.uid, "pk": m.pk}
                    for m in self.members.values()]

    def admit(self, wanted, chan, addr):
        """Adds a new member, or returns None when the room is full or closed.
        A name that is already taken gets a number: Bob -> Bob (2)."""
        with self.lock:
            if self.closed or len(self.members) + 1 >= self.max_people:
                return None
            taken = {self.host_name.lower()} | {m.name.lower() for m in self.members.values()}
            name, n = wanted, 2
            while name.lower() in taken:
                name = f"{wanted} ({n})"
                n += 1
            member = Member(self.next_id, name, chan, addr)
            self.next_id += 1
            self.members[member.id] = member
            return member

    def remove(self, member):
        with self.lock:
            return self.members.pop(member.id, None) is not None

    def get(self, mid):
        with self.lock:
            return self.members.get(mid)

    def others(self, skip=None):
        with self.lock:
            return [m for m in self.members.values() if m is not skip]

    def send_all(self, kind, payload, skip=None):
        for m in self.others(skip):
            try:
                m.chan.send(kind, payload)
            except OSError:
                pass


# ======================================================================
#  The internet relay
#
#  An alternative to connecting directly: both sides only ever make OUTGOING
#  connections to a small, free public message relay (MQTT, over TLS), so nobody
#  needs to share an IP address, open a port, or be on the same network. Once the
#  password-protected handshake (SPAKE2 + ChaCha20Poly1305, exactly the same as a
#  direct connection) is done, messages are exactly as encrypted as always - the
#  relay only ever sees ciphertext. What the relay (or anyone watching it) CAN see
#  is metadata: that a room with this code exists, and roughly when people in it
#  are active. It is also a third party the host has no control over, and a lone
#  attacker can occupy all of a room's "logging in" slots more easily than over a
#  direct connection, since there is no IP address to tell two attempts apart.
#  MqttPipe below makes one end of that connection look exactly like a plain
#  socket (sendall/recv/settimeout/close), so none of the code above needs to
#  know a connection is going through the relay instead of straight to the host.
# ======================================================================
class MqttPipe:
    """One end of a relay connection, made to look like a socket. Every chunk of
    bytes gets a sequence number, so even if the relay (or network) re-delivers
    or re-orders a message, the stream handed to the rest of the program is
    still exactly what was sent, once each, in order - the same guarantee a
    real TCP socket already gives the rest of this file."""

    def __init__(self, client, my_topic, their_topic, first_message=None):
        self.client, self.my_topic, self.their_topic = client, my_topic, their_topic
        self.cv = threading.Condition()
        self.buf = bytearray()
        self.pending = {}          # out-of-order chunks, waiting for the gap to fill
        self.next_in = 0
        self.next_out = 0
        self.closed = False
        self.timeout = None
        self._inflight = collections.deque()  # publishes not yet acknowledged, oldest first
        if first_message is not None:
            self.feed(first_message)

    def feed(self, payload):
        """Called (from the MQTT thread) whenever a message for this pipe arrives."""
        if len(payload) < 4:
            return
        seq = struct.unpack(">I", payload[:4])[0]
        with self.cv:
            if seq >= self.next_in:
                self.pending[seq] = payload[4:]
                while self.next_in in self.pending:
                    self.buf += self.pending.pop(self.next_in)
                    self.next_in += 1
                if len(self.pending) > 2000:               # a gap that will never fill
                    self.closed = True
            self.cv.notify_all()

    def sendall(self, data):
        """Publishes one piece and returns - it does NOT wait for the broker to
        acknowledge it. Waiting on every single piece before sending the next used to
        make file transfers over the relay slow (one full round trip per 32KB chunk)
        and made one slow acknowledgement kill the whole connection. Instead, pieces
        are pipelined: up to MQTT_INFLIGHT_WINDOW may be unacknowledged at once, and a
        slow (not failed) acknowledgement is just backpressure, never a reason to give
        up on the connection - an actually dead link is caught by the heartbeat
        (see ping_loop/RELAY_PING_TIMEOUT), which doesn't depend on anyone sending
        anything at all, let alone a file."""
        if self.closed:
            raise OSError("the relay connection is closed")
        with self.cv:
            seq, self.next_out = self.next_out, self.next_out + 1
        try:
            info = self.client.publish(self.their_topic, struct.pack(">I", seq) + bytes(data), qos=1)
        except (OSError, ValueError, RuntimeError) as e:
            raise OSError(f"the relay is not reachable: {e}") from e
        self._inflight.append(info)
        while len(self._inflight) > MQTT_INFLIGHT_WINDOW:
            oldest = self._inflight.popleft()
            try:
                oldest.wait_for_publish(timeout=MQTT_PUBLISH_RETRY_WAIT)
            except (ValueError, RuntimeError):
                pass  # just slow, not dead - the heartbeat is what decides that

    def recv(self, n):
        with self.cv:
            end = None if self.timeout is None else time.monotonic() + self.timeout
            while not self.buf and not self.closed:
                left = None if end is None else max(0.0, end - time.monotonic())
                if left == 0.0 or not self.cv.wait(left):
                    raise TimeoutError("timed out waiting for the relay")
            if not self.buf:
                return b""                                  # closed: like a TCP socket's FIN
            take = bytes(self.buf[:n])
            del self.buf[:len(take)]
            return take

    def settimeout(self, t):
        self.timeout = t

    def shutdown(self, how=None):
        pass

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()


def mqtt_client(client_id):
    c = mqtt_lib.Client(mqtt_lib.CallbackAPIVersion.VERSION2, client_id=client_id)
    c.tls_set()
    return c


class RelayListener:
    """Looks enough like a listening TCP socket (accept/close/shutdown) that the
    host's existing accept loop can use it without any changes. One MQTT client
    serves a whole room; anyone who knows the room code may try to connect - same
    as anyone who knows an IP address could - but the password is still what
    actually keeps them out."""

    def __init__(self, code):
        self.code = code
        self.to_host = RELAY_PREFIX + "r/" + code + "/g/"      # guest -> host (wildcard for us)
        self.to_guest = RELAY_PREFIX + "r/" + code + "/h/"     # host -> one guest
        self.cv = threading.Condition()
        self.queue = []
        self.known = {}
        self.closed = False
        self.error = None
        self.client = mqtt_client("ipchat-h-" + secrets.token_hex(8))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        try:
            self.client.connect(RELAY_HOST, RELAY_PORT, 60)
        except OSError as e:
            raise OSError(f"could not reach the relay: {e}") from e
        self.client.loop_start()

    def _on_connect(self, c, u, flags, rc, props=None):
        if rc == 0:
            c.subscribe(self.to_host + "+", qos=1)
        else:
            with self.cv:
                self.error = f"the relay refused the connection ({rc})"
                self.closed = True
                self.cv.notify_all()

    def _on_message(self, c, u, m):
        connid = m.topic.rsplit("/", 1)[-1]
        pipe = self.known.get(connid)
        if pipe is not None:
            pipe.feed(m.payload)
            return
        with self.cv:
            if self.closed or connid in self.known:
                return
            pipe = MqttPipe(self.client, self.to_host + connid, self.to_guest + connid,
                            first_message=m.payload)
            self.known[connid] = pipe
            self.queue.append((pipe, (f"relay:{connid}", 0)))
            self.cv.notify_all()

    def accept(self):
        with self.cv:
            while not self.queue and not self.closed:
                self.cv.wait(1)
            if self.queue:
                return self.queue.pop(0)
        raise OSError(self.error or "the relay room is closed")

    def shutdown(self, how=None):
        pass

    def close(self):
        with self.cv:
            self.closed = True
            self.cv.notify_all()
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass


# ======================================================================
#  Emoji shortcodes: typing :sob: gives 😭
#  Uses the "emoji" package when it is installed (pip install emoji); a few of the
#  most used ones also work without it.
# ======================================================================
BASIC_EMOJI = {
    "sob": "😭", "joy": "😂", "smile": "😄", "grin": "😁", "laughing": "😆", "wink": "😉",
    "blush": "😊", "heart_eyes": "😍", "kissing_heart": "😘", "sunglasses": "😎",
    "thinking": "🤔", "neutral_face": "😐", "unamused": "😒", "rage": "😡", "angry": "😠",
    "cry": "😢", "scream": "😱", "sleeping": "😴", "skull": "💀", "fire": "🔥",
    "heart": "❤️", "broken_heart": "💔", "thumbsup": "👍", "thumbs_up": "👍", "+1": "👍",
    "thumbsdown": "👎", "thumbs_down": "👎", "-1": "👎", "clap": "👏", "pray": "🙏",
    "wave": "👋", "ok_hand": "👌", "muscle": "💪", "eyes": "👀", "tada": "🎉", "100": "💯",
    "star": "⭐", "sparkles": "✨", "party": "🥳", "pensive": "😔", "sweat_smile": "😅",
    "rofl": "🤣", "facepalm": "🤦", "shrug": "🤷", "poop": "💩", "ghost": "👻",
    "check": "✅", "x": "❌", "warning": "⚠️", "question": "❓", "zzz": "💤",
}
SHORTCODE = re.compile(r":([A-Za-z0-9_+\-]{1,40}):")
try:
    import emoji as emoji_lib
except ImportError:
    emoji_lib = None


EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}"
    "|[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\u2764]"
    "(?:\uFE0F|[\U0001F3FB-\U0001F3FF])?"
    "(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF](?:\uFE0F)?)*)")
EMOJI_FONTS = [
    r"C:\Windows\Fonts\seguiemj.ttf",                       # Windows
    "/System/Library/Fonts/Apple Color Emoji.ttc",            # macOS
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",      # Linux
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]


class EmojiImages:
    """Draws emoji in full colour. Tk itself can only draw them as flat black-and-white
    shapes, so with Pillow installed (pip install pillow) each emoji in a message is
    drawn from the system's colour emoji font and shown as a small picture."""

    SIZE = 16      # a little smaller than a line of text, so lines don't grow taller

    def __init__(self, root):
        self.root = root
        self.font = None
        self.cache = {}
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageTk
            self.pil = (Image, ImageDraw, ImageTk)
        except ImportError:
            return
        for path in EMOJI_FONTS:
            if not os.path.exists(path):
                continue
            for size in (109, 96, 136, 160, 64, 40):   # bitmap fonts only exist in fixed sizes
                try:
                    self.font = ImageFont.truetype(path, size)
                    return
                except (OSError, ValueError):
                    continue

    @property
    def available(self):
        return self.font is not None

    def has_emoji(self, text):
        return self.available and EMOJI_RE.search(text) is not None

    def get(self, cluster, bg):
        key = (cluster, bg)
        if key not in self.cache:
            self.cache[key] = self._render(cluster, bg)
        return self.cache[key]

    def _render(self, cluster, bg):
        Image, ImageDraw, ImageTk = self.pil
        try:
            big = 200
            im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            ImageDraw.Draw(im).text((20, 20), cluster, font=self.font, embedded_color=True)
            box = im.getbbox()
            if box is None:
                return None
            im = im.crop(box)
            scale = self.SIZE / max(im.size)
            im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                           Image.LANCZOS)
            canvas = Image.new("RGBA", (self.SIZE, self.SIZE), bg)
            canvas.alpha_composite(im, ((self.SIZE - im.width) // 2, (self.SIZE - im.height) // 2))
            return ImageTk.PhotoImage(canvas.convert("RGB"), master=self.root)
        except Exception:
            return None


def emojize(text):
    """:sob: -> 😭  (unknown codes are left exactly as typed)."""
    if ":" not in text:
        return text
    if emoji_lib is not None:
        try:
            text = emoji_lib.emojize(text, language="alias")
        except Exception:
            pass
    return SHORTCODE.sub(lambda m: BASIC_EMOJI.get(m.group(1).lower(), m.group(0)), text)


# ======================================================================
#  Word filter
#
#  safetext finds the swear words (English, including forms like "fucking" or
#  "bitches"). On top of that this adds what people do to get around filters:
#  stretched letters (fuuuck), symbols (f*ck, a$$hole, sh!t), dots or dashes
#  between letters (f.u.c.k), missing vowels (fck), words glued together with
#  underscores. safetext has no Dutch, so a short Dutch list is built in.
#  More words can go in a file called filter_words.txt next to this script
#  (one word per line).
# ======================================================================
LEET = {"@": "a", "$": "s", "0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "5": "s",
        "7": "t", "+": "t"}
MASK_CHARS = "*#%&?^~"          # people "censor" themselves with these: f*ck
JOINERS = re.compile(r"[_/\\|,;:()\[\]{}<>\"'`]+")   # glue words together: fuck_you
EDGE_PUNCT = ".,!?…-–—"
VOWELS = "aeiou"
EXTRA_SUFFIXES = ("", "s", "es", "ed", "er", "ers", "ing", "in", "y", "ie", "ies", "head",
                  "face", "en", "ten", "ken", "je", "jes")
EXTRA_WORDS = {
    # English (safetext adds many more when it is installed)
    "fuck", "shit", "bitch", "bastard", "asshole", "ass", "arse", "arsehole", "dick", "cock",
    "cunt", "pussy", "twat", "prick", "whore", "slut", "wank", "wanker", "bollocks", "piss",
    "motherfuck", "bullshit", "dumbass", "jackass", "dipshit", "tits", "nigger", "nigga",
    "faggot", "fag", "retard", "douche", "douchebag",
    "kys", "kkr", "homo", "rape", "raped", "raping", "rapist", "rapists", "goon", "cum",
    "cumming", "cummed", "cumshot",
    # short chat abbreviations
    "wtf", "stfu", "omfg", "gtfo", "ffs",
    # Dutch
    "kut", "kutwijf", "klote", "klootzak", "kloothommel", "lul", "lulhannes", "hoer", "slet",
    "trut", "teef", "flikker", "kanker", "kankerlijer", "kankerhoer", "tering", "teringlijer",
    "tyfus", "tyfuslijer", "godverdomme", "godverdomd", "godver", "verdomme", "verdomd",
    "neuk", "neuken", "pik", "rotzak", "idioot",
}


def _collapse(word, keep):
    """Squeezes repeated letters: keep=1 -> fuuuck = fuck, keep=2 -> fuuuck = fuuck."""
    if keep == 1:
        return re.sub(r"(.)\1+", r"\1", word)
    return re.sub(r"(.)\1{2,}", r"\1\1", word)


class WordFilter:
    def __init__(self):
        self.engine = None
        try:
            try:
                import lingua  # noqa: F401  (safetext wants it, but only to guess languages)
            except ImportError:
                # Not installed (it needs a C++ compiler on new Python versions). We always
                # tell safetext the language, so a stand-in is enough.
                import types
                stub = types.ModuleType("lingua")
                stub.Language = stub.LanguageDetectorBuilder = object
                sys.modules["lingua"] = stub
            from safetext import SafeText
            self.engine = SafeText(language="en")
        except Exception:
            self.engine = None          # not installed: the filter can't be switched on
        self.extra = set(EXTRA_WORDS)
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "filter_words.txt"), encoding="utf-8") as f:
                for line in f:
                    word = line.strip().lower()
                    if word and not word.startswith("#"):
                        self.extra.add(word)
        except (OSError, NameError):
            pass
        self._cache = {}

    @property
    def available(self):
        return self.engine is not None

    def find(self, text):
        """Returns [(start, end)] of every swear word in `text`."""
        spans = []
        if self.engine is not None:
            try:
                spans = [(int(r["start"]), int(r["end"]))
                         for r in self.engine.check_profanity(text=text)]
            except Exception:
                spans = []
        deadline = time.monotonic() + 0.25      # never let one huge message freeze the window
        for n, m in enumerate(re.finditer(r"\S+", text)):
            if n >= 300 or time.monotonic() > deadline:
                break
            start, end = m.span()
            if any(a < end and b > start for a, b in spans):
                continue                        # safetext already caught (part of) this one
            for a, b, piece in self._pieces(m.group(), start):
                if self._piece_is_bad(piece):
                    spans.append((a, b))
        return self._merge(spans, len(text))

    @staticmethod
    def _merge(spans, length):
        out = []
        for a, b in sorted((max(0, a), min(length, b)) for a, b in spans if b > a):
            if out and a <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], b))
            else:
                out.append((a, b))
        return out

    @staticmethod
    def _pieces(token, offset):
        """Splits glued words (fuck_you) and trims punctuation around each part."""
        pos = 0
        for part in JOINERS.split(token):
            a = token.index(part, pos) if part else pos
            pos = a + len(part)
            core = part.strip(EDGE_PUNCT)
            if core and len(core) <= 40:
                lead = len(part) - len(part.lstrip(EDGE_PUNCT))
                yield offset + a + lead, offset + a + lead + len(core), core

    def _piece_is_bad(self, piece):
        if not any(ch.isalpha() for ch in piece):
            return False
        return any(self._is_bad(v) for v in self._variants(piece))

    def _variants(self, piece):
        """Every plain-letter spelling this piece could be hiding."""
        low = piece.lower()
        out = set()
        for base in {low, re.sub(r"[.\-·•]", "", low)}:
            forms = {base}
            masks = [i for i, ch in enumerate(base) if ch in MASK_CHARS]
            if 0 < len(masks) <= 3:
                for i in masks:
                    forms = {f[:i] + v + f[i + 1:] for f in forms for v in VOWELS}
            for f in forms:
                for g in (f, "".join(LEET.get(ch, ch) for ch in f)):
                    g = "".join(ch for ch in g if ch.isalpha())
                    if len(g) >= 3:
                        for h in {g, g.replace("v", "u")}:      # fvck
                            out.update((h, _collapse(h, 1), _collapse(h, 2)))
        for g in list(out):   # no vowels at all (fck, sht, btch): try putting one back
            if 3 <= len(g) <= 8 and not any(ch in VOWELS for ch in g):
                for i in range(len(g) + 1):
                    for v in VOWELS:
                        out.add(g[:i] + v + g[i:])
        return out

    def _is_bad(self, word):
        hit = self._cache.get(word)
        if hit is None:
            hit = any(word.startswith(w) and word[len(w):] in EXTRA_SUFFIXES for w in self.extra)
            if not hit and self.engine is not None:
                try:
                    hit = bool(self.engine.check_profanity(text=word))
                except Exception:
                    hit = False
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[word] = hit
        return hit


# ======================================================================
#  GUI helpers
# ======================================================================
def mix(c1, c2, t):
    """Colour between two #rrggbb colours (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


class Switch(tk.Canvas):
    """A small on/off switch: white outline, green when on, red when off.
    It reacts the moment the mouse goes down (the knob squeezes) and flips on
    release; the knob and colour then glide over in a fraction of a second."""
    W, H = 42, 22

    def __init__(self, parent, bg, on=False, command=None):
        super().__init__(parent, width=self.W, height=self.H, bg=bg, highlightthickness=0,
                         bd=0, cursor="hand2", takefocus=1)
        self.on = bool(on)
        self.command = command
        self.pos = 1.0 if self.on else 0.0     # 0 = left (off) ... 1 = right (on)
        self.hover = False
        self.pressed = False
        self.job = None
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<space>", lambda e: self.toggle())
        self.bind("<FocusIn>", lambda e: self.draw())
        self.bind("<FocusOut>", lambda e: self.draw())
        self.draw()

    def _set_hover(self, value):
        self.hover = value
        if not value:
            self.pressed = False
        self.draw()

    def _press(self, event):
        self.pressed = True
        self.draw()

    def _release(self, event):
        was = self.pressed
        self.pressed = False
        inside = 0 <= event.x < self.W and 0 <= event.y < self.H
        if was and inside:
            self.toggle()
        else:
            self.draw()

    def toggle(self):
        self.set(not self.on, notify=True)

    def set(self, on, notify=False):
        on = bool(on)
        if on != self.on:
            self.on = on
            self.glide()
        else:
            self.draw()
        if notify and self.command:
            self.command(self.on)

    def glide(self):
        if self.job is not None:
            self.after_cancel(self.job)
            self.job = None
        goal = 1.0 if self.on else 0.0

        def step():
            self.job = None
            if abs(goal - self.pos) < 0.12:
                self.pos = goal
            else:
                self.pos += (goal - self.pos) * 0.5
                self.job = self.after(14, step)
            self.draw()
        step()

    def draw(self):
        self.delete("all")
        H, W = self.H, self.W
        base = mix(RED, GREEN, self.pos)
        if self.hover:
            base = mix(base, "#ffffff", 0.18)
        r = H / 2
        # white outline, then the coloured track on top of it
        outline = "#ffffff" if on_color(PANEL) == "#ffffff" else "#111827"   # white (dark on light themes)
        self.create_line(r, r, W - r, r, width=H - 1, capstyle="round", fill=outline)
        self.create_line(r, r, W - r, r, width=H - 5, capstyle="round", fill=base)
        kr = 6.0 + (1.5 if self.pressed else 0.0)       # the knob squeezes wider when pressed
        cx = r + self.pos * (W - 2 * r)
        self.create_oval(cx - kr, r - kr, cx + kr, r + kr, fill="#ffffff", outline="")
        if self.focus_get() is self:
            self.create_rectangle(0, 0, W - 1, H - 1, outline=ACCENT)


def make_button(parent, text, bg, hover_bg, command, **kw):
    font = kw.pop("font", FONT_BOLD)
    fg = on_color(bg)
    btn = tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                    activebackground=hover_bg, activeforeground=fg,
                    relief="flat", bd=0, cursor="hand2", font=font, **kw)
    btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg))
    return btn


def make_entry(parent, show="", limit=None):
    entry = tk.Entry(parent, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat",
                     font=("Segoe UI", 11), show=show, highlightthickness=1,
                     highlightbackground=LINE, highlightcolor=ACCENT, width=28)
    if limit:  # typing/pasting beyond `limit` characters gets cut off
        var = tk.StringVar(master=parent)
        var.trace_add("write", lambda *a: var.set(var.get()[:limit]) if len(var.get()) > limit else None)
        entry.config(textvariable=var)
        entry.var = var  # keep a reference so it isn't garbage collected
    return entry


def rounded_rect_points(x0, y0, x1, y1, r):
    """Point list for a Canvas create_polygon(..., smooth=True) that traces a
    rectangle with rounded corners - the standard way to fake them in classic Tk,
    which has no native support for rounded corners on a Frame, Label or Text."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    return [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r,
            x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
            x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]


class RoundedPanel(tk.Frame):
    """A soft-cornered panel: paints a rounded rectangle on a Canvas and sits a
    plain rectangular Frame (`.content`) on top of it, inset by at least the
    corner radius on every side so the content's own sharp corners always land
    inside the curve and never peek out past it. `.content` is used exactly like
    an ordinary Frame - pack/grid things into it as usual - and the panel resizes
    and redraws itself automatically to fit whatever ends up inside."""

    def __init__(self, parent, bg, radius=16, outer_bg=None, **content_kw):
        outer_bg = parent["bg"] if outer_bg is None else outer_bg
        super().__init__(parent, bg=outer_bg)
        self.radius = radius
        self.canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.content = tk.Frame(self.canvas, bg=bg, **content_kw)
        self._win = self.canvas.create_window(radius, radius, window=self.content, anchor="nw")
        self._shape = None
        self.content.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        r = self.radius
        w = max(1, self.content.winfo_reqwidth())
        h = max(1, self.content.winfo_reqheight())
        cw, ch = w + 2 * r, h + 2 * r
        self.canvas.config(width=cw, height=ch)
        pts = rounded_rect_points(0, 0, cw, ch, r)
        if self._shape is None:
            self._shape = self.canvas.create_polygon(pts, smooth=True,
                                                      fill=self.content["bg"], outline="")
            self.canvas.tag_lower(self._shape)
        else:
            self.canvas.coords(self._shape, *pts)

    def set_fill(self, color):
        """Lets an animation (see animate_bubble_in) fade the rounded background
        in step with the content inside it."""
        self.content.config(bg=color)
        if self._shape is not None:
            self.canvas.itemconfig(self._shape, fill=color)
        self.canvas.config(bg=self["bg"])


class RoundedBubble(tk.Frame):
    """A chat bubble's rounded-corner shell: paints a rounded rectangle on a
    Canvas and embeds the bubble's own widget (a Label for plain text, a Text
    for spoilers/markdown) on top of it via attach(). The wrapped widget is
    otherwise used exactly as before - this only paints behind it, and keeps the
    shape in sync as it resizes, including mid-animation (see animate_bubble_in,
    which calls set_fill() to fade the shape's colour along with the widget's)."""

    def __init__(self, parent, bg, radius=12):
        outer_bg = parent["bg"]
        super().__init__(parent, bg=outer_bg)
        self.radius = radius
        self.canvas = tk.Canvas(self, bg=outer_bg, highlightthickness=0, bd=0)
        self.canvas.pack()
        self._fill = bg
        self.widget = None
        self._shape = None

    def attach(self, widget):
        """`widget` must already be a child of self.canvas (it embeds via
        canvas.create_window, which only works for an actual descendant)."""
        self.widget = widget
        self.canvas.create_window(0, 0, window=widget, anchor="nw")
        widget.bind("<Configure>", self._redraw, add="+")
        self._redraw()

    def _redraw(self, event=None):
        r = self.radius
        w = max(1, self.widget.winfo_reqwidth())
        h = max(1, self.widget.winfo_reqheight())
        self.canvas.config(width=w, height=h)
        pts = rounded_rect_points(0, 0, w, h, r)
        if self._shape is None:
            self._shape = self.canvas.create_polygon(pts, smooth=True,
                                                      fill=self._fill, outline="")
            self.canvas.tag_lower(self._shape)
        else:
            self.canvas.coords(self._shape, *pts)

    def set_fill(self, color):
        self._fill = color
        if self.widget is not None:
            self.widget.config(bg=color)
        if self._shape is not None:
            self.canvas.itemconfig(self._shape, fill=color)


def center_window(win, width=None, height=None, parent=None):
    """Puts a window in the middle of the screen (or in the middle of `parent`)."""
    win.update_idletasks()
    w = width or win.winfo_reqwidth()
    h = height or win.winfo_reqheight()
    if parent is not None:
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
    else:
        x = (win.winfo_screenwidth() - w) // 2
        y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")


def place_half_screen(win, side):
    """Resizes and moves `win` to cover the left or right half of the screen, full
    height - used so two testing clients (see open_new_client) can sit side by side
    where you can see both at once, instead of stacked on top of each other."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w = sw // 2
    x = 0 if side == "left" else sw - w
    win.geometry(f"{w}x{sh}+{x}+0")


def minimize_console():
    """Minimizes the command prompt window this program was started from."""
    if os.name != "nt":
        return
    try:
        from ctypes import wintypes
        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return  # started without a console (e.g. through .pyw)
        # Inside Windows Terminal the "console window" is an invisible helper;
        # the real window that has to be minimized is its root owner.
        real = user32.GetAncestor(hwnd, 3)  # GA_ROOTOWNER
        user32.ShowWindow(real or hwnd, 7)  # SW_SHOWMINNOACTIVE: minimize, don't steal focus
    except Exception:
        pass  # purely cosmetic, never worth a crash


def ensure_installed():
    """Runs before any window is shown - a plain console flashing open and then
    suddenly closing is confusing, so this has to happen before there's anything to
    show at all, not as a delayed "looks stable" check once the GUI is already up.

    The first time the downloaded ip-chat<version>.py is run from wherever it was
    saved (Downloads, the Desktop, ...), this installs it properly: makes the "IP
    Chat" folder in AppData, fetches the real, current script and the window/shortcut
    icon straight from GitHub into it (falling back to just moving in whatever copy
    is already running if GitHub can't be reached), and builds the "IP Chat.lnk"
    shortcut there too - one tidy folder instead of loose files scattered wherever
    someone happened to download from. This also doubles as how an older install
    (from before this folder existed) migrates the first time it's run after
    updating, since the running copy's path won't match the installed one either.

    Once installed, later launches (through that shortcut, or just double-clicking
    the installed copy itself) are already in the right spot and this does nothing -
    it never reinstalls itself on top of a copy that's already in place. Returns True
    if it just installed and relaunched the installed copy (the caller should exit
    immediately without ever creating a window), False if nothing needed installing
    and startup should continue right here."""
    target = os.path.join(appdata_dir(), "ip-chat.pyw")
    current = os.path.abspath(sys.argv[0])
    if os.path.normcase(current) == os.path.normcase(target):
        return False   # already running the installed copy

    try:
        os.makedirs(appdata_dir(), exist_ok=True)
    except OSError:
        return False   # can't even make the folder - just keep running in place

    ensure_icon()   # best effort; a missing icon never blocks installing

    content = None
    try:
        manifest = fetch_latest_release()
        data = download_bytes(manifest["url"])
        expected = manifest.get("git_sha")
        if not expected or git_blob_sha1(data) == str(expected).strip().lower():
            compile(data, "ip-chat-install.py", "exec")   # reject a broken/truncated download
            content = data
    except Exception:
        content = None   # offline, repo unreachable, etc. - fall back to our own bytes below

    if content is None:
        try:
            with open(current, "rb") as f:
                content = f.read()   # whatever was actually downloaded still runs fine
        except OSError:
            return False

    try:
        tmp = target + ".new"
        with open(tmp, "wb") as f:
            f.write(content)
        os.replace(tmp, target)
    except OSError:
        return False

    try:
        create_shortcut(target, icon_path() if os.path.exists(icon_path()) else None)
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass   # the shortcut is a nice-to-have - a failed one shouldn't block installing

    exe = sys.executable
    if os.name == "nt":
        pyw_exe = os.path.join(os.path.dirname(sys.executable) or "", "pythonw.exe")
        if os.path.exists(pyw_exe):
            exe = pyw_exe
    try:
        subprocess.Popen([exe, target] + sys.argv[1:], cwd=appdata_dir())
    except OSError:
        return False
    return True


# ======================================================================
#  GUI
# ======================================================================
class ChatApp:
    ROW_H = 28            # height of one line in the people list
    PEOPLE_MAX_H = 168    # the people list scrolls when it gets taller than this

    def __init__(self, root, data_dir=None):
        self.root = root
        self.data_dir = data_dir or os.path.dirname(settings_path())
        self.identity = None       # who we are (set by boot_identity)
        self.friends = FriendStore(self.data_dir).data
        self.friend_store = None
        self.peer_ids = {}         # person id in this room -> (friend ID, public key), verified
        self.friend_out = {}       # requests we sent: person id -> details
        self.friend_in = {}        # requests we got: person id -> details
        self.friend_wait = {}      # requests we accepted, waiting for their name
        self._xpk_asked = set()    # friends we already asked to refresh their relay-search key
        self.test_friends = {}     # same-PC testing only: never saved, never on the Friends page
        self._test_tried = set()   # people we already tried to same-PC test-friend
        self._loopback_peers = set()     # host: ids of members connected via 127.0.0.1
        self._joined_via_loopback = False  # guest: true if we connected to 127.0.0.1
        self.dev_unlocked = False   # Settings opened with Shift+Ctrl held: shows testing options
        self.open_person = None    # whose details are open in the People list
        self.relay = False         # True while the current room goes over the internet relay
        self.found_relay = {}      # friends' relay rooms seen while searching: code -> info
        self.relay_search = None   # the MQTT client used while searching for friends' rooms
        apply_theme(load_settings().get("theme", "default"))
        self.root.title("IP Chat")
        icon = icon_path()
        if os.path.exists(icon):
            try:
                self.root.iconbitmap(default=icon)   # same .ico as the taskbar shortcut
            except tk.TclError:
                pass   # not every platform can load a .ico this way - never worth a crash
        half = next((a[len(ARG_HALF_PREFIX):] for a in sys.argv[1:]
                     if a.startswith(ARG_HALF_PREFIX)), None)
        if half in ("left", "right"):
            # a testing client opened via "Open a new client" - sits on its half of
            # the screen instead of the usual centred, fixed-size window.
            place_half_screen(self.root, half)
        else:
            center_window(self.root, 480, 640)
        self.root.minsize(400, 580)
        self.root.configure(bg=BG)

        self.room = None          # the Room we run (only while hosting)
        self.is_host = False
        self.conn_sock = None     # raw socket while connecting as a guest
        self.channel = None       # encrypted channel to the host (guests only)
        self.session = 0          # bumped on every new host/connect/disconnect, so
                                  # late messages from old network threads are ignored
        self.incoming = queue.Queue()  # network threads -> GUI thread
        self.bubbles = []         # message labels (their wrap width follows the window)
        self.host_details = ""
        self.nickname = ""        # how this person appears to the others
        self.my_id = None         # our id in the room (the host is HOST_ID)
        self.people = []          # [(id, name)] everybody in the room, host first
        self.names = {}           # id -> name
        self.max_people = DEFAULT_ROOM_PEOPLE
        self.joined = False       # guests: true once the host let us in
        self.people_open = False  # is the people list expanded?
        self.tx = {}               # files we are sending, by recipient's id (one per person)
        self.rx = None            # file we are being offered / receiving (one at a time)
        self.pages = {}           # name -> page frame (search, settings, ...)
        self._finish_anim = None  # set while a screen is sliding in
        self.found = {}           # rooms seen on the network: room id -> info
        self.found_lock = threading.Lock()
        self.search_stop = None   # Event that stops the listener while searching
        self.search_problem = ""
        self.rooms_sig = None
        self.banned_rids = set()  # rooms that told us we are banned
        self.return_to = None     # "search" when a failed join should go back to the list
        self.joining_rid = None
        self.pkg_busy = False
        self.update_busy = False
        self.req_stop = None      # stops waiting for the answer to a request
        self.req_room = None
        self.pkg_widgets = {}
        self.hide_switch = None
        self.word_filter = WordFilter()
        self.filter_on = False    # "Filter words" switch (only changes what this person sees)
        self.switches = []        # every Filter words switch, kept in step with each other
        self.text_bubbles = []    # messages that contain a swear word (they hold click spoilers)
        self.typing = {}          # id -> monotonic time their "is typing" expires
        self._typing_frame = 0    # which frame of the animated dots is showing
        self._last_typing_sent = 0.0  # monotonic time we last told the others we're typing
        self.emoji_imgs = EmojiImages(root)
        self.live_labels = []     # (label, function) for names/lines that get *'d out by the filter
        self.scrollables = {}     # widget -> the widget the mouse wheel should scroll
        self._wheel_acc = {}      # leftover fractions of a scroll step, per widget

        self.build_menu_frame()
        self.build_chat_frame()
        self.build_pages()
        self.show_menu()

        self.install_wheel()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.root.after(100, self.process_queue)
        self.root.after(TYPING_TICK_MS, self.typing_tick)

    # ---------- start screen ----------
    def build_menu_frame(self):
        self.menu_frame = tk.Frame(self.root, bg=BG)

        panel = RoundedPanel(self.menu_frame, bg=PANEL, radius=18, padx=30, pady=28)
        panel.place(relx=0.5, rely=0.46, anchor="center")
        card = panel.content

        tk.Label(card, text="IP Chat", font=("Segoe UI", 24, "bold"),
                 bg=PANEL, fg=TEXT).pack()
        tk.Label(card, text="Private, encrypted chat over your network",
                 font=FONT, bg=PANEL, fg=MUTED).pack(pady=(2, 20))

        make_button(card, "Host a room", GREEN, GREEN_HOVER, self.start_host,
                    pady=9).pack(fill="x")
        relay_link = make_button(card, "Host over the internet instead (less private)",
                                 LINE, HOVER, lambda: self.start_host(relay=True),
                                 font=FONT_SMALL, pady=6)
        relay_link.pack(fill="x", pady=(6, 0))

        # divider: ----- or join a room -----
        div = tk.Frame(card, bg=PANEL)
        div.pack(fill="x", pady=18)
        tk.Frame(div, bg=LINE, height=1).pack(side="left", fill="x", expand=True, pady=7)
        tk.Label(div, text="  or join a room  ", font=FONT_SMALL,
                 bg=PANEL, fg=MUTED).pack(side="left")
        tk.Frame(div, bg=LINE, height=1).pack(side="left", fill="x", expand=True, pady=7)

        tk.Label(card, text="Your nickname", font=FONT_SMALL, bg=PANEL,
                 fg=MUTED, anchor="w").pack(fill="x")
        self.nick_entry = make_entry(card, limit=NICK_MAX)
        self.nick_entry.pack(fill="x", ipady=6, pady=(2, 0))
        last_nick = load_settings().get("search_nickname", "")
        if last_nick:
            self.nick_entry.insert(0, last_nick)

        self.menu_error = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=RED,
                                   wraplength=280, justify="left", anchor="w")
        self.menu_error.pack(fill="x", pady=(8, 8))

        make_button(card, "Search for rooms", ACCENT, ACCENT_HOVER, self.start_search,
                    pady=9).pack(fill="x")
        self.nick_entry.bind("<Return>", lambda e: self.start_search())

        # three tiny links at the bottom: Credits • Settings • Instructions
        footer = tk.Frame(self.menu_frame, bg=BG)
        footer.place(relx=0.5, rely=1.0, anchor="s", y=-12)
        for n, (text, cmd) in enumerate((("Credits", lambda: self.show_page("credits")),
                                         ("Settings", None),
                                         ("Instructions", lambda: self.show_page("instructions")))):
            if n:
                tk.Label(footer, text="  •  ", font=FONT_SMALL, bg=BG, fg=LINE).pack(side="left")
            link = tk.Label(footer, text=text, font=FONT_SMALL, bg=BG, fg=MUTED, cursor="hand2")
            link.pack(side="left")
            if text == "Settings":
                link.bind("<Button-1>", lambda e: self.open_settings(e))
            else:
                link.bind("<Button-1>", lambda e, c=cmd: c())
            link.bind("<Enter>", lambda e, l=link: l.config(fg=TEXT))
            link.bind("<Leave>", lambda e, l=link: l.config(fg=MUTED))

    def open_settings(self, event=None):
        """Opens Settings. Holding Shift+Ctrl while clicking also reveals a hidden
        "testing" section underneath the normal settings - not meant for everyday use."""
        shift = bool(event is not None and event.state & 0x0001)
        ctrl = bool(event is not None and event.state & 0x0004)
        self.dev_unlocked = shift and ctrl
        card = getattr(self, "dev_card", None)
        if card is not None:
            if self.dev_unlocked:
                card.pack(fill="x", padx=16, pady=(16, 24))
            else:
                card.pack_forget()
        self.update_network_card()
        self.show_page("settings")

    def network_access_needed(self):
        """True only on Windows, and only until both firewall rules (the chat port and
        the LAN-discovery ports) already exist - i.e. there is still an admin prompt
        this person hasn't gotten past yet."""
        return os.name == "nt" and not (
            _firewall_rule_exists(RULE_NAME) and _firewall_rule_exists(RULE_NAME + " search"))

    def update_network_card(self):
        """Shows the "Network access" card only while it would actually do something -
        once both firewall rules exist, there is nothing left to ask Windows for."""
        card = getattr(self, "network_card", None)
        if card is None:
            return
        if self.network_access_needed():
            card.pack(fill="x", padx=16, pady=self._network_card_pady)
        else:
            card.pack_forget()

    def grant_network_access(self):
        self.network_note.config(
            text="Asking Windows for permission (look for a popup)...", fg=MUTED)
        self.root.update_idletasks()
        ok = ensure_firewall_rule(RULE_NAME + " search", "UDP",
                                  f"{DISCOVERY_PORT}-{KNOCK_PORT}")
        ok = ensure_firewall_rule() and ok
        if ok:
            self.update_network_card()
        else:
            self.network_note.config(
                text="Windows didn't grant it. You can allow IP Chat yourself in Windows "
                    "Defender Firewall, or use \"Host over the internet\" instead, which "
                    "never needs this.", fg=RED)

    def paste_details(self, ip_entry, pw_entry):
        """Pasting the text from "Copy details" fills in both boxes at once."""
        try:
            clip = self.root.clipboard_get()
        except tk.TclError:
            return None
        ip = re.search(r"\b(?:IP|Code)\s*[:=]\s*(\S+)", clip, re.I)
        pw = re.search(r"\bPassword\s*[:=]\s*(\S+)", clip, re.I)
        if not (ip and pw):
            return None                      # an ordinary paste: let Tk do it
        for box, value in ((ip_entry, ip.group(1)), (pw_entry, pw.group(1))):
            box.delete(0, "end")
            box.insert(0, value)
        pw_entry.focus_set()
        return "break"

    # ---------- chat screen ----------
    def build_chat_frame(self):
        self.chat_frame = tk.Frame(self.root, bg=BG)

        # Header: status dot + text + disconnect
        self.header = tk.Frame(self.chat_frame, bg=PANEL)
        self.header.pack(side="top", fill="x")
        self.dot = tk.Canvas(self.header, width=14, height=14, bg=PANEL, highlightthickness=0)
        self.dot.pack(side="left", padx=(14, 6), pady=14)
        self.dot_item = self.dot.create_oval(2, 2, 12, 12, fill=STATE_COLORS["wait"], outline="")
        self.status = tk.Label(self.header, text="", font=FONT_BOLD, bg=PANEL, fg=TEXT, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        make_button(self.header, "Disconnect", RED, RED_HOVER, self.disconnect,
                    padx=12, pady=4).pack(side="right", padx=12, pady=8)

        # Host info strip (only shown while hosting). The IP and the password stay
        # hidden behind a "spoiler" until the mouse is held over them.
        self.relay_banner = tk.Frame(self.chat_frame, bg="#3a2a12")
        tk.Label(self.relay_banner, text="Connected through a public internet relay: your "
                 "messages stay encrypted, but this is less private than connecting directly.",
                 font=FONT_SMALL, bg="#3a2a12", fg="#ffcf8a", wraplength=440, justify="left",
                 anchor="w").pack(fill="x", padx=14, pady=6)

        self.info_frame = tk.Frame(self.chat_frame, bg=STRIP)
        tk.Label(self.info_frame, text="Password", font=FONT, bg=STRIP,
                 fg=MUTED).pack(side="left", padx=(14, 6), pady=8)
        self.pw_val = Spoiler(self.info_frame)
        self.pw_val.pack(side="left")
        self.copy_btn = make_button(self.info_frame, "Copy details", LINE, HOVER,
                                    self.copy_details, padx=10, pady=2, font=FONT_SMALL)
        self.copy_btn.pack(side="right", padx=12, pady=8)

        # People bar: click to expand the list of everybody in the room
        self.people_bar = tk.Frame(self.chat_frame, bg=STRIP, cursor="hand2")
        self.people_lbl = tk.Label(self.people_bar, text="", font=FONT_BOLD, bg=STRIP,
                                   fg=TEXT, anchor="w", cursor="hand2")
        self.people_lbl.pack(side="left", fill="x", expand=True, padx=14, pady=7)
        for w in (self.people_bar, self.people_lbl):
            w.bind("<Button-1>", lambda e: self.toggle_people())
            w.bind("<Enter>", lambda e: (self.people_bar.config(bg=PANEL),
                                         self.people_lbl.config(bg=PANEL)))
            w.bind("<Leave>", lambda e: (self.people_bar.config(bg=STRIP),
                                         self.people_lbl.config(bg=STRIP)))

        self.people_panel = tk.Frame(self.chat_frame, bg=PANEL)
        tk.Frame(self.people_panel, bg=LINE, height=1).pack(side="bottom", fill="x")
        frow = tk.Frame(self.people_panel, bg=PANEL)
        frow.pack(side="top", fill="x")
        tk.Label(frow, text="Filter words", font=FONT, bg=PANEL, fg=TEXT).pack(
            side="left", padx=(14, 0), pady=7)
        self.add_switch(frow, PANEL).pack(side="right", padx=14)
        tk.Frame(self.people_panel, bg=LINE, height=1).pack(side="top", fill="x")
        self.ip_row = tk.Frame(self.people_panel, bg=PANEL)
        tk.Frame(self.ip_row, bg=LINE, height=1).pack(side="bottom", fill="x")
        self.ip_label = tk.Label(self.ip_row, text="IP address", font=FONT, bg=PANEL, fg=TEXT)
        self.ip_label.pack(side="left", padx=(14, 8), pady=7)
        self.ip_val = Spoiler(self.ip_row)
        self.ip_val.pack(side="left")
        tk.Label(self.ip_row, text="click to keep open", font=FONT_SMALL, bg=PANEL,
                 fg=MUTED).pack(side="right", padx=14)
        self.hide_row = tk.Frame(self.people_panel, bg=PANEL)
        tk.Frame(self.hide_row, bg=LINE, height=1).pack(side="bottom", fill="x")
        tk.Label(self.hide_row, text="Hide room", font=FONT, bg=PANEL, fg=TEXT).pack(
            side="left", padx=(14, 0), pady=7)
        self.hide_switch = Switch(self.hide_row, PANEL, on=False, command=self.set_hidden)
        self.hide_switch.pack(side="right", padx=14)
        tk.Label(self.hide_row, text="not shown in Search", font=FONT_SMALL, bg=PANEL,
                 fg=MUTED).pack(side="right")
        self.ban_row = tk.Frame(self.people_panel, bg=PANEL, cursor="hand2")
        self.ban_lbl = tk.Label(self.ban_row, text="", font=FONT_SMALL, bg=PANEL, fg=MUTED,
                                anchor="w", cursor="hand2")
        self.ban_lbl.pack(side="left", padx=14, pady=5)
        for w in (self.ban_row, self.ban_lbl):
            w.bind("<Button-1>", lambda e: self.show_bans())
            w.bind("<Enter>", lambda e: self.ban_lbl.config(fg=TEXT))
            w.bind("<Leave>", lambda e: self.ban_lbl.config(fg=MUTED))
        self.people_canvas = tk.Canvas(self.people_panel, bg=PANEL, highlightthickness=0,
                                       height=self.ROW_H, yscrollincrement=12)
        self.people_sb = tk.Scrollbar(self.people_panel, orient="vertical",
                                      command=self.people_canvas.yview)
        self.people_canvas.configure(yscrollcommand=self.people_sb.set)
        self.people_canvas.pack(side="left", fill="both", expand=True)
        self.people_inner = tk.Frame(self.people_canvas, bg=PANEL)
        self.people_win = self.people_canvas.create_window((0, 0), window=self.people_inner,
                                                           anchor="nw")
        self.people_inner.bind(
            "<Configure>",
            lambda e: self.people_canvas.configure(scrollregion=self.people_canvas.bbox("all")))
        self.people_canvas.bind(
            "<Configure>", lambda e: self.people_canvas.itemconfigure(self.people_win, width=e.width))

        # Input bar (packed before the message area so it can never be pushed out)
        bar = tk.Frame(self.chat_frame, bg=PANEL)
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=PANEL)
        inner.pack(fill="x", padx=12, pady=(10, 2))

        send = make_button(inner, "➤", ACCENT, ACCENT_HOVER, self.send_message,
                           font=("Segoe UI Symbol", 16), width=3)
        send.pack(side="right", fill="y", padx=(8, 0))
        attach = make_button(inner, "+", LINE, HOVER, self.attach_file,
                             font=("Segoe UI", 16, "bold"), width=3)
        attach.pack(side="right", fill="y", padx=(8, 0))

        box = tk.Frame(inner, bg=PANEL)
        box.pack(side="left", fill="both", expand=True)
        self.entry_sb = tk.Scrollbar(box, orient="vertical")
        self.entry_sb.pack(side="right", fill="y")
        self.entry = tk.Text(box, height=3, width=10, wrap="word", bg=INPUT, fg=TEXT,
                             insertbackground=TEXT, relief="flat", font=("Segoe UI", 11),
                             padx=10, pady=8, highlightthickness=1,
                             highlightbackground=LINE, highlightcolor=ACCENT,
                             yscrollcommand=self.entry_sb.set)
        self.entry.pack(side="left", fill="both", expand=True)
        self.entry_sb.configure(command=self.entry.yview)
        self.entry.bind("<KeyRelease>", self.convert_emoji)      # :sob: turns into 😭
        self.entry.bind("<KeyRelease>", self.on_typing, add="+")  # tell the others we're typing
        self.entry.bind("<Return>", self.send_message)           # Enter = send
        self.entry.bind("<Shift-Return>", self.insert_newline)   # Shift+Enter = new line
        self.typing_label = tk.Label(bar, text="", font=FONT_SMALL, bg=PANEL, fg=MUTED,
                                     anchor="w", justify="left")
        self.typing_label.pack(fill="x", padx=12, pady=(2, 0))
        tk.Label(bar, text="Enter = send    ·    Shift+Enter = new line    ·    + = send a file",
                 font=FONT_SMALL, bg=PANEL, fg=MUTED).pack(pady=(0, 8))

        # Message area: canvas with a frame inside, so every message can be a bubble
        area = tk.Frame(self.chat_frame, bg=BG)
        area.pack(side="top", fill="both", expand=True)
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0, yscrollincrement=12)
        self.vsb = tk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.msg_frame = tk.Frame(self.canvas, bg=BG)
        self.win_id = self.canvas.create_window((0, 0), window=self.msg_frame, anchor="nw")
        self.msg_frame.bind("<Configure>",
                            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        # everything that can scroll (and the scrollbars that belong to it)
        self.register_scroll(self.canvas)
        self.register_scroll(self.vsb, self.canvas)
        self.register_scroll(self.entry)
        self.register_scroll(self.entry_sb, self.entry)
        self.register_scroll(self.people_canvas)
        self.register_scroll(self.people_sb, self.people_canvas)

    # ---------- filter words ----------
    def add_switch(self, parent, bg):
        sw = Switch(parent, bg, on=self.filter_on, command=self.set_filter)
        self.switches.append(sw)
        return sw

    def set_filter(self, on):
        """Called when either switch is flipped: both follow, every message updates."""
        self.filter_on = bool(on)
        for sw in self.switches:
            sw.set(self.filter_on)
        for box in self.text_bubbles:
            box.opened.clear()               # turning it on blurs everything again
            self.style_spoilers(box)
        self.refresh_live()
        if self.people_open:
            self.render_people()

    def mask(self, text):
        """With Filter words on, swear words (in nicknames and so on) become ****."""
        if not self.filter_on or not text:
            return text
        out, last = [], 0
        for a, b in self.word_filter.find(text):
            out.append(text[last:a] + "*" * (b - a))
            last = b
        out.append(text[last:])
        return "".join(out)

    def live(self, label, fn):
        """Keeps label.text = fn(mask) up to date when the switch is flipped."""
        self.live_labels.append((label, fn))
        label.config(text=fn(self.mask))

    def refresh_live(self):
        alive = []
        for label, fn in self.live_labels:
            try:
                label.config(text=fn(self.mask))
            except tk.TclError:
                continue                     # that message was cleared away
            alive.append((label, fn))
        self.live_labels = alive

    def on_canvas_resize(self, event):
        self.canvas.itemconfigure(self.win_id, width=event.width)
        wrap = self.wrap_len()
        for lbl in self.bubbles:
            lbl.config(wraplength=wrap)
        for box in self.text_bubbles:
            self.fit_text(box)

    def wrap_len(self):
        return max(160, int(self.canvas.winfo_width() * 0.70))

    def scroll_to_bottom(self):
        self.root.update_idletasks()
        self.canvas.yview_moveto(1.0)

    # ---------- mouse wheel / two-finger trackpad scrolling ----------
    def register_scroll(self, widget, target=None):
        """Makes `widget` scroll `target` (itself by default) when the wheel is used over it."""
        self.scrollables[widget] = target or widget

    def install_wheel(self):
        """One handler for every scrollable thing in the app. Tk's own handlers only
        look at whole wheel 'clicks'; a trackpad sends many small steps, which they
        round down to nothing. This one adds the small steps up instead."""
        r = self.root
        events = ["<MouseWheel>"]
        if sys.platform.startswith("linux"):
            events += ["<Button-4>", "<Button-5>"]
        for cls in ("Text", "Listbox", "Scrollbar"):
            for ev in events:
                r.bind_class(cls, ev, self.on_wheel)   # replaces Tk's built-in version
        for ev in events:
            r.bind_all(ev, self.on_wheel)

    def on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = 120
        elif getattr(event, "num", None) == 5:
            delta = -120
        else:
            delta = event.delta
        if not delta:
            return "break"
        notches = delta / (3.0 if sys.platform == "darwin" else 120.0)

        # Scroll whatever is under the mouse (not whatever has keyboard focus):
        # start at that widget and walk up until something can actually scroll.
        # (Ask where the pointer really is: on some systems the wheel event is
        # delivered to the box that has keyboard focus, with unreliable coordinates.)
        w = None
        for x, y in ((self.root.winfo_pointerx(), self.root.winfo_pointery()),
                     (event.x_root, event.y_root)):
            try:
                w = self.root.winfo_containing(x, y)
            except (KeyError, tk.TclError):
                w = None
            if w is not None:
                break
        start, done = w, False
        # Anything inside the message list (bubbles, cards, buttons): scroll the messages.
        if w is not None and str(w).startswith(str(self.msg_frame)):
            self.scroll_widget(self.canvas, notches)
            return "break"
        while w is not None:
            target = self.scrollables.get(w)
            if target is None and isinstance(w, (tk.Text, tk.Listbox)):
                target = w
            if target is not None and self.scroll_widget(target, notches):
                done = True
                break
            w = w.master
        # Anywhere else in the chat window (header, input bar, empty space) the
        # wheel scrolls the messages.
        if not done and start is not None and self.chat_frame.winfo_ismapped() \
                and start.winfo_toplevel() is self.root:
            self.scroll_widget(self.canvas, notches)
        return "break"

    def scroll_widget(self, w, notches):
        """Scrolls `w` and returns True, or returns False when there is nothing to
        scroll (so the widget below it in the window gets the chance instead)."""
        try:
            first, last = w.yview()
        except tk.TclError:
            return False
        if first <= 0.0 and last >= 1.0:
            return False
        if isinstance(w, tk.Text):
            amount, unit = notches * 48, "pixels"
        elif isinstance(w, tk.Listbox):
            amount, unit = notches * 3, "units"
        else:  # canvases scroll in steps of 12 pixels (yscrollincrement)
            amount, unit = notches * 4, "units"
        acc = self._wheel_acc.get(w, 0.0) - amount
        whole = int(acc)
        self._wheel_acc[w] = acc - whole
        if whole:
            w.yview_scroll(whole, unit)
        return True

    # ---------- extra pages: search, credits, settings, packages, instructions ----------
    def new_page(self, name, title, back):
        frame = tk.Frame(self.root, bg=BG)
        head = tk.Frame(frame, bg=PANEL)
        head.pack(side="top", fill="x")
        make_button(head, "← Back", LINE, HOVER, back,
                    padx=12, pady=4).pack(side="left", padx=12, pady=8)
        tk.Label(head, text=title, font=FONT_BOLD, bg=PANEL, fg=TEXT).pack(side="left", padx=4)
        self.pages[name] = frame
        return frame

    def scroll_area(self, parent):
        """A scrolling area (mouse wheel and trackpad work). Returns the frame to fill."""
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(side="top", fill="both", expand=True)
        sb = tk.Scrollbar(wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        cv = tk.Canvas(wrap, bg=BG, highlightthickness=0, yscrollincrement=12,
                       yscrollcommand=sb.set)
        cv.pack(side="left", fill="both", expand=True)
        sb.config(command=cv.yview)
        inner = tk.Frame(cv, bg=BG)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        self.register_scroll(cv)
        self.register_scroll(sb, cv)
        return inner

    def build_pages(self):
        # --- search
        f = self.new_page("search", "Rooms on your network", self.show_menu)
        self.search_note = tk.Label(f, text="", font=FONT_SMALL, bg=BG, fg=RED, wraplength=420,
                                    justify="left", anchor="w")
        self.search_note.pack(side="top", fill="x", padx=16, pady=(8, 0))
        bottom_row = tk.Frame(f, bg=BG)
        bottom_row.pack(side="bottom", fill="x", padx=16, pady=10)
        link = make_button(bottom_row, "Join by IP address instead", LINE, HOVER,
                           self.join_by_ip, pady=9)
        link.pack(side="left", fill="x", expand=True, padx=(0, 5))
        link2 = make_button(bottom_row, "Join using a code instead (over the internet)", LINE, HOVER,
                            self.join_by_relay, pady=9)
        link2.pack(side="left", fill="x", expand=True, padx=(5, 0))
        self.rooms_inner = self.scroll_area(f)

        # --- credits
        f = self.new_page("credits", "Credits", self.show_menu)
        tk.Label(f, text="Nothing here to see yet", font=("Segoe UI", 12), bg=BG,
                 fg=MUTED).pack(pady=(30, 0))
        card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        card.pack(fill="x", padx=16, pady=(24, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text=f"Version {APP_VERSION}", font=FONT, bg=PANEL, fg=TEXT,
                 anchor="w").pack(side="left")
        self.update_btn = make_button(row, "Check for updates", ACCENT, ACCENT_HOVER,
                                      lambda: self.check_for_updates(manual=True),
                                      padx=14, pady=4)
        self.update_btn.pack(side="right")
        self.update_note = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=MUTED,
                                    anchor="w", wraplength=380, justify="left")
        self.update_note.pack(fill="x", pady=(6, 0))

        # --- settings
        f = self.new_page("settings", "Settings", self.show_menu)
        f = self.scroll_area(f)
        card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        card.pack(fill="x", padx=16, pady=(16, 0))
        tk.Label(card, text="Theme", font=FONT, bg=PANEL, fg=TEXT, anchor="w").pack(fill="x")
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        self.theme_note = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w")
        for n, (key, theme) in enumerate(THEMES.items()):
            cell = tk.Frame(row, bg=PANEL, cursor="hand2")
            cell.grid(row=n // 5, column=n % 5, padx=(0, 8), pady=(0, 6))
            sw = tk.Canvas(cell, width=70, height=46, bg=PANEL, highlightthickness=0,
                           cursor="hand2")
            sw.pack()
            chosen = key == CURRENT_THEME[0]
            sw.create_rectangle(1, 1, 69, 45, fill=theme["BG"],
                                outline=TEXT if chosen else theme["LINE"],
                                width=2 if chosen else 1)
            sw.create_rectangle(8, 8, 62, 26, fill=theme["PANEL"], outline="")
            sw.create_rectangle(8, 32, 34, 39, fill=theme["ACCENT"], outline="")
            sw.create_rectangle(38, 32, 62, 39, fill=theme["LINE"], outline="")
            name = tk.Label(cell, text=theme["name"], font=FONT_SMALL, bg=PANEL,
                            fg=TEXT if chosen else MUTED, cursor="hand2")
            name.pack(pady=(3, 0))
            for w in (cell, sw, name):
                w.bind("<Button-1>", lambda e, k=key: self.set_theme(k))
        self.theme_note.pack(fill="x", pady=(6, 0))
        card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        card.pack(fill="x", padx=16, pady=(16, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Filter words", font=FONT, bg=PANEL, fg=TEXT).pack(side="left")
        self.add_switch(row, PANEL).pack(side="right")
        tk.Label(card, text=("Blurs swear words in chat. Click a blurred word to show it."
                             if self.word_filter.available else
                             "Blurs swear words in chat. The word list is small right now: "
                             "install safetext in Packages for the big one."),
                 font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w", wraplength=380,
                 justify="left").pack(fill="x", pady=(2, 0))
        card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        card.pack(fill="x", padx=16, pady=(12, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Friends", font=FONT, bg=PANEL, fg=TEXT).pack(side="left")
        make_button(row, "Friends", ACCENT, ACCENT_HOVER, lambda: self.show_page("friends"),
                    padx=14, pady=4).pack(side="right")
        self.profile_lbl = tk.Label(card, text="", font=("Consolas", 9), bg=PANEL, fg=MUTED,
                                    anchor="w", justify="left")
        self.profile_lbl.pack(fill="x", pady=(6, 0))
        tk.Label(card, text="Only your friends see your name. Your ID is how they recognise you.",
                 font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w", wraplength=380,
                 justify="left").pack(fill="x", pady=(2, 0))
        card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        card.pack(fill="x", padx=16, pady=(12, 0))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Packages", font=FONT, bg=PANEL, fg=TEXT).pack(side="left")
        make_button(row, "Packages", ACCENT, ACCENT_HOVER, lambda: self.show_page("packages"),
                    padx=14, pady=4).pack(side="right")
        tk.Label(card, text="Extra parts of the program (colour emoji, bigger word list) "
                            "and an easy way to install them.",
                 font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w", wraplength=380,
                 justify="left").pack(fill="x", pady=(2, 0))

        if os.name == "nt":
            card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
            card.pack(fill="x", padx=16, pady=(12, 0))
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x")
            tk.Label(row, text="Pin to taskbar", font=FONT, bg=PANEL, fg=TEXT).pack(side="left")
            make_button(row, "Pin to taskbar", ACCENT, ACCENT_HOVER, self.pin_to_taskbar,
                        padx=14, pady=4).pack(side="right")
            tk.Label(card, text="Opens the IP Chat shortcut so you can drag it onto "
                                "your taskbar yourself to pin it there.",
                     font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w", wraplength=380,
                     justify="left").pack(fill="x", pady=(2, 0))

        # Network access: only shown on Windows, and only until both firewall rules exist
        # (see update_network_card, called whenever Settings is opened).
        self.network_card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        row = tk.Frame(self.network_card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Network access", font=FONT, bg=PANEL, fg=TEXT).pack(side="left")
        make_button(row, "Allow", ACCENT, ACCENT_HOVER, self.grant_network_access,
                    padx=14, pady=4).pack(side="right")
        self.network_note = tk.Label(
            self.network_card, text="Lets other people on your network find and join your "
                      "rooms. Windows will ask you to approve this once.",
            font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w", wraplength=380, justify="left")
        self.network_note.pack(fill="x", pady=(2, 0))
        self._network_card_pady = (12, 0)

        # Hidden testing option: only shown for this visit to Settings if it was opened
        # while holding Shift+Ctrl (see open_settings). Not packed here on purpose.
        self.dev_card = tk.Frame(f, bg=PANEL, padx=18, pady=14)
        row = tk.Frame(self.dev_card, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Testing: auto-friend connections to myself", font=FONT,
                 bg=PANEL, fg=TEXT, anchor="w", justify="left",
                 wraplength=260).pack(side="left")
        self.test_friend_switch = Switch(
            row, PANEL, on=load_settings().get("test_friend_self", False),
            command=lambda on: save_settings(test_friend_self=bool(on)))
        self.test_friend_switch.pack(side="right", padx=(8, 0))
        tk.Label(self.dev_card, text="For testing with two windows on this one PC: host in "
                 "one, join with 127.0.0.1 in the other, and they quietly count as friends "
                 "for that room - not saved, and never shown on the Friends page. Off by "
                 "default; this card itself only shows up when Settings is opened while "
                 "holding Shift+Ctrl.", font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w",
                 wraplength=380, justify="left").pack(fill="x", pady=(2, 0))
        row2 = tk.Frame(self.dev_card, bg=PANEL)
        row2.pack(fill="x", pady=(12, 0))
        tk.Label(row2, text="Testing: open a new client", font=FONT, bg=PANEL, fg=TEXT,
                 anchor="w", justify="left", wraplength=260).pack(side="left")
        make_button(row2, "Open", ACCENT, ACCENT_HOVER, self.open_new_client,
                    padx=14, pady=4).pack(side="right")
        tk.Label(self.dev_card, text="Starts a second, independent copy of the program (this "
                 "window keeps running) - handy for testing host/join on one PC without "
                 "digging up the file again yourself.", font=FONT_SMALL, bg=PANEL, fg=MUTED,
                 anchor="w", wraplength=380, justify="left").pack(fill="x", pady=(2, 0))

        # --- friends
        f = self.new_page("friends", "Friends", lambda: self.show_page("settings", -1))
        self.friends_inner = self.scroll_area(f)
        self.refresh_friends_page()
        self.refresh_profile()

        # --- packages
        f = self.new_page("packages", "Packages", lambda: self.show_page("settings", -1))
        self.pkg_all = make_button(f, "Install all missing", GREEN, GREEN_HOVER,
                                   self.install_missing, padx=14, pady=8)
        self.pkg_all.pack(side="top", fill="x", padx=16, pady=(14, 0))
        inner = self.scroll_area(f)
        for name, module, text, args, required in PACKAGES:
            card = tk.Frame(inner, bg=PANEL, padx=16, pady=10)
            card.pack(fill="x", padx=16, pady=(10, 0))
            top = tk.Frame(card, bg=PANEL)
            top.pack(fill="x")
            tk.Label(top, text=name, font=FONT_BOLD, bg=PANEL, fg=TEXT).pack(side="left")
            if required:
                tk.Label(top, text="  required", font=FONT_SMALL, bg=PANEL,
                         fg=MUTED).pack(side="left")
            btn = make_button(top, "Install", ACCENT, ACCENT_HOVER,
                              lambda n=name: self.install_packages([n]), padx=14, pady=3)
            btn.pack(side="right")
            status = tk.Label(top, text="", font=FONT_SMALL, bg=PANEL, fg=MUTED)
            status.pack(side="right", padx=10)
            tk.Label(card, text=text, font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w").pack(fill="x")
            self.pkg_widgets[name] = (status, btn)
        self.pkg_note = tk.Label(inner, text="", font=FONT_SMALL, bg=BG, fg=RED, wraplength=400,
                                 justify="left", anchor="w")
        self.pkg_note.pack(fill="x", padx=16, pady=10)

        self.build_instructions()

    # ---------- identity ----------
    def boot_identity(self):
        """Loads (or makes) ID.json. Call once, right after the window is up."""
        self.friend_store = FriendStore(self.data_dir)
        self.friends = self.friend_store.data
        ident, tampered = IdentityStore(self.data_dir).boot(self.ask_real_name, self.show_tamper_notice)
        self.identity = ident
        self.refresh_profile()
        if ident is None:                       # no name given: the program can't be used
            self.quit()
        return ident

    def startup(self):
        self.boot_identity()
        if self.identity is not None:
            self.root.after(300, self.offer_packages)
            if not load_settings().get("shown_instructions", False):
                # the very first time IP Chat is opened on this computer: land on the
                # instructions page instead of the main menu, once - settings.json
                # remembers it happened so this never fires again after today.
                self.show_page("instructions")
                save_settings(shown_instructions=True)
        self.tick_update_counter()

    def tick_update_counter(self):
        """The quiet update check only actually runs every UPDATE_CHECK_EVERY launches -
        this counts that down (in settings.json) and fires the check once it hits 0,
        then resets it. update_download_worker sets a higher count after a real update,
        so the very next launch doesn't immediately go checking again."""
        settings = load_settings()
        counter = settings.get("update_check_counter")
        if not isinstance(counter, int):
            counter = UPDATE_CHECK_EVERY
        counter -= 1
        if counter <= 0:
            self.root.after(1500, lambda: self.check_for_updates(manual=False))
            counter = UPDATE_CHECK_EVERY
        save_settings(update_check_counter=counter)

    def offer_packages(self):
        """At launch: if optional packages are missing, say what they do and offer them."""
        if load_settings().get("skip_package_offer"):
            return
        missing = [(n, t) for n, m, t, a, r in PACKAGES if not r and not package_installed(m)]
        if not missing or self.pkg_busy:
            return
        dlg, card = self.make_dialog("Extra packages", "Extra packages",
                                     "These are optional, IP Chat works without them, but "
                                     "they add more features:")
        for name, info in missing:
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=name, font=FONT_BOLD, bg=PANEL, fg=TEXT, anchor="w").pack(fill="x")
            tk.Label(row, text=info, font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w",
                     wraplength=300, justify="left").pack(fill="x")
        result = {"go": False}

        def install(event=None):
            result["go"] = True
            dlg.destroy()

        def never():
            save_settings(skip_package_offer=True)
            dlg.destroy()
        later = make_button(card, "Not now", LINE, HOVER, dlg.destroy, padx=14, pady=8)
        make_button(card, "Install", GREEN, GREEN_HOVER, install, padx=14, pady=8).pack(
            fill="x", pady=(12, 0))
        later.pack(fill="x", pady=(8, 0))
        make_button(card, "Don't ask again", LINE, HOVER, never, padx=14, pady=4,
                    font=FONT_SMALL).pack(fill="x", pady=(8, 0))
        self.run_dialog(dlg, later)
        if result["go"]:
            self.show_page("packages")
            self.install_missing()

    def show_tamper_notice(self):
        dlg, card = self.make_dialog("IP Chat", "Careful", TAMPER_MESSAGE)
        ok = make_button(card, "OK", ACCENT, ACCENT_HOVER, dlg.destroy, padx=14, pady=8)
        ok.pack(fill="x")
        self.run_dialog(dlg, ok)

    def ask_real_name(self):
        """First start: asks for the name only your friends will see."""
        dlg, card = self.make_dialog(
            "Welcome", "Your friend name",
            "This is a name only IPFriends will see, NOT a nickname, choose this carefully.")
        entry = make_entry(card, limit=FRIEND_NAME_MAX)
        entry.pack(fill="x", ipady=6, pady=(0, 6))
        error = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=RED, anchor="w")
        error.pack(fill="x", pady=(0, 6))
        result = {"name": None}

        def ok(event=None):
            name = clean_nickname(entry.get())[:FRIEND_NAME_MAX]
            if not name:
                error.config(text="Please enter a name.")
                return
            result["name"] = name
            dlg.destroy()
        make_button(card, "Continue", ACCENT, ACCENT_HOVER, ok, padx=14, pady=8).pack(fill="x")
        entry.bind("<Return>", ok)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)      # it has to be filled in
        self.run_dialog(dlg, entry, closable=False)
        return result["name"]

    # ---------- themes ----------
    def set_theme(self, key):
        if key == CURRENT_THEME[0]:
            return
        if self.pkg_busy:
            self.theme_note.config(text="Wait until the install is finished.", fg=RED)
            return
        saved = save_settings(theme=key)
        apply_theme(key)
        self.rebuild_ui("settings")
        if not saved:
            self.theme_note.config(
                text="The theme could not be saved, so it will reset after a restart.", fg=RED)

    def rebuild_ui(self, show):
        """Builds every screen again in the new colours (only done on the start screens)."""
        if self._finish_anim:
            self._finish_anim()
        self.stop_search()
        nickname = self.nick_entry.get()
        for frame in self.all_frames():
            frame.destroy()
        self.pages, self.switches, self.scrollables, self._wheel_acc = {}, [], {}, {}
        self.pkg_widgets, self.live_labels = {}, []
        self.text_bubbles, self.bubbles = [], []
        self.rooms_sig = None
        self.root.configure(bg=BG)
        self.build_menu_frame()
        self.build_chat_frame()
        self.build_pages()
        self.nick_entry.delete(0, "end")
        self.nick_entry.insert(0, nickname)
        self.pages[show].pack(fill="both", expand=True)
        self.root.update_idletasks()

    # ---------- packages ----------
    def refresh_packages(self):
        missing = 0
        for name, module, text, args, required in PACKAGES:
            status, btn = self.pkg_widgets[name]
            if self.pkg_busy and status.cget("text") == "Installing...":
                continue
            if package_installed(module):
                status.config(text="Installed ✓", fg=STATE_COLORS["ok"])
                btn.pack_forget()
            else:
                missing += 1
                status.config(text="Not installed", fg=MUTED)
                if not btn.winfo_ismapped():
                    btn.pack(side="right", before=status)
                btn.config(state="disabled" if self.pkg_busy else "normal")
        self.pkg_all.config(state="disabled" if (self.pkg_busy or not missing) else "normal",
                            text="Install all missing" if missing else "Everything is installed")

    def install_missing(self):
        self.install_packages([n for n, m, t, a, r in PACKAGES if not package_installed(m)])

    def install_packages(self, names):
        if self.pkg_busy or not names:
            return
        self.pkg_busy = True
        self.pkg_results = []
        self.pkg_note.config(text="")
        for n in names:
            self.pkg_widgets[n][0].config(text="Installing...", fg=STATE_COLORS["wait"])
        self.refresh_packages()
        threading.Thread(target=self.pip_worker, args=(list(names),), daemon=True).start()

    def pip_worker(self, names):
        for i, name in enumerate(names):
            args = next(a for n, m, t, a, r in PACKAGES if n == name)
            ok, error = run_pip(args)
            self.incoming.put((0, "pkg", (name, ok, error, i == len(names) - 1)))

    def on_package_done(self, name, ok, error, last):
        self.pkg_results.append((name, ok, error))
        status = self.pkg_widgets[name][0]
        status.config(text="Installed ✓" if ok else "Failed",
                      fg=STATE_COLORS["ok"] if ok else RED)
        if not last:
            return
        self.pkg_busy = False
        self.refresh_packages()
        failed = [(n, e) for n, o, e in self.pkg_results if not o]
        if failed:
            self.pkg_note.config(text="Could not install: " + "; ".join(
                f"{n} ({e[-160:] or 'unknown error'})" for n, e in failed))
        if any(o for n, o, e in self.pkg_results):
            if self.ask_restart():
                self.restart_program()

    def ask_restart(self):
        dlg, card = self.make_dialog("Installed", "Installed ✓",
                                     "Packages will activate after restarting this program.")
        result = {"restart": False}

        def go(event=None):
            result["restart"] = True
            dlg.destroy()
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x")
        later = make_button(buttons, "Not yet", LINE, HOVER, dlg.destroy, padx=14, pady=8)
        later.pack(side="left")
        make_button(buttons, "Restart", GREEN, GREEN_HOVER, go, padx=14, pady=8).pack(side="right")
        self.run_dialog(dlg, later)
        return result["restart"]

    def restart_program(self):
        script = os.path.abspath(sys.argv[0])
        # drop any testing-only flags this process happened to be carrying (an
        # alternate half, permission to run alongside another copy) - a restart goes
        # back to being an ordinary single main instance. ARG_RELAUNCH tells the new
        # process to take the single-instance lock over from this one without
        # checking whether this one is still technically alive - it's about to quit
        # on purpose, right below, so it would otherwise lose that race to itself.
        passthrough = [a for a in sys.argv[1:]
                       if a not in (ARG_RELAUNCH, ARG_ALLOW_MULTIPLE)
                       and not a.startswith(ARG_HALF_PREFIX)]
        try:
            subprocess.Popen([sys.executable, script, ARG_RELAUNCH] + passthrough,
                             cwd=os.path.dirname(script) or None)
        except OSError as e:
            messagebox.showerror("Restart", f"Could not restart the program:\n{e}\n\n"
                                            "Close it and open it again yourself.")
            return
        self.quit()

    def open_new_client(self):
        """Testing only: starts a second, completely independent copy of the program,
        and puts this window and the new one side by side - this one on the left
        half of the screen, the new one on the right - so you can see both at once.
        This window's connection, if any, is left exactly as it is. The new copy is
        launched with ARG_ALLOW_MULTIPLE, the one deliberate exception to IP Chat
        otherwise refusing to run two ordinary copies at once (see __main__)."""
        script = os.path.abspath(sys.argv[0])
        exe = sys.executable
        if os.name == "nt" and script.lower().endswith(".pyw"):
            pyw_exe = os.path.join(os.path.dirname(sys.executable) or "", "pythonw.exe")
            if os.path.exists(pyw_exe):
                exe = pyw_exe
        try:
            subprocess.Popen([exe, script, ARG_ALLOW_MULTIPLE, ARG_HALF_PREFIX + "right"],
                             cwd=os.path.dirname(script) or None)
        except OSError as e:
            messagebox.showerror("Open a new client", f"Could not start another copy:\n{e}")
            return
        place_half_screen(self.root, "left")

    def pin_to_taskbar(self):
        if os.name != "nt":
            messagebox.showinfo("Pin to taskbar", "This only works on Windows.")
            return
        lnk_path = os.path.join(appdata_dir(), "IP Chat.lnk")
        if not os.path.exists(lnk_path):
            try:
                lnk_path = create_shortcut(os.path.abspath(sys.argv[0]),
                    icon_path() if os.path.exists(icon_path()) else None)
            except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
                messagebox.showerror("Pin to taskbar", f"Could not create the shortcut:\n{e}")
                return
        reveal_in_folder(lnk_path)
        messagebox.showinfo("Pin to taskbar",
            'A folder has opened with the "IP Chat" shortcut selected.\n\n'
            "Drag that shortcut onto your taskbar to pin it there.")

    # ---------- checking for a newer version ----------
    def check_for_updates(self, manual=False):
        """manual=True is the "Check for updates" button (always reports back, even if
        already up to date); manual=False is the quiet check at startup (only speaks up
        if there actually is something new)."""
        if self.update_busy:
            return
        self.update_busy = True
        if manual:
            self.update_btn.config(state="disabled")
            self.update_note.config(text="Checking for updates...")
        threading.Thread(target=self.update_check_worker, args=(manual,), daemon=True).start()

    def update_check_worker(self, manual):
        try:
            release = fetch_latest_release()
            self.incoming.put((0, "update", ("checked", release, None, manual)))
        except (urllib.error.URLError, ValueError, OSError, TimeoutError,
                json.JSONDecodeError, UnicodeDecodeError) as e:
            self.incoming.put((0, "update", ("checked", None, str(e), manual)))

    def on_update_event(self, stage, data, error, manual):
        if stage == "checked":
            self.update_busy = False
            if manual:
                self.update_btn.config(state="normal")
            if error:
                if manual:
                    self.update_note.config(text=f"Could not check for updates: {error}")
                return
            latest = str(data.get("version", ""))
            latest_v, current_v = parse_version(latest), parse_version(APP_VERSION)
            if latest_v > current_v:
                self.update_note.config(
                    text=f"Version {latest} is available (you have {APP_VERSION}).")
                self.offer_update(data, downgrade=False)
            elif latest_v < current_v:
                self.update_note.config(
                    text=f"The repo's newest build is {latest} (older than your {APP_VERSION}).")
                self.offer_update(data, downgrade=True)
            elif manual:
                self.update_note.config(text=f"You're up to date (version {APP_VERSION}).")
        elif stage == "downloaded":
            self.update_busy = False
            self.update_btn.config(state="normal")
            if error:
                self.update_note.config(text=f"Could not install the update: {error}")
                return
            latest = data
            save_settings(update_check_counter=UPDATE_CHECK_AFTER_UPDATE)
            self.update_note.config(text=f"Switched to version {latest}. Restarting...")
            self.root.after(1200, self.restart_program)

    def offer_update(self, manifest, downgrade=False):
        latest = str(manifest.get("version", ""))
        notes = clean_text(str(manifest.get("notes", "")), 500)
        if downgrade:
            title, heading, button_text = ("Different version available",
                f"Switch to version {latest}?", "Switch now")
        else:
            title, heading, button_text = ("Update available",
                f"Version {latest} is available", "Update now")
        dlg, card = self.make_dialog(title, heading,
            notes or f"You currently have version {APP_VERSION}.")
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x")

        def go(event=None):
            dlg.destroy()
            self.start_update_download(manifest)
        later = make_button(buttons, "Not now", LINE, HOVER, dlg.destroy, padx=14, pady=8)
        later.pack(side="left")
        make_button(buttons, button_text, GREEN, GREEN_HOVER, go, padx=14, pady=8).pack(
            side="right")
        self.run_dialog(dlg, later)

    def start_update_download(self, manifest):
        self.update_busy = True
        self.update_btn.config(state="disabled")
        self.update_note.config(text="Downloading update...")
        threading.Thread(target=self.update_download_worker, args=(manifest,),
                         daemon=True).start()

    def update_download_worker(self, manifest):
        """Downloads the new script, makes sure it matches the hash GitHub's own API
        said this file should have (no manual checksum to maintain) and is at least
        valid Python, before touching anything - then swaps it in. The running program
        already has the old code loaded in memory, so replacing the file on disk is
        safe even while it's still open - restart_program() is what actually picks the
        new copy up."""
        try:
            url = manifest["url"]
            req = urllib.request.Request(url, headers={"User-Agent": "IPChat"})
            with urllib.request.urlopen(req, timeout=UPDATE_DOWNLOAD_TIMEOUT) as resp:
                content = resp.read(50 * 1024 * 1024)   # a script this size is already absurd

            expected_sha = manifest.get("git_sha")
            if expected_sha and git_blob_sha1(content) != str(expected_sha).strip().lower():
                raise ValueError("the download didn't match what GitHub said this file should be")

            compile(content, "ip-chat-update.py", "exec")   # reject a broken/truncated download

            script = os.path.abspath(sys.argv[0])
            tmp_path = script + ".new"
            with open(tmp_path, "wb") as f:
                f.write(content)
            os.replace(tmp_path, script)   # atomic - either the swap fully happens or it doesn't
            self.incoming.put((0, "update", ("downloaded", manifest.get("version"), None, True)))
        except (urllib.error.URLError, ValueError, OSError, SyntaxError, TimeoutError) as e:
            self.incoming.put((0, "update", ("downloaded", None, str(e), True)))

    # ---------- a popup with one or more boxes ----------
    def ask_fields(self, title, heading, subtitle, fields, ok_text, ok_color=None,
                   ok_hover=None, paste=False, validate=None):
        """fields: [(label, show, limit)]. Returns the typed values, or None on cancel."""
        dlg, card = self.make_dialog(title, heading, subtitle)
        entries = []
        for label, show, limit in fields:
            tk.Label(card, text=label, font=FONT_SMALL, bg=PANEL, fg=MUTED,
                     anchor="w").pack(fill="x")
            e = make_entry(card, show=show, limit=limit)
            e.pack(fill="x", ipady=6, pady=(2, 10))
            entries.append(e)
        error = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=RED, anchor="w",
                         wraplength=300, justify="left")
        error.pack(fill="x", pady=(0, 6))
        result = {"values": None}

        def ok(event=None):
            values = [e.get().strip() for e in entries]
            problem = validate(values) if validate else None
            if problem:
                error.config(text=problem)
                return
            result["values"] = values
            dlg.destroy()
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x")
        make_button(buttons, "Cancel", LINE, HOVER, dlg.destroy,
                    padx=14, pady=8).pack(side="left")
        make_button(buttons, ok_text, ok_color or ACCENT, ok_hover or ACCENT_HOVER, ok,
                    padx=14, pady=8).pack(side="right")
        for n, e in enumerate(entries):
            e.bind("<Return>", ok if n == len(entries) - 1 else
                   (lambda ev, nxt=entries[n + 1]: nxt.focus_set()))
        if paste and len(entries) >= 2:
            for e in entries[:2]:
                e.bind("<<Paste>>", lambda ev: self.paste_details(entries[0], entries[1]))
        self.run_dialog(dlg, entries[0])
        return result["values"]

    # ---------- instructions, with little pictures ----------
    ARROW = "#f59e0b"

    def build_instructions(self):
        f = self.new_page("instructions", "Instructions", self.show_menu)
        inner = self.scroll_area(f)

        def section(title, text, draw, height):
            box = tk.Frame(inner, bg=PANEL, padx=16, pady=14)
            box.pack(fill="x", padx=16, pady=(14, 0))
            tk.Label(box, text=title, font=("Segoe UI", 12, "bold"), bg=PANEL,
                     fg=TEXT, anchor="w").pack(fill="x")
            cv = tk.Canvas(box, width=380, height=height, bg=BG, highlightthickness=0)
            cv.pack(pady=10)
            draw(cv)
            tk.Label(box, text=text, font=FONT, bg=PANEL, fg=MUTED, anchor="w",
                     wraplength=380, justify="left").pack(fill="x")

        def button(cv, x, y, w, h, text, color):
            cv.create_rectangle(x, y, x + w, y + h, fill=color, outline="")
            cv.create_text(x + w / 2, y + h / 2, text=text, fill=on_color(color), font=FONT_BOLD)

        def entry(cv, x, y, w, h, text):
            cv.create_rectangle(x, y, x + w, y + h, fill=INPUT, outline=LINE)
            cv.create_text(x + 8, y + h / 2, text=text, fill=TEXT, font=FONT, anchor="w")

        def card(cv, x, y, w, h):
            cv.create_rectangle(x, y, x + w, y + h, fill=PANEL, outline="")

        def switch(cv, x, y, on):
            cv.create_line(x + 11, y + 11, x + 31, y + 11, width=21, capstyle="round", fill="white")
            cv.create_line(x + 11, y + 11, x + 31, y + 11, width=17, capstyle="round",
                           fill=GREEN if on else RED)
            cx = x + (31 if on else 11)
            cv.create_oval(cx - 6, y + 5, cx + 6, y + 17, fill="white", outline="")

        def arrow(cv, x1, y1, x2, y2, text, tx, ty, anchor="w"):
            cv.create_line(x1, y1, x2, y2, arrow="last", width=3, fill=self.ARROW,
                           arrowshape=(10, 12, 5))
            cv.create_text(tx, ty, text=text, fill=self.ARROW, font=FONT_BOLD, anchor=anchor)

        def draw_host(cv):
            card(cv, 10, 10, 190, 100)
            cv.create_text(105, 30, text="IP Chat", fill=TEXT, font=("Segoe UI", 12, "bold"))
            button(cv, 24, 55, 162, 32, "Host a room", GREEN)
            arrow(cv, 250, 71, 192, 71, "Start here", 258, 71)

        def draw_search(cv):
            card(cv, 10, 8, 190, 124)
            cv.create_text(24, 24, text="Your nickname", fill=MUTED, font=FONT_SMALL, anchor="w")
            entry(cv, 24, 34, 162, 26, "Bob")
            button(cv, 24, 82, 162, 32, "Search for rooms", ACCENT)
            arrow(cv, 250, 46, 192, 47, "1. Nickname first", 258, 46)
            arrow(cv, 250, 98, 192, 98, "2. Search", 258, 98)

        def draw_rooms(cv):
            card(cv, 10, 8, 250, 104)
            cv.create_text(24, 28, text="Alice's room", fill=TEXT,
                           font=("Segoe UI", 12, "bold"), anchor="w")
            cv.create_text(24, 48, text="1 of 4 people", fill=MUTED, font=FONT_SMALL, anchor="w")
            button(cv, 24, 66, 60, 30, "Join", GREEN)
            button(cv, 92, 66, 130, 30, "Request to join", ACCENT)
            arrow(cv, 54, 142, 54, 102, "Know the password?", 24, 154, "w")
            arrow(cv, 250, 142, 200, 102, "No password?\nAsk the host", 236, 156, "w")

        def draw_room(cv):
            card(cv, 10, 6, 210, 138)
            cv.create_text(24, 24, text="Filter words", fill=TEXT, font=FONT, anchor="w")
            switch(cv, 168, 13, True)
            cv.create_line(10, 38, 220, 38, fill=LINE)
            cv.create_text(24, 54, text="Hide room", fill=TEXT, font=FONT, anchor="w")
            switch(cv, 168, 43, False)
            cv.create_line(10, 68, 220, 68, fill=LINE)
            cv.create_text(24, 90, text="Bob", fill=TEXT, font=FONT, anchor="w")
            button(cv, 126, 78, 40, 22, "Kick", LINE)
            button(cv, 170, 78, 38, 22, "Ban", RED)
            cv.create_text(24, 122, text="Banned: 1  \u00b7  click to manage", fill=MUTED,
                           font=FONT_SMALL, anchor="w")
            arrow(cv, 262, 26, 214, 26, "Blur words", 268, 26, "w")
            arrow(cv, 262, 56, 214, 56, "Not in Search", 268, 56, "w")
            arrow(cv, 262, 100, 214, 92, "Kick = remove\nBan = block", 268, 112, "w")

        def draw_chat(cv):
            card(cv, 10, 20, 340, 56)
            cv.create_rectangle(20, 30, 250, 66, fill=INPUT, outline=LINE)
            cv.create_text(30, 48, text="hello :sob:  →  \U0001F62D", fill=TEXT, font=FONT, anchor="w")
            button(cv, 258, 30, 40, 36, "+", LINE)
            button(cv, 304, 30, 38, 36, "➤", ACCENT)
            arrow(cv, 278, 126, 278, 72, "+ sends a file (max 500 MB)", 160, 132, "w")
            arrow(cv, 120, 100, 120, 72, "Enter sends, Shift+Enter = new line", 20, 108, "w")

        section("1. Host a room",
                "Click Host a room, choose your nickname and how many people may join "
                "(2 to 100). The room gets a random password: hover over it in the top bar to "
                "see it, then tell your friends. You can also hide the room in the People tab.",
                draw_host, 120)
        section("2. Find a room",
                "Type a nickname, then click Search for rooms. Rooms on the same Wi-Fi or "
                "network as you show up by themselves. Nobody has to share an IP address.",
                draw_search, 140)
        section("3. Join it",
                "Join asks for the room password. No password? Request to join sends the host "
                "a short message, and they can send you the password. A room you are banned "
                "from is greyed out.",
                draw_rooms, 180)
        section("4. In the room",
                "Open the People tab. The host can Kick (the person may come back) or Ban "
                "(they can never join again until unbanned). Filter words hides swear words "
                "on your screen only; click a hidden word to show it.",
                draw_room, 150)
        section("5. Chatting and files",
                "Type and press Enter. Typing a shortcode like :sob: gives an emoji. "
                "Use + to send a file to one person.",
                draw_chat, 140)
        tk.Label(inner, text="Trouble? No rooms found: check that you are on the same Wi-Fi "
                             "and allow the program in the Windows firewall. School and public "
                             "networks often block this.",
                 font=FONT_SMALL, bg=BG, fg=MUTED, wraplength=380, justify="left").pack(
            padx=16, pady=14, anchor="w")

    # ---------- screens ----------
    ANIMATE = True                 # slide between screens

    def all_frames(self):
        return [self.menu_frame, self.chat_frame, *self.pages.values()]

    def hide_all(self):
        self.stop_search()
        if self._finish_anim:
            self._finish_anim()
        for frame in self.all_frames():
            frame.pack_forget()

    def switch_to(self, frame, direction=1):
        """Shows `frame`. When another screen is showing, the new one slides in
        (direction 1: from the right, -1: from the left)."""
        self.stop_search()
        if self._finish_anim:
            self._finish_anim()
        old = [f for f in self.all_frames() if f is not frame and f.winfo_manager()]
        if not old or not self.ANIMATE or not self.root.winfo_viewable():
            for f in self.all_frames():
                f.pack_forget()
            frame.pack(fill="both", expand=True)
            return
        prev = old[0]
        for extra in old[1:]:
            extra.pack_forget()
        frame.pack_forget()
        prev.pack_forget()
        prev.place(in_=self.root, relx=0, rely=0, relwidth=1, relheight=1)
        frame.place(in_=self.root, relx=direction, rely=0, relwidth=1, relheight=1)
        frame.lift()

        def finish():
            self._finish_anim = None
            prev.place_forget()
            frame.place_forget()
            frame.pack(fill="both", expand=True)

        steps = 9

        def step(i):
            if self._finish_anim is not finish:
                return
            if i > steps:
                finish()
                return
            ease = 1 - (1 - i / steps) ** 3
            frame.place_configure(relx=direction * (1 - ease))
            prev.place_configure(relx=-direction * 0.25 * ease)
            self.root.after(14, step, i + 1)
        self._finish_anim = finish
        step(1)

    def show_menu(self):
        self.switch_to(self.menu_frame, -1)
        self.menu_error.config(text="")
        self.nick_entry.focus_set()

    def show_page(self, name, direction=1):
        self.switch_to(self.pages[name], direction)
        if name == "packages":
            self.refresh_packages()
        if name == "friends":
            self.refresh_friends_page()

    def show_chat(self, status_text, state="wait", host_info=None, relay=False,
                  row_label="IP address", copy_label="IP"):
        self.switch_to(self.chat_frame, 1)
        self.set_status(status_text, state)

        self.info_frame.pack_forget()
        self.relay_banner.pack_forget()
        self.people_bar.pack_forget()
        self.people_panel.pack_forget()
        self.people_open = False
        anchor = self.header
        if relay:
            self.relay_banner.pack(side="top", fill="x", after=anchor)
            anchor = self.relay_banner
        if host_info:
            ip, password = host_info
            self.host_details = f"{copy_label}: {ip}\nPassword: {password}"
            self.ip_label.config(text=row_label)
            self.ip_val.set(ip)
            self.pw_val.set(password)
            self.copy_btn.config(text="Copy details")
            self.info_frame.pack(side="top", fill="x", after=anchor)
            anchor = self.info_frame
        self.people_bar.pack(side="top", fill="x", after=anchor)
        self.set_people([], self.max_people)
        self.hide_row.pack_forget()
        self.ip_row.pack_forget()
        if host_info:                                   # only the host sees these rows
            self.hide_switch.set(False)
            self.ip_row.pack(side="top", fill="x", before=self.people_canvas)
            self.hide_row.pack(side="top", fill="x", before=self.people_canvas)

        for child in self.msg_frame.winfo_children():
            child.destroy()
        self.bubbles = []
        self.text_bubbles = []
        self.live_labels = []
        self.entry.delete("1.0", "end")
        self.root.update_idletasks()
        self.entry.focus_set()

    def set_status(self, text, state):
        self.status.config(text=text)
        self.dot.itemconfigure(self.dot_item, fill=STATE_COLORS.get(state, MUTED))

    def copy_details(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.host_details)
        self.copy_btn.config(text="Copied ✓")
        self.root.after(1500, lambda: self.copy_btn.config(text="Copy details"))

    # ---------- the people list ----------
    def toggle_people(self):
        self.people_open = not self.people_open
        if self.people_open:
            self.people_panel.pack(side="top", fill="x", after=self.people_bar)
        else:
            self.people_panel.pack_forget()
        self.update_people_ui()

    def set_people(self, people, max_people):
        self.people = people
        self.names = {pid: name for pid, name in people}
        self.max_people = max_people
        self.update_people_ui()

    def update_people_ui(self):
        arrow = "▴" if self.people_open else "▾"
        if self.people:
            self.people_lbl.config(
                text=f"People  {len(self.people)}/{self.max_people}      {arrow}")
        else:
            self.people_lbl.config(text=f"People      {arrow}")
        self.update_ban_row()
        if self.people_open:
            self.render_people()

    def update_ban_row(self):
        room = self.room
        count = (len(room.banned) + len(room.banned_uids)) if (self.is_host and room is not None) else 0
        if count:
            self.ban_lbl.config(text=f"Banned: {count}   ·   click to manage")
            if not self.ban_row.winfo_ismapped():
                self.ban_row.pack(side="bottom", fill="x", before=self.people_canvas)
        else:
            self.ban_row.pack_forget()

    def render_people(self):
        for child in self.people_inner.winfo_children():
            child.destroy()
        self.friend_sweep()
        for pid, name in self.people:
            row = tk.Frame(self.people_inner, bg=PANEL)
            row.pack(fill="x")
            you = pid == self.my_id
            dot = tk.Label(row, text="●", font=("Segoe UI", 8), bg=PANEL,
                           fg=STATE_COLORS["ok"])
            dot.pack(side="left", padx=(14, 8), pady=5)
            shown = tk.Label(row, text=self.mask(self.label_of(pid)),
                             font=FONT_BOLD if you else FONT, bg=PANEL, fg=TEXT, anchor="w")
            shown.pack(side="left")
            tags = [t for t, on in (("host", pid == HOST_ID), ("you", you)) if on]
            tag_lbl = None
            if tags:
                tag_lbl = tk.Label(row, text=" · ".join(tags), font=FONT_SMALL, bg=PANEL, fg=MUTED)
                tag_lbl.pack(side="right", padx=14)
            if self.is_host and pid != HOST_ID:
                make_button(row, "Ban", RED, RED_HOVER,
                            lambda p=pid, n=name: self.ask_ban(p, n),
                            padx=8, pady=0, font=FONT_SMALL).pack(side="right", padx=(4, 14))
                make_button(row, "Kick", LINE, HOVER,
                            lambda p=pid: self.kick_person(p),
                            padx=8, pady=0, font=FONT_SMALL).pack(side="right", padx=(4, 0))
            if not you:                                   # click a person to see more / add them
                for w in (row, dot, shown, tag_lbl):
                    if w is not None:
                        w.bind("<Button-1>", lambda e, p=pid: self.toggle_person(p))
                        w.config(cursor="hand2")
                if self.open_person == pid:
                    self.person_details(self.people_inner, pid)
        self.root.update_idletasks()
        wanted = self.people_inner.winfo_reqheight()
        self.people_canvas.config(height=max(self.ROW_H, min(wanted, self.PEOPLE_MAX_H)),
                                  scrollregion=(0, 0, 1, wanted))
        if wanted <= self.PEOPLE_MAX_H:
            self.people_canvas.yview_moveto(0)   # everything fits: start from the top
        if wanted > self.PEOPLE_MAX_H:
            self.people_sb.pack(side="right", fill="y", before=self.people_canvas)
        else:
            self.people_sb.pack_forget()

    def name_of(self, pid):
        return self.mask(self.names.get(pid, "Someone"))

    # ---------- friends ----------
    def friend_of(self, pid):
        """The saved friend behind this person, if they really are that friend (a same-PC
        test-friend from self.test_friends counts here too, just never on the Friends page)."""
        ident = self.peer_ids.get(pid)
        if not ident:
            return None
        f = self.friends.get(ident[0]) or self.test_friends.get(ident[0])
        return f if f and f.get("pk") == ident[1] else None

    def all_friends(self):
        """Real friends plus same-PC test-friends, for anything that should treat both the
        same (relay search beacons) - but never for the Friends page itself."""
        merged = dict(self.test_friends)
        merged.update(self.friends)
        return merged

    def is_test_peer(self, pid):
        """True only when: the hidden same-PC testing switch is on, AND this particular
        connection is to/from 127.0.0.1 - i.e. almost certainly you, testing with a second
        window on this machine. Used only to decide whether a friend exchange with them
        becomes a real, saved friend or an in-memory test-friend."""
        if not load_settings().get("test_friend_self", False):
            return False
        if self.is_host:
            return pid in self._loopback_peers
        return pid == HOST_ID and self._joined_via_loopback

    def label_of(self, pid):
        """'bootybandit (Samantha)' for friends, just the nickname for everybody else."""
        name = self.names.get(pid, "Someone")
        f = self.friend_of(pid)
        return f"{name} ({f['name']})" if f else name

    def label_for_nick(self, nick):
        pid = next((p for p, n in self.names.items() if n == nick), None)
        return self.label_of(pid) if pid is not None else nick

    def send_friend(self, pid, body):
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        try:
            if self.is_host:
                member = self.room.get(pid) if self.room else None
                if member is None:
                    return False
                member.chan.send(K_FRIEND, struct.pack(">H", HOST_ID) + data)
            else:
                if self.channel is None or not self.joined:
                    return False
                self.channel.send(K_FRIEND, struct.pack(">H", pid) + data)
            return True
        except OSError:
            return False

    def friend_sweep(self):
        now = time.monotonic()
        for table in (self.friend_out, self.friend_in, self.friend_wait):
            for pid in [k for k, v in table.items() if now - v["time"] > FRIEND_TIMEOUT]:
                del table[pid]

    def friend_request(self, pid):
        ident = self.peer_ids.get(pid)
        if not (self.identity and ident) or pid in self.friend_out or self.friend_of(pid):
            return False
        ok = self._send_friend_req(pid, ident)
        if ok:
            self.add_line(f"Friend request sent to {self.names.get(pid, 'them')}.")
            self.update_people_ui()
        return ok

    def refresh_friend_key(self, pid):
        """A friend made before internet-relay search existed has no static key saved for
        them yet. Quietly re-run the friend handshake so both sides pick one up - it answers
        on its own (friend_accept's "already friends: refresh quietly" case)."""
        ident = self.peer_ids.get(pid)
        if self.identity and ident and pid not in self.friend_out:
            self._send_friend_req(pid, ident)

    def try_auto_test_friend(self, pid):
        """Same-PC testing: silently become friends with yourself over a loopback
        connection, so you can test friends-only features without a second real person."""
        ident = self.peer_ids.get(pid)
        if self.identity and ident and pid not in self.friend_out:
            self._send_friend_req(pid, ident, test=True)

    def _send_friend_req(self, pid, ident, test=False):
        eph = X25519PrivateKey.generate()
        eph_pub = raw_public(eph)
        sig = self.identity.sign(b"fr-req|" + ident[0].encode("utf-8") + eph_pub +
                                 self.identity.x_pub)
        ok = self.send_friend(pid, {"t": "req", "uid": self.identity.uid,
                                    "pk": self.identity.pub_hex, "eph": eph_pub.hex(),
                                    "xpk": self.identity.x_pub_hex, "sig": sig.hex()})
        if ok:
            self.friend_out[pid] = {"uid": ident[0], "pk": ident[1], "eph": eph,
                                    "eph_pub": eph_pub, "test": test, "time": time.monotonic()}
        return ok

    def friend_answer(self, pid, accept):
        """Accept or decline a friend request somebody sent us."""
        req = self.friend_in.pop(pid, None)
        if req is None:
            return
        if accept:
            self.friend_accept(pid, req)
        else:
            self.send_friend(pid, {"t": "no", "uid": self.identity.uid})
            self.add_line(f"You declined {self.names.get(pid, 'their')} friend request.")
        self.update_people_ui()

    def friend_accept(self, pid, req, test=False):
        a_uid, b_uid = req["uid"], self.identity.uid
        eph = X25519PrivateKey.generate()
        eph_pub = raw_public(eph)
        shared = eph.exchange(X25519PublicKey.from_public_bytes(req["eph"]))
        k_a2b, k_b2a = friend_keys(shared, req["eph"], eph_pub)
        nonce = os.urandom(12)
        sealed = ChaCha20Poly1305(k_b2a).encrypt(nonce, self.identity.name.encode("utf-8"),
                                                 (a_uid + b_uid).encode("utf-8"))
        sig = self.identity.sign(b"fr-acc|" + a_uid.encode("utf-8") + req["eph"] + eph_pub +
                                 nonce + sealed + self.identity.x_pub)
        if self.send_friend(pid, {"t": "acc", "uid": b_uid, "pk": self.identity.pub_hex,
                                  "eph": eph_pub.hex(), "n": nonce.hex(), "ct": sealed.hex(),
                                  "xpk": self.identity.x_pub_hex, "sig": sig.hex()}):
            self.friend_wait[pid] = {"uid": a_uid, "pk": req["pk"], "k_a2b": k_a2b,
                                     "a_eph": req["eph"], "b_eph": eph_pub, "xpk": req["xpk"],
                                     "test": test, "time": time.monotonic()}

    def save_friend(self, pid, uid, pk, name, xpk=None, test=False):
        name = clean_nickname(name)[:FRIEND_NAME_MAX] or "Friend"
        nick = self.names.get(pid, "")
        if test:
            # A same-PC testing shortcut, not a real friendship: kept only for this room
            # session, in memory - never written to friends.json, never shown on the
            # Friends page.
            already = uid in self.test_friends or uid in self.friends
            self.test_friends[uid] = {"name": name, "pk": pk, "nick": nick, "xpk": xpk,
                                      "since": time.strftime("%Y-%m-%d")}
            if not already:
                self.add_line(f"(testing) You and {nick or 'them'} count as friends for this "
                              "session - not saved, not shown on the Friends page.")
            self.update_people_ui()
            return
        already = uid in self.friends
        if self.friend_store is None:
            self.friend_store = FriendStore(self.data_dir)
            self.friend_store.data = self.friends
        self.friend_store.add(uid, pk, name, nick, xpk)
        self.friends = self.friend_store.data
        if not already:
            self.add_line(f"You and {nick or 'them'} are now friends: {name}.")
        self.update_people_ui()
        self.refresh_friends_page()

    def remove_friend(self, uid):
        if self.test_friends.pop(uid, None) is not None:
            self.update_people_ui()
            return
        if self.friend_store is None:
            self.friend_store = FriendStore(self.data_dir)
            self.friend_store.data = self.friends
        self.friend_store.remove(uid)
        self.friends = self.friend_store.data
        self.update_people_ui()
        self.refresh_friends_page()

    def on_friend(self, src, raw):
        """A friend message from person `src` (checked against who they proved to be)."""
        self.friend_sweep()
        ident = self.peer_ids.get(src)
        if not (self.identity and ident):
            return
        try:
            d = json.loads(raw.decode("utf-8"))
            kind = d["t"]
            if kind == "no":
                if self.friend_out.pop(src, None) is not None:
                    self.add_line(f"{self.names.get(src, 'They')} declined your friend request.")
                    self.update_people_ui()
                return
            if d["uid"] != ident[0]:
                return
            me = self.identity.uid
            if kind == "req":
                xpk = bytes.fromhex(d["xpk"]) if d.get("xpk") else b""
                if d["pk"] != ident[1] or not verify_sig(
                        d["pk"], d["sig"], b"fr-req|" + me.encode("utf-8") +
                        bytes.fromhex(d["eph"]) + xpk):
                    return
                req = {"uid": d["uid"], "pk": d["pk"], "eph": bytes.fromhex(d["eph"]),
                       "xpk": d.get("xpk"), "time": time.monotonic()}
                if len(req["eph"]) != 32 or (req["xpk"] is not None and len(xpk) != 32):
                    return
                if self.friend_of(src):
                    # already friends: refresh quietly, keeping it a test-friend if that's
                    # all it ever was (a refresh must never promote it to a real one)
                    still_test = d["uid"] in self.test_friends and d["uid"] not in self.friends
                    self.friend_accept(src, req, test=still_test)
                elif src in self.friend_out:
                    if me < d["uid"]:                            # both asked at once: one side answers
                        self.friend_out.pop(src, None)
                        self.friend_accept(src, req, test=self.is_test_peer(src))
                elif src not in self.friend_in:
                    if self.is_test_peer(src):   # same-PC testing: accept silently, no card
                        self.friend_accept(src, req, test=True)
                    else:
                        self.friend_in[src] = req
                        self.add_friend_card(src)
                        self.update_people_ui()
            elif kind == "acc":
                out = self.friend_out.get(src)
                if out is None or d["pk"] != out["pk"] or d["uid"] != out["uid"]:
                    return
                b_eph, nonce, sealed = (bytes.fromhex(d[k]) for k in ("eph", "n", "ct"))
                b_xpk = bytes.fromhex(d["xpk"]) if d.get("xpk") else b""
                if not verify_sig(d["pk"], d["sig"], b"fr-acc|" + me.encode("utf-8") +
                                  out["eph_pub"] + b_eph + nonce + sealed + b_xpk):
                    return
                if d.get("xpk") and len(b_xpk) != 32:
                    return
                shared = out["eph"].exchange(X25519PublicKey.from_public_bytes(b_eph))
                k_a2b, k_b2a = friend_keys(shared, out["eph_pub"], b_eph)
                name = ChaCha20Poly1305(k_b2a).decrypt(
                    nonce, sealed, (me + d["uid"]).encode("utf-8")).decode("utf-8")
                nonce2 = os.urandom(12)
                sealed2 = ChaCha20Poly1305(k_a2b).encrypt(
                    nonce2, self.identity.name.encode("utf-8"), (me + d["uid"]).encode("utf-8"))
                sig = self.identity.sign(b"fr-nm|" + d["uid"].encode("utf-8") + out["eph_pub"] +
                                         b_eph + nonce2 + sealed2)
                self.send_friend(src, {"t": "nm", "uid": me, "n": nonce2.hex(),
                                       "ct": sealed2.hex(), "sig": sig.hex()})
                del self.friend_out[src]
                self.save_friend(src, d["uid"], d["pk"], name, d.get("xpk"), out.get("test", False))
            elif kind == "nm":
                w = self.friend_wait.get(src)
                if w is None or d["uid"] != w["uid"]:
                    return
                nonce, sealed = bytes.fromhex(d["n"]), bytes.fromhex(d["ct"])
                if not verify_sig(w["pk"], d["sig"], b"fr-nm|" + me.encode("utf-8") +
                                  w["a_eph"] + w["b_eph"] + nonce + sealed):
                    return
                name = ChaCha20Poly1305(w["k_a2b"]).decrypt(
                    nonce, sealed, (w["uid"] + me).encode("utf-8")).decode("utf-8")
                del self.friend_wait[src]
                self.save_friend(src, w["uid"], w["pk"], name, w.get("xpk"), w.get("test", False))
        except (ValueError, KeyError, TypeError, InvalidTag, UnicodeDecodeError):
            return

    def add_friend_card(self, pid):
        """A friend request in the chat, with Accept / Decline."""
        box = tk.Frame(self.msg_frame, bg=PANEL, padx=14, pady=10)
        box.pack(fill="x", padx=14, pady=(10, 2))
        text = tk.Label(box, font=FONT, bg=PANEL, fg=TEXT, anchor="w", justify="left",
                        wraplength=max(200, self.wrap_len() + 20))
        text.pack(fill="x")
        name = self.names.get(pid, "Someone")
        uid = self.peer_ids.get(pid, ("?",))[0]
        self.live(text, lambda mk: f"{mk(name)} (ID {uid}) wants to be your friend.\n"
                                   "If you accept, you will see each other's real names.")
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))

        def answer(accept):
            for child in row.winfo_children():
                child.destroy()
            self.friend_answer(pid, accept)
            tk.Label(row, text="Accepted." if accept else "Declined.", font=FONT_SMALL,
                     bg=PANEL, fg=MUTED).pack(side="left")
        make_button(row, "Accept", GREEN, GREEN_HOVER, lambda: answer(True),
                    padx=14, pady=4).pack(side="left")
        make_button(row, "Decline", RED, RED_HOVER, lambda: answer(False),
                    padx=14, pady=4).pack(side="left", padx=(8, 0))
        self.scroll_to_bottom()

    def person_details(self, parent, pid):
        """The little panel under a person in the People list."""
        box = tk.Frame(parent, bg=STRIP)
        box.pack(fill="x")
        ident = self.peer_ids.get(pid)
        inner = tk.Frame(box, bg=STRIP)
        inner.pack(fill="x", padx=36, pady=(2, 8))
        if not ident or not self.identity:
            tk.Label(inner, text="No friend ID (they use an older version).", font=FONT_SMALL,
                     bg=STRIP, fg=MUTED, anchor="w").pack(fill="x")
            return
        tk.Label(inner, text=f"Friend ID  {ident[0]}", font=("Consolas", 9), bg=STRIP,
                 fg=MUTED, anchor="w").pack(fill="x")
        row = tk.Frame(inner, bg=STRIP)
        row.pack(fill="x", pady=(6, 0))
        f = self.friend_of(pid)
        if f:
            tk.Label(row, text=f"Friends ✓  {f['name']}", font=FONT_SMALL, bg=STRIP,
                     fg=STATE_COLORS["ok"]).pack(side="left")
            make_button(row, "Remove friend", LINE, HOVER,
                        lambda u=ident[0]: self.remove_friend(u),
                        padx=8, pady=1, font=FONT_SMALL).pack(side="right")
        elif pid in self.friend_in:
            make_button(row, "Accept", GREEN, GREEN_HOVER, lambda: self.friend_answer(pid, True),
                        padx=10, pady=1, font=FONT_SMALL).pack(side="left")
            make_button(row, "Decline", RED, RED_HOVER, lambda: self.friend_answer(pid, False),
                        padx=10, pady=1, font=FONT_SMALL).pack(side="left", padx=(6, 0))
        elif pid in self.friend_out or pid in self.friend_wait:
            tk.Label(row, text="Waiting for an answer...", font=FONT_SMALL, bg=STRIP,
                     fg=STATE_COLORS["wait"]).pack(side="left")
        else:
            make_button(row, "Add friend", ACCENT, ACCENT_HOVER, lambda: self.friend_request(pid),
                        padx=10, pady=1, font=FONT_SMALL).pack(side="left")

    def toggle_person(self, pid):
        self.open_person = None if self.open_person == pid else pid
        self.render_people()

    def refresh_profile(self):
        if self.identity is not None and getattr(self, "profile_lbl", None) is not None:
            self.profile_lbl.config(
                text=f"Name  {self.identity.name}\nFriend ID  {self.identity.uid}")

    def refresh_friends_page(self):
        box = getattr(self, "friends_inner", None)
        if box is None:
            return
        for child in box.winfo_children():
            child.destroy()
        if not self.friends:
            tk.Label(box, text="No friends yet. Open the People tab in a room and click "
                               "someone to add them.", font=FONT, bg=BG, fg=MUTED,
                     wraplength=380, justify="center").pack(pady=40, padx=20)
            return
        for uid, f in sorted(self.friends.items(), key=lambda kv: kv[1]["name"].lower()):
            card = tk.Frame(box, bg=PANEL, padx=16, pady=10)
            card.pack(fill="x", padx=16, pady=(10, 0))
            top = tk.Frame(card, bg=PANEL)
            top.pack(fill="x")
            tk.Label(top, text=self.mask(f["name"]), font=FONT_BOLD, bg=PANEL, fg=TEXT).pack(side="left")
            make_button(top, "Remove", LINE, HOVER, lambda u=uid: self.remove_friend(u),
                        padx=10, pady=2, font=FONT_SMALL).pack(side="right")
            tk.Label(card, text=f"ID {uid}   ·   last seen as '{self.mask(f.get('nick', ''))}'",
                     font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w").pack(fill="x")

    # ---------- log ----------
    def add_line(self, text):
        """Small centered grey line for system messages."""
        lbl = tk.Label(self.msg_frame, text=text, font=FONT_SMALL, bg=BG, fg=MUTED,
                       wraplength=self.wrap_len() + 60, justify="center")
        lbl.pack(pady=(8, 2))
        self.live(lbl, lambda mk: mk(text))
        self.scroll_to_bottom()

    def add_bubble(self, text, mine, name="Someone"):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        row = tk.Frame(self.msg_frame, bg=BG)
        row.pack(fill="x", padx=10, pady=(0, 0))   # eased up to its real (6, 0) as it pops in
        col = tk.Frame(row, bg=BG)
        col.pack(side="right" if mine else "left")

        color = BUBBLE_ME if mine else BUBBLE_FRIEND
        clean_text, style_ranges = parse_markdown(text) if "*" in text else (text, [])
        spans = self.word_filter.find(clean_text)
        if spans or self.emoji_imgs.has_emoji(clean_text) or style_ranges:
            shell, box = self.make_spoiler_bubble(col, clean_text, spans, color, mine, style_ranges)
            shell.pack(anchor="e" if mine else "w")
            self.animate_bubble_in(row, box, color, shell=shell)
        else:
            shell = RoundedBubble(col, color, radius=12)
            lbl = tk.Label(shell.canvas, text=clean_text, bg=color, fg="white",
                           font=("Segoe UI", 10), justify="left", wraplength=self.wrap_len(),
                           padx=12, pady=8)
            shell.attach(lbl)
            shell.pack(anchor="e" if mine else "w")
            self.bubbles.append(lbl)
            self.animate_bubble_in(row, lbl, color, grow_pad=(12, 8), shell=shell)

        who = "You" if mine else self.label_for_nick(name)
        stamp = time.strftime("%H:%M")
        meta = tk.Label(col, font=FONT_SMALL, bg=BG, fg=MUTED)
        meta.pack(anchor="e" if mine else "w", pady=(1, 0))
        self.live(meta, lambda mk: f"{mk(who)} · {stamp}")
        self.scroll_to_bottom()

    def animate_bubble_in(self, row, bubble, final_bg, grow_pad=None, shell=None):
        """A very small, quick "pop": a freshly added message fades in from the
        page's own background colour instead of just appearing, and its row eases
        down into its normal spacing. For an ordinary (non-spoiler) bubble it also
        grows from a sliver up to its full padding, so it looks like it's popping
        into place. Same ease-out curve switch_to() uses for page transitions, just
        much smaller and faster - meant to be felt more than seen. `shell` is the
        bubble's RoundedBubble wrapper, if it has one (see add_bubble) - its
        rounded background is faded in lock-step with the bubble itself."""
        steps = 8
        bg_now = BG   # captured once: the page colour the bubble is fading in from

        def step(i):
            if not (row.winfo_exists() and bubble.winfo_exists()):
                return
            t = 1 - (1 - i / steps) ** 3
            try:
                color = blend_hex(bg_now, final_bg, t)
                if shell is not None:
                    shell.set_fill(color)
                else:
                    bubble.configure(bg=color)
                row.pack_configure(pady=(round(6 * t), 0))
                if grow_pad:
                    bubble.configure(padx=round(grow_pad[0] * t), pady=round(grow_pad[1] * t))
            except tk.TclError:
                return
            if i < steps:
                self.root.after(14, step, i + 1)

        step(1)

    def make_spoiler_bubble(self, parent, text, spans, color, mine, style_ranges=()):
        """A message that holds swear words and/or *markdown* emphasis. It is a
        read-only Text so single words can be covered (with Filter words on, they're
        bars you click to open) and so part of the text can be bold/italic while the
        rest isn't - a plain Label can't do either of those. Returns (shell, box):
        shell is the rounded-corner wrapper to pack, box is the Text widget itself."""
        shell = RoundedBubble(parent, color, radius=12)
        font = tkfont.Font(family="Segoe UI", size=10)
        box = tk.Text(shell.canvas, bg=color, fg="white", font=font, relief="flat", bd=0,
                      highlightthickness=0, wrap="word", padx=12, pady=8, width=10, height=1,
                      cursor="arrow", spacing1=0, spacing3=0, takefocus=0,
                      selectbackground=ACCENT, inactiveselectbackground=ACCENT)
        shell.attach(box)
        box.font_obj, box.raw, box.color = font, text, color
        box.spans, box.opened = spans, set()

        # Markdown fonts are derived from this bubble's own font, so bold/italic
        # always match its family and size exactly.
        box.md_fonts = (
            tkfont.Font(family="Segoe UI", size=10, weight="bold"),           # md_b
            tkfont.Font(family="Segoe UI", size=10, slant="italic"),          # md_i
            tkfont.Font(family="Segoe UI", size=10, weight="bold", slant="italic"),  # md_bi
        )
        box.tag_configure("md_b", font=box.md_fonts[0])
        box.tag_configure("md_i", font=box.md_fonts[1])
        box.tag_configure("md_bi", font=box.md_fonts[2])

        def style_at(pos):
            for a, b, bold, italic in style_ranges:
                if a <= pos < b:
                    return bold, italic
            return False, False

        def spoiler_at(pos):
            for i, (a, b) in enumerate(spans):
                if a <= pos < b:
                    return i
            return None

        # Spoiler-word boundaries and markdown-style boundaries can fall anywhere
        # relative to each other, so cut the text at every boundary either one cares
        # about - each resulting piece then has one unambiguous (spoiler index or
        # none, bold, italic) to tag it with, and both kinds of tag can land on it.
        cuts = sorted({0, len(text)} | {p for a, b in spans for p in (a, b)}
                      | {p for a, b, *_ in style_ranges for p in (a, b)})
        for a, b in zip(cuts, cuts[1:]):
            if a >= b:
                continue
            word_idx = spoiler_at(a)
            bold, italic = style_at(a)
            tags = []
            if word_idx is not None:
                tag = f"w{word_idx}"
                tags.append(tag)
                box.tag_bind(tag, "<Button-1>", lambda e, bx=box, n=word_idx: self.click_word(bx, n))
                box.tag_bind(tag, "<Enter>", lambda e, bx=box, n=word_idx: self.word_cursor(bx, n, True))
                box.tag_bind(tag, "<Leave>", lambda e, bx=box, n=word_idx: self.word_cursor(bx, n, False))
            if bold and italic:
                tags.append("md_bi")
            elif bold:
                tags.append("md_b")
            elif italic:
                tags.append("md_i")
            self.put_text(box, text[a:b], tags)
            if word_idx is not None:
                box.tag_raise(f"w{word_idx}")
        box.configure(state="disabled")
        self.text_bubbles.append(box)
        self.style_spoilers(box)
        self.fit_text(box)
        return shell, box

    def put_text(self, box, piece, tags=()):
        """Adds text to a bubble; every emoji in it becomes a coloured picture. Any
        `tags` (a spoiler-word tag, a markdown bold/italic tag, both, or neither) are
        applied over the whole inserted range afterwards, images included."""
        start = box.index("end-1c")
        if not self.emoji_imgs.available:
            box.insert("end", piece)
        else:
            pos = 0
            for m in EMOJI_RE.finditer(piece):
                box.insert("end", piece[pos:m.start()])
                img = self.emoji_imgs.get(m.group(), box.color)
                if img is None:
                    box.insert("end", m.group())
                else:
                    box.image_create("end", image=img, padx=1, align="center")
                pos = m.end()
            box.insert("end", piece[pos:])
        if tags:
            end = box.index("end-1c")
            for t in tags:
                box.tag_add(t, start, end)

    def style_spoilers(self, box):
        for i in range(len(box.spans)):
            tag = f"w{i}"
            if self.filter_on and i not in box.opened:      # covered
                box.tag_configure(tag, background=SPOILER, foreground=SPOILER)
            elif self.filter_on:                            # opened by a click: click to cover again
                box.tag_configure(tag, background=SPOILER_OPEN, foreground="white")
            else:                                           # filter is off: ordinary text
                box.tag_configure(tag, background=box.color, foreground="white")

    def click_word(self, box, n):
        if not self.filter_on:
            return None
        box.opened.symmetric_difference_update({n})         # open <-> covered
        self.style_spoilers(box)
        return "break"

    def word_cursor(self, box, n, inside):
        box.configure(cursor="hand2" if inside and self.filter_on else "arrow")

    def fit_text(self, box):
        """Sizes a Text bubble to its words, like a Label with a wrap length."""
        font = box.font_obj
        limit = self.wrap_len() - 24
        flat = EMOJI_RE.sub("00", box.raw) if self.emoji_imgs.available else box.raw
        need = max(font.measure(line) for line in flat.split("\n"))
        zero = max(1, font.measure("0"))
        # Measure with a tall box, so every line is laid out (a 1-line box only lays out one).
        box.configure(width=max(2, int((min(need, limit) + 8) / zero) + 1), height=100)
        box.update()
        try:
            rows = box.count("1.0", "end-1c", "update", "displaylines")
            rows = int(rows[0] if isinstance(rows, (tuple, list)) else (rows or 1))
            info = box.dlineinfo("end-1c")         # the last line's position: counts lines with
            if info:                               # emoji pictures in them more reliably
                bottom = info[1] + info[3] - int(box.cget("pady"))
                rows = max(rows, -(-bottom // max(1, font.metrics("linespace"))))
            box.configure(height=max(1, rows))
        except (tk.TclError, TypeError, IndexError, ValueError):
            box.configure(height=max(1, len(box.raw.split("\n"))))

    def post(self, session, kind, value=None):
        self.incoming.put((session, kind, value))

    # ---------- small popups (same style as the app) ----------
    def make_dialog(self, title, heading, subtitle):
        """A dark popup with a card in it. Returns (dialog, card)."""
        dlg = tk.Toplevel(self.root)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        card = tk.Frame(dlg, bg=PANEL, padx=30, pady=26)
        card.pack(padx=20, pady=20)
        tk.Label(card, text=heading, font=("Segoe UI", 16, "bold"), bg=PANEL, fg=TEXT).pack()
        tk.Label(card, text=subtitle, font=FONT, bg=PANEL, fg=MUTED,
                 wraplength=300).pack(pady=(2, 16))
        return dlg, card

    def run_dialog(self, dlg, focus, closable=True):
        if closable:
            dlg.bind("<Escape>", lambda e: dlg.destroy())
        center_window(dlg, parent=self.root)
        try:
            dlg.wait_visibility()
            dlg.grab_set()  # block the main window until this popup is closed
        except tk.TclError:
            pass
        focus.focus_set()
        self.root.wait_window(dlg)

    def ask_room_settings(self, relay=False):
        """Popup for the host: nickname + maximum number of people (+ for a relay room,
        whether friends can find it by searching). Returns (nickname, max_people, hidden),
        or None when the person cancels."""
        subtitle = ("Choose your name and how many people can be in the room.\n\n"
                   "This room goes through a public internet relay instead of your own "
                   "network. Messages stay encrypted, but the relay (run by someone else) "
                   "can see that the room exists and roughly when people use it.") if relay else \
                   "Choose your name and how many people can be in the room."
        dlg, card = self.make_dialog("Create a room", "Create a room", subtitle)

        tk.Label(card, text="Your nickname", font=FONT_SMALL, bg=PANEL, fg=MUTED,
                 anchor="w").pack(fill="x")
        nick = make_entry(card, limit=NICK_MAX)
        nick.pack(fill="x", ipady=6, pady=(2, 10))
        # Its own remembered name, kept apart from the one used to join/search a
        # room (see search_nickname) - hosting and joining are different enough
        # habits that one shouldn't overwrite the other.
        last_host_nick = load_settings().get("host_nickname", "")
        if last_host_nick:
            nick.insert(0, last_host_nick)

        tk.Label(card, text="Maximum people (including you)", font=FONT_SMALL, bg=PANEL,
                 fg=MUTED, anchor="w").pack(fill="x")
        count = make_entry(card, limit=3)
        count.pack(fill="x", ipady=6, pady=(2, 0))

        def only_digits(*_):
            text = count.var.get()
            clean = "".join(ch for ch in text if ch.isdigit())
            if clean != text:
                count.var.set(clean)
        count.var.trace_add("write", only_digits)

        tk.Label(card, text=f"2 to {MAX_ROOM_PEOPLE}. Leave empty for {DEFAULT_ROOM_PEOPLE}.",
                 font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(4, 0))

        findable = None
        if relay:
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=(14, 0))
            tk.Label(row, text="Let friends find this room when they search",
                     font=FONT, bg=PANEL, fg=TEXT, anchor="w", justify="left",
                     wraplength=220).pack(side="left")
            findable = Switch(row, PANEL, on=True)
            findable.pack(side="right", padx=(8, 0))

        error = tk.Label(card, text="", font=FONT_SMALL, bg=PANEL, fg=RED, anchor="w",
                         wraplength=300, justify="left")
        error.pack(fill="x", pady=(6, 6))

        result = {"value": None}

        def ok(event=None):
            name = clean_nickname(nick.get())
            if not name:
                error.config(text="Please enter a nickname.")
                nick.focus_set()
                return
            raw = count.get().strip()
            n = int(raw) if raw else DEFAULT_ROOM_PEOPLE
            if n < 2:
                error.config(text="A room needs at least 2 people (you and one more).")
                return
            if n > MAX_ROOM_PEOPLE:
                error.config(text=f"The maximum is {MAX_ROOM_PEOPLE} people.")
                return
            result["value"] = (name, n, not (findable.on if findable else True))
            save_settings(host_nickname=name)
            dlg.destroy()

        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x")
        make_button(buttons, "Cancel", LINE, HOVER, dlg.destroy,
                    padx=14, pady=8).pack(side="left")
        make_button(buttons, "Create room", GREEN, GREEN_HOVER, ok,
                    padx=14, pady=8).pack(side="right")

        nick.bind("<Return>", lambda e: count.focus_set())
        count.bind("<Return>", ok)
        self.run_dialog(dlg, nick)
        return result["value"]

    def ask_recipients(self, others):
        """Popup to pick who gets a file - a checkbox per person (plus "Select all"),
        so a file can be sent to several people at once. Returns a list of ids
        (empty if cancelled)."""
        dlg, card = self.make_dialog("Send a file", "Send a file to...",
                                     "Choose who should receive it.")
        tvars = {pid: tk.BooleanVar(value=(i == 0)) for i, (pid, _) in enumerate(others)}

        top = tk.Frame(card, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, text=f"{len(others)} people here", font=FONT_SMALL, bg=PANEL,
                 fg=MUTED).pack(side="left")

        def select_all():
            turn_on = not all(v.get() for v in tvars.values())
            for v in tvars.values():
                v.set(turn_on)
        make_button(top, "Select all", LINE, HOVER, select_all,
                    padx=10, pady=4).pack(side="right")

        shown = min(8, len(others))
        row_h = 32
        wrap = tk.Frame(card, bg=INPUT, highlightthickness=1, highlightbackground=LINE)
        wrap.pack(fill="x", pady=(8, 0))
        cv = tk.Canvas(wrap, bg=INPUT, highlightthickness=0, width=260,
                       height=shown * row_h, yscrollincrement=12)
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=INPUT)
        win = cv.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        if len(others) > shown:
            sb = tk.Scrollbar(wrap, orient="vertical", command=cv.yview)
            cv.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.register_scroll(sb, cv)
        self.register_scroll(cv)
        for pid, name in others:
            row = tk.Checkbutton(inner, text=self.mask(name), variable=tvars[pid],
                                 bg=INPUT, fg=TEXT, selectcolor=INPUT, bd=0,
                                 activebackground=INPUT, activeforeground=TEXT,
                                 highlightthickness=0, font=FONT, anchor="w", padx=10)
            row.pack(fill="x")
            self.register_scroll(row, cv)

        result = {"ids": []}

        def ok(event=None):
            picked = [pid for pid, v in tvars.items() if v.get()]
            if picked:
                result["ids"] = picked
                dlg.destroy()

        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x", pady=(16, 0))
        make_button(buttons, "Cancel", LINE, HOVER, dlg.destroy,
                    padx=14, pady=8).pack(side="left")
        make_button(buttons, "Choose file", ACCENT, ACCENT_HOVER, ok,
                    padx=14, pady=8).pack(side="right")
        self.run_dialog(dlg, dlg)
        return result["ids"]

    def ask_ban(self, pid, name):
        """Asks the host to confirm a ban."""
        dlg, card = self.make_dialog("Ban", f"Ban {name}?",
                                     "They are removed now and cannot join this room again "
                                     "(even with the password) until you unban them.")
        result = {"ok": False}

        def ok(event=None):
            result["ok"] = True
            dlg.destroy()
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x")
        cancel = make_button(buttons, "Cancel", LINE, HOVER, dlg.destroy, padx=14, pady=8)
        cancel.pack(side="left")
        make_button(buttons, "Ban", RED, RED_HOVER, ok, padx=14, pady=8).pack(side="right")
        self.run_dialog(dlg, cancel)
        if result["ok"]:
            self.kick_person(pid, ban=True)

    def show_bans(self):
        room = self.room
        if room is None or not (room.banned or room.banned_uids):
            return
        dlg, card = self.make_dialog("Banned people", "Banned people",
                                     "Banned people are turned away at the door. A friend ID "
                                     "ban also survives them moving to a new address; an address "
                                     "ban does not, if their IP or relay connection changes.")
        with room.lock:
            items = [("ip", k, v) for k, v in room.banned.items()] + \
                    [("uid", k, v) for k, v in room.banned_uids.items()]
        shown = min(8, len(items))
        wrap = tk.Frame(card, bg=PANEL)
        wrap.pack(fill="x")
        lb = tk.Listbox(wrap, height=shown, width=34, bg=INPUT, fg=TEXT, font=FONT,
                        selectbackground=ACCENT, selectforeground="white",
                        activestyle="none", relief="flat", highlightthickness=1,
                        highlightbackground=LINE, highlightcolor=ACCENT, exportselection=False)
        for kind, key, name in items:
            lb.insert("end", f"{name}   ·   {key}" if kind == "ip" else f"{name}   ·   friend ID {key}")
        lb.selection_set(0)
        lb.pack(side="left", fill="x", expand=True)
        if len(items) > shown:
            sb = tk.Scrollbar(wrap, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            sb.pack(side="right", fill="y")
            self.register_scroll(sb, lb)
        self.register_scroll(lb)

        def unban(event=None):
            picked = lb.curselection()
            if not picked:
                return
            kind, key, name = items[picked[0]]
            with room.lock:
                (room.banned if kind == "ip" else room.banned_uids).pop(key, None)
            self.add_line(f"{name} ({key}) was unbanned.")
            dlg.destroy()
            self.update_ban_row()
        buttons = tk.Frame(card, bg=PANEL)
        buttons.pack(fill="x", pady=(16, 0))
        make_button(buttons, "Close", LINE, HOVER, dlg.destroy,
                    padx=14, pady=8).pack(side="left")
        make_button(buttons, "Unban selected", GREEN, GREEN_HOVER, unban,
                    padx=14, pady=8).pack(side="right")
        lb.bind("<Return>", unban)
        self.run_dialog(dlg, lb)

    # ---------- kick / ban (host only) ----------
    def kick_person(self, pid, ban=False):
        room = self.room
        member = room.get(pid) if (self.is_host and room is not None) else None
        if member is None:
            return
        with room.lock:
            member.kicked = True
            member.reason = "was banned from the room" if ban else "was kicked from the room"
            if ban:
                room.banned[member.addr[0]] = member.name
                if member.uid:                      # survives a relay room's addresses changing
                    room.banned_uids[member.uid] = member.name
        text = "You were banned from this room." if ban else "You were kicked out of the room."
        threading.Thread(target=self.eject, args=(member, text), daemon=True).start()
        self.update_ban_row()

    @staticmethod
    def eject(member, text):
        try:
            member.chan.send(K_BYE, text.encode("utf-8"))
        except OSError:
            pass
        member.chan.close(flush=True)

    # ---------- host ----------
    def start_host(self, relay=False):
        if relay and mqtt_lib is None:
            self.menu_error.config(text="This needs the paho-mqtt package. Go to "
                                        "Settings > Packages to install it, then try again.")
            return
        settings = self.ask_room_settings(relay=relay)
        if not settings:
            return  # cancelled
        if len(settings) == 3:
            nickname, max_people, start_hidden = settings
        else:
            nickname, max_people, start_hidden = settings[0], settings[1], False
        self.nickname = nickname

        if relay:
            try:
                server = RelayListener(generate_room_code())
            except OSError as e:
                messagebox.showerror("Host failed", f"Could not reach the relay:\n{e}")
                return
        else:
            ensure_firewall_rule(RULE_NAME + " search", "UDP", f"{DISCOVERY_PORT}-{KNOCK_PORT}")
            if not ensure_firewall_rule():
                messagebox.showwarning(
                    "Firewall",
                    "The firewall rule could not be created.\n"
                    "Other people may not be able to connect.")
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if os.name != "nt":
                    # On Windows this option would let other programs share our port.
                    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server.bind(("0.0.0.0", PORT))
                server.listen(16)
            except OSError as e:
                server.close()
                messagebox.showerror("Host failed", f"Could not start server:\n{e}")
                return

        self.session += 1
        password = generate_password()
        room = Room(self.session, nickname, password, max_people, server)
        room.hidden = start_hidden
        if self.identity:
            room.host_uid, room.host_pk = self.identity.uid, self.identity.pub_hex
        if relay:
            room.relay = True
            room.room_code = server.code
        self.room = room
        self.is_host = True
        self.joined = True
        self.relay = relay
        if relay:
            self.show_chat("Waiting for someone to join...", "wait",
                           host_info=(room.room_code, password), relay=True,
                           row_label="Room code", copy_label="Code")
            self.add_line(f"Room is open over the internet relay, you are {nickname}. Up to "
                          f"{max_people} people can be in it. The code and password are in the "
                          "bar above (hover to peek, click to keep it open) - whoever you give "
                          "them to can use \"Join using a code\" to get in. This goes through a "
                          "public relay: your messages stay encrypted, but the relay (and anyone "
                          "watching it) can see that this room exists and roughly when people in "
                          "it are active.")
        else:
            ip = get_local_ip()
            self.show_chat("Waiting for someone to join...", "wait", host_info=(ip, password))
            self.add_line(f"Room is open on port {PORT}, you are {nickname}. Up to {max_people} "
                          "people can be in it. The password is in the bar above (hover to peek, "
                          "click to keep it open); the IP address is in the People tab.")
        self.on_roster({"you": HOST_ID, "max": max_people, "people": room.people()})
        threading.Thread(target=self.host_accept_loop, args=(room,), daemon=True).start()
        if relay:
            threading.Thread(target=self.relay_announce_loop, args=(room,), daemon=True).start()
        else:
            threading.Thread(target=self.knock_loop, args=(room,), daemon=True).start()
            threading.Thread(target=self.announce_loop, args=(room,), daemon=True).start()

    def set_hidden(self, on):
        room = self.room
        if room is None:
            return
        room.hidden = bool(on)
        if room.relay:
            self.add_line("Your room is hidden: your friends no longer see it when they "
                          "search." if on else "Your friends can see this room when they search "
                          "again.")
        else:
            self.add_line("Your room is hidden: it no longer shows up in Search." if on else
                          "Your room shows up in Search again.")

    def relay_announce_loop(self, room):
        """Tells your friends - and only your friends - that this room exists, so it can
        show up when they search. No listening port is used: this only ever publishes
        outbound to the relay, the same connection that is already hosting the room."""
        client = room.server_sock.client
        while not room.closed:
            if not room.hidden and self.identity:
                with room.lock:
                    n = len(room.members) + 1
                beacon = json.dumps({
                    "from": self.identity.uid, "name": self.identity.name,
                    "host": room.host_name, "code": room.room_code, "pw": room.password,
                    "n": n, "max": room.max_people, "ts": time.time(),
                }, separators=(",", ":")).encode("utf-8")
                for uid, info in list(self.all_friends().items()):
                    xpk = info.get("xpk")
                    if not xpk:
                        continue
                    try:
                        key = lobby_key(self.identity, xpk)
                        nonce = os.urandom(12)
                        ct = ChaCha20Poly1305(key).encrypt(nonce, beacon, uid.encode("utf-8"))
                        envelope = json.dumps({"n": nonce.hex(), "ct": ct.hex()},
                                              separators=(",", ":")).encode("utf-8")
                        client.publish(LOBBY_TOPIC + uid, envelope, qos=0)
                    except (ValueError, OSError):
                        continue
            for _ in range(int(LOBBY_INTERVAL / 0.1)):
                if room.closed:
                    break
                time.sleep(0.1)

    def announce_loop(self, room):
        """Shouts "here is a room" on the local network every second or so."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        while not room.closed:
            if not room.hidden:
                with room.lock:
                    packet = json.dumps({
                        "app": APP_TAG, "rid": room.rid, "host": room.host_name,
                        "n": len(room.members) + 1, "max": room.max_people, "port": PORT,
                        "kp": room.knock_port,
                        "ban": [ban_hash(room.rid, ip) for ip in list(room.banned)[:20]],
                    }, separators=(",", ":")).encode("utf-8")
                for target in broadcast_targets():
                    try:
                        sock.sendto(packet, (target, DISCOVERY_PORT))
                    except OSError:
                        pass
            for _ in range(12):
                if room.closed:
                    break
                time.sleep(0.1)
        sock.close()

    def knock_loop(self, room):
        """Receives "I am trying to join" / "please let me in" notes and shows them."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", KNOCK_PORT))
        except OSError:
            sock.close()
            return                                   # no requests possible (port busy)
        room.knock_port = KNOCK_PORT
        sock.settimeout(1.0)
        while not room.closed:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            self.handle_knock(room, data, addr[0])
        sock.close()

    def handle_knock(self, room, data, ip):
        try:
            d = json.loads(data.decode("utf-8"))
            if not isinstance(d, dict) or d.get("app") != APP_TAG or d.get("rid") != room.rid:
                return
            kind = d["t"]
            if kind not in ("try", "ask"):
                return
        except (ValueError, KeyError, UnicodeDecodeError):
            return
        if ip in room.banned:
            return
        key, now = (ip, kind), time.monotonic()
        if now - room.knock_seen.get(key, -999) < 3:        # no flooding
            return
        if len(room.knock_seen) > 500:
            room.knock_seen.clear()
        room.knock_seen[key] = now
        nick = clean_nickname(str(d.get("nick", ""))) or "Someone"
        if kind == "try":
            self.post(room.session, "sys", f"{nick} ({ip}) is trying to join.")
            return
        try:
            pk, rp = str(d["pk"]), int(d["rp"])
            if len(pk) != 64 or bytes.fromhex(pk) is None or not 1 <= rp <= 65535:
                return
        except (KeyError, ValueError, TypeError):
            return
        self.post(room.session, "request", {"nick": nick, "ip": ip, "pk": pk, "rp": rp,
                                            "msg": clean_text(d.get("msg", ""), 120)})

    def host_accept_loop(self, room):
        while True:
            try:
                conn, addr = room.server_sock.accept()
            except OSError:
                err = getattr(room.server_sock, "error", None)
                if err and not room.closed:
                    self.post(room.session, "sys", f"Lost the relay: {err}")
                return  # server socket was closed (disconnect / quit, or a relay error)
            with room.lock:
                busy = (room.closed or len(room.pending) >= MAX_PENDING
                        or room.pending_ip.get(addr[0], 0) >= MAX_PENDING_PER_IP)
                if not busy:
                    room.pending.add(conn)
                    room.pending_ip[addr[0]] = room.pending_ip.get(addr[0], 0) + 1
            if busy:
                conn.close()
                if room.closed:
                    return
                continue
            threading.Thread(target=self.host_serve_member, args=(room, conn, addr),
                             daemon=True).start()

    def host_serve_member(self, room, conn, addr):
        """One thread per person: log them in, then relay what they send."""
        session = room.session
        if not room.relay:   # a real socket - the relay's "conn" is a faked-up stand-in
            enable_tcp_keepalive(conn)

        def slow():  # runs *inside* handshake(), before the socket is torn down -
            with room.fail_lock:          # otherwise the attempt is already over by the
                time.sleep(1)             # time anything here could slow it down
        try:
            chan, wanted = handshake(conn, room.password, True, room.host_name,
                                     identity=self.identity, slow_fail=slow)
        except HandshakeError:
            chan = None
        if chan is None:
            conn.close()
            self.post(session, "sys", f"{addr[0]} tried to join with a wrong password.")
            with room.lock:
                room.pending.discard(conn)
                room.pending_ip[addr[0]] = max(0, room.pending_ip.get(addr[0], 1) - 1)
            return

        with room.lock:
            room.pending.discard(conn)
            room.pending_ip[addr[0]] = max(0, room.pending_ip.get(addr[0], 1) - 1)

        ident = getattr(chan, "peer_identity", None)
        banned_as = room.banned.get(addr[0]) or (ident and room.banned_uids.get(ident[0]))
        if banned_as is not None:
            try:
                chan.send(K_BYE, "You are banned from this room.".encode("utf-8"))
            except OSError:
                pass
            chan.close(flush=True)
            now = time.monotonic()
            if now - room.ban_notice.get(addr[0], -999) > 10:   # don't flood the log
                room.ban_notice[addr[0]] = now
                self.post(session, "sys", f"{banned_as} ({addr[0]}) tried to join, but is banned.")
            return

        member = room.admit(wanted, chan, addr)
        if member is None:
            reason = "The room is closed." if room.closed else "The room is full."
            try:
                chan.send(K_BYE, reason.encode("utf-8"))
            except OSError:
                pass
            chan.close(flush=True)
            if not room.closed:
                self.post(session, "sys", f"{wanted} tried to join, but the room is full.")
            return

        if ident:
            member.uid, member.pk = ident
        if addr[0] in my_lan_ips():
            self._loopback_peers.add(member.id)
        if room.relay:
            try:
                chan.sock.settimeout(1.5)   # wake member_loop regularly to check liveness
            except OSError:
                pass
            threading.Thread(target=self.ping_loop, args=(chan,), daemon=True).start()
        self.send_roster(room)
        room.send_all(K_SYS, f"{member.name} joined the room.".encode("utf-8"), skip=member)
        self.post(session, "sys", f"{member.name} joined the room.")
        try:
            self.member_loop(room, member)
        finally:
            was_in = room.remove(member)
            self._loopback_peers.discard(member.id)
            member.chan.close()
            if was_in and not room.closed:
                self.send_roster(room)
                what = member.reason or "left the room"
                room.send_all(K_SYS, f"{member.name} {what}.".encode("utf-8"))
                self.post(session, "sys", f"{member.name} {what}.")

    def send_roster(self, room):
        """Tells everybody (the guests and our own window) who is in the room."""
        # The lock is held the whole time so two people joining at once can't send
        # their lists in the wrong order (which would leave an old list on screen).
        # Nothing here waits on the network: messages are only put in queues.
        with room.lock:
            people = room.people()
            for m in room.others():
                data = {"you": m.id, "max": room.max_people, "people": people}
                try:
                    m.chan.send(K_ROSTER, json.dumps(data).encode("utf-8"))
                except OSError:
                    pass
            self.post(room.session, "roster",
                      {"you": HOST_ID, "max": room.max_people, "people": people})

    def member_loop(self, room, member):
        session = room.session
        while True:
            try:
                kind, payload = member.chan.recv()
            except TimeoutError:
                # only happens for a relay member (see host_serve_member) - no data showed
                # up in time, which is normal; only act once they've truly gone quiet
                if room.relay and time.monotonic() - member.last_seen > RELAY_PING_TIMEOUT:
                    try:
                        member.chan.send(K_BYE, "You went quiet for too long.".encode("utf-8"))
                    except OSError:
                        pass
                    member.chan.close(flush=True)
                    self.post(session, "sys", f"{member.name} went quiet and was disconnected.")
                    return
                continue
            except (OSError, InvalidTag, ValueError):  # closed connection, or tampered data
                return
            member.last_seen = time.monotonic()
            try:
                if kind == K_TEXT:
                    text = payload.decode("utf-8", errors="replace")[:MAX_MESSAGE_CHARS]
                    if text.strip():
                        msg = json.dumps({"n": member.name, "t": text}).encode("utf-8")
                        room.send_all(K_MSG, msg, skip=member)
                        self.post(session, "msg", (member.name, text))
                elif kind == K_LEAVE:
                    return  # they are disconnecting on purpose - the usual cleanup follows
                elif kind == K_PING:
                    pass  # just a liveness signal - last_seen was already refreshed above
                elif kind == K_TYPING:
                    room.send_all(K_TYPING, struct.pack(">H", member.id), skip=member)
                    self.post(session, "typing", member.id)
                elif kind in FILE_KINDS:
                    self.host_file_frame(room, member, kind, payload)
                elif kind == K_FRIEND:
                    self.host_friend_frame(room, member, payload)
            except (ValueError, KeyError, TypeError, struct.error):
                continue  # malformed message from that person: ignore it

    def ping_loop(self, chan):
        """Relay connections give no hint when the other side just vanishes - no
        network-level "closed" signal, unlike a real TCP socket - so each side sends a
        tiny "I'm still here" every few seconds, and the other watches for it going
        quiet too long (see member_loop and guest_loop)."""
        while not getattr(chan, "_closed", True):
            try:
                chan.send(K_PING, b"")
            except OSError:
                return
            for _ in range(int(RELAY_PING_INTERVAL / 0.5)):
                if getattr(chan, "_closed", True):
                    return
                time.sleep(0.5)

    def host_friend_frame(self, room, member, payload):
        """A friend message between two people: pass it on (the host can't read the
        names inside, they are encrypted for the other person)."""
        (dest,) = struct.unpack(">H", payload[:2])
        body = payload[2:]
        if len(body) > 4096:
            return
        if dest == HOST_ID:
            self.post(room.session, "friend", (member.id, body))
            return
        target = room.get(dest)
        if target is not None and target is not member:
            try:
                target.chan.send(K_FRIEND, struct.pack(">H", member.id) + body)
            except OSError:
                pass

    def host_file_frame(self, room, member, kind, payload):
        """A file message from a guest: it is either for us, or for another guest."""
        (dest,) = struct.unpack(">H", payload[:2])
        body = payload[2:]
        if dest == HOST_ID:
            self.handle_file_frame(room.session, member.id, kind, body)
            return
        target = room.get(dest)
        try:
            if target is None or target is member:
                if kind == K_OFFER:  # nobody there: tell the sender right away
                    tid = int(json.loads(body.decode("utf-8"))["id"])
                    member.chan.send(K_REJECT, struct.pack(">HI", dest, tid))
                return
            # Pass it on, marked with who it comes from. A slow receiver slows
            # down only this sender (file pieces wait in line, see SecureChannel).
            target.chan.send(kind, struct.pack(">H", member.id) + body, bulk=(kind == K_CHUNK))
        except OSError:
            pass

    # ---------- connect ----------
    # ---------- search + join ----------
    def start_search(self):
        nickname = clean_nickname(self.nick_entry.get())
        if not nickname:
            self.menu_error.config(text="Choose a nickname first, then search.")
            self.nick_entry.focus_set()
            return
        self.nickname = nickname
        save_settings(search_nickname=nickname)
        self.menu_error.config(text="")
        self.open_search()

    def open_search(self, note="", bad=True):
        self.switch_to(self.pages["search"], 1)
        self.search_note.config(text=note, fg=RED if bad else STATE_COLORS["ok"])
        self.rooms_sig = None
        with self.found_lock:
            self.found = {}
        self.search_problem = ""
        with self.found_lock:
            self.found_relay = {}
        self.search_stop = threading.Event()
        threading.Thread(target=self.search_listen, args=(self.search_stop,), daemon=True).start()
        threading.Thread(target=self.relay_search_listen, args=(self.search_stop,),
                         daemon=True).start()
        self.search_tick()

    def stop_search(self):
        if self.search_stop is not None:
            self.search_stop.set()
            self.search_stop = None

    def search_listen(self, stop):
        """Collects the announcements of rooms on this network."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", DISCOVERY_PORT))
        except OSError as e:
            sock.close()
            self.search_problem = f"Could not start searching: {e}"
            return
        sock.settimeout(0.5)
        mine = {get_local_ip(), "127.0.0.1"}
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                d = json.loads(data.decode("utf-8"))
                if not isinstance(d, dict) or d.get("app") != APP_TAG:
                    continue
                rid = str(d["rid"])[:16]
                info = {
                    "rid": rid, "ip": addr[0], "port": int(d.get("port", PORT)),
                    "kp": int(d.get("kp", 0)), "host": clean_text(d["host"], NICK_MAX),
                    "n": int(d["n"]), "max": int(d["max"]), "seen": time.monotonic(),
                    "banned": any(ban_hash(rid, ip) in [str(h) for h in d.get("ban", [])[:30]]
                                  for ip in mine),
                }
                if not (1 <= info["port"] <= 65535 and 0 <= info["kp"] <= 65535):
                    continue
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                continue
            with self.found_lock:
                old = self.found.get(rid)
                if old and not old["ip"].startswith("127.") and addr[0].startswith("127."):
                    info["ip"] = old["ip"]           # prefer the real address over the test copy
                if len(self.found) < 60 or old:
                    self.found[rid] = info
        sock.close()

    def relay_search_listen(self, stop):
        """Picks up "I'm hosting a room" beacons from friends, over the relay. This only
        ever makes an outbound connection to the relay (same as hosting/joining does) -
        no port is opened, so there is nothing for a firewall to ask about."""
        if mqtt_lib is None or not self.identity:
            return
        topic = LOBBY_TOPIC + self.identity.uid
        client = mqtt_client("ipchat-s-" + secrets.token_hex(8))

        def on_connect(c, u, flags, rc, props=None):
            if rc == 0:
                c.subscribe(topic, qos=0)

        def on_message(c, u, m):
            try:
                env = json.loads(m.payload.decode("utf-8"))
                nonce, ct = bytes.fromhex(env["n"]), bytes.fromhex(env["ct"])
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                return
            for uid, info in list(self.all_friends().items()):
                xpk = info.get("xpk")
                if not xpk:
                    continue
                try:
                    key = lobby_key(self.identity, xpk)
                    plain = ChaCha20Poly1305(key).decrypt(
                        nonce, ct, self.identity.uid.encode("utf-8"))
                    d = json.loads(plain.decode("utf-8"))
                    if d.get("from") != uid:
                        continue
                    code, pw = str(d["code"]), str(d["pw"])
                    n, mx = int(d["n"]), int(d["max"])
                    if len(code) != ROOM_CODE_LENGTH:
                        continue
                except (InvalidTag, ValueError, KeyError, TypeError, UnicodeDecodeError):
                    continue
                with self.found_lock:
                    self.found_relay[code] = {
                        "rid": "relay:" + code, "relay": True, "code": code, "password": pw,
                        "host": clean_text(str(d.get("host") or info["name"]), NICK_MAX),
                        "n": n, "max": mx, "banned": False, "kp": 0,
                        "seen": time.monotonic(),
                    }
                return

        client.on_connect, client.on_message = on_connect, on_message
        try:
            client.connect(RELAY_HOST, RELAY_PORT, 60)
            client.loop_start()
        except OSError:
            return
        self.relay_search = client
        stop.wait()
        self.relay_search = None
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass

    def search_tick(self):
        stop = self.search_stop
        if stop is None or stop.is_set():       # leaving the page stops the search
            return
        now = time.monotonic()
        with self.found_lock:
            for rid in [r for r, i in self.found.items() if now - i["seen"] > STALE_AFTER]:
                del self.found[rid]
            for code in [c for c, i in self.found_relay.items()
                        if now - i["seen"] > LOBBY_STALE_AFTER]:
                del self.found_relay[code]
            rooms = sorted(list(self.found.values()) + list(self.found_relay.values()),
                          key=lambda i: (i["host"].lower(), i["rid"]))
        self.render_rooms(rooms)
        self.root.after(700, self.search_tick)

    def render_rooms(self, rooms):
        sig = (self.search_problem, self.filter_on, tuple(
            (r["rid"], r["host"], r["n"], r["max"], r["banned"] or r["rid"] in self.banned_rids,
             r["kp"] > 0) for r in rooms))
        if sig == self.rooms_sig:
            return
        self.rooms_sig = sig
        for child in self.rooms_inner.winfo_children():
            child.destroy()
        if not rooms:
            msg = self.search_problem or ("Looking for rooms on your network...\n\n"
                                          "Make sure you and the host are on the same Wi-Fi. "
                                          "If Windows asks about the firewall, allow it.")
            tk.Label(self.rooms_inner, text=msg, font=FONT, bg=BG, fg=MUTED, wraplength=380,
                     justify="center").pack(pady=40, padx=20)
            return
        for r in rooms:
            relay = r.get("relay", False)
            banned = not relay and (r["banned"] or r["rid"] in self.banned_rids)
            full = r["n"] >= r["max"]
            card = tk.Frame(self.rooms_inner, bg=PANEL, padx=16, pady=12)
            card.pack(fill="x", padx=16, pady=(12, 0))
            host = self.mask(r["host"])
            # a relay room is only ever seen through a friend's own beacon in the first
            # place (it's encrypted to their key), so naming them here isn't telling
            # the person anything they don't already know - it's just saying which of
            # their friends' rooms this one is, same as the LAN list does for everyone.
            label = f"{host}'s room (internet)" if relay else f"{host}'s room"
            tk.Label(card, text=label, font=("Segoe UI", 12, "bold"), bg=PANEL,
                     fg=MUTED if banned else TEXT, anchor="w").pack(fill="x")
            tk.Label(card, text=f"{r['n']} of {r['max']} people", font=FONT_SMALL, bg=PANEL,
                     fg=MUTED, anchor="w").pack(fill="x")
            if relay:
                tk.Label(card, text="Hosted by a friend, over a public relay.",
                         font=FONT_SMALL, bg=PANEL, fg=MUTED, anchor="w").pack(fill="x")
            if banned:
                tk.Label(card, text="You are banned from this room.", font=FONT_SMALL,
                         bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(6, 0))
            elif full:
                tk.Label(card, text="This room is full.", font=FONT_SMALL, bg=PANEL,
                         fg=MUTED, anchor="w").pack(fill="x", pady=(6, 0))
            else:
                row = tk.Frame(card, bg=PANEL)
                row.pack(fill="x", pady=(10, 0))
                if relay:
                    make_button(row, "Join", GREEN, GREEN_HOVER,
                                lambda r=r: self.join_relay_from_search(r),
                                padx=16, pady=6).pack(side="left")
                else:
                    make_button(row, "Join", GREEN, GREEN_HOVER,
                                lambda r=r: self.join_from_search(r),
                                padx=16, pady=6).pack(side="left")
                    if r["kp"]:
                        make_button(row, "Request to join", ACCENT, ACCENT_HOVER,
                                    lambda r=r: self.request_from_search(r),
                                    padx=16, pady=6).pack(side="left", padx=(8, 0))

    def send_knock(self, room, kind, message="", extra=None):
        """A small unprotected note to the host: someone is trying to join / wants to join."""
        if not room["kp"]:
            return False
        note = {"app": APP_TAG, "rid": room["rid"], "t": kind, "nick": self.nickname,
                "msg": message}
        note.update(extra or {})
        data = json.dumps(note).encode("utf-8")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(data, (room["ip"], room["kp"]))
            return True
        except OSError:
            return False
        finally:
            sock.close()

    def join_from_search(self, room):
        values = self.ask_fields(
            "Join", f"Join {self.mask(room['host'])}'s room", "Type the room password.",
            [("Room password", "•", 40)], "Join", GREEN, GREEN_HOVER,
            validate=lambda v: None if v[0] else "Type the password first.")
        if not values:
            return
        self.send_knock(room, "try")
        self.join_room(room["ip"], values[0], self.nickname, rid=room["rid"], back="search")

    def join_relay_from_search(self, room):
        """Joining a friend's room found through search: the code and password came in
        their beacon, already meant only for us, so there is nothing left to type."""
        self.join_relay(room["code"], room["password"], self.nickname, back="search")

    def request_from_search(self, room):
        values = self.ask_fields(
            "Request to join", f"Ask {self.mask(room['host'])} to let you in",
            "The host sees your nickname and this message in their chat.",
            [("Your message", "", 120)], "Send request", ACCENT, ACCENT_HOVER,
            validate=lambda v: None if v[0] else "Write a short message for the host.")
        if not values:
            return
        # A one-time key lets the host send the password back so only we can read it.
        key = X25519PrivateKey.generate()
        reply = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            reply.bind(("", 0))
        except OSError:
            reply.close()
            self.search_note.config(text="Could not send the request.", fg=RED)
            return
        extra = {"pk": raw_public(key).hex(), "rp": reply.getsockname()[1]}
        if not self.send_knock(room, "ask", values[0], extra):
            reply.close()
            self.search_note.config(text="Could not send the request.", fg=RED)
            return
        if self.req_stop is not None:
            self.req_stop.set()                 # a newer request replaces an older one
        self.req_stop = threading.Event()
        self.req_room = room
        threading.Thread(target=self.wait_for_answer, args=(room, key, reply, self.req_stop),
                         daemon=True).start()
        self.search_note.config(
            text=f"Request sent. Waiting for {self.mask(room['host'])} to answer...",
            fg=STATE_COLORS["wait"])

    def wait_for_answer(self, room, key, sock, stop):
        """Waits (up to 5 minutes) for the host to accept or decline."""
        sock.settimeout(1.0)
        end = time.monotonic() + 300
        while not stop.is_set() and time.monotonic() < end:
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                d = json.loads(data.decode("utf-8"))
                if d.get("app") != APP_TAG or d.get("rid") != room["rid"] or addr[0] != room["ip"]:
                    continue
                if d["t"] == "no":
                    self.incoming.put((0, "reply", (room["rid"], "no", "")))
                    break
                if d["t"] == "ok":
                    shared = key.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(d["pk"])))
                    password = ChaCha20Poly1305(invite_key(shared, room["rid"])).decrypt(
                        bytes.fromhex(d["n"]), bytes.fromhex(d["ct"]),
                        room["rid"].encode("utf-8")).decode("utf-8")
                    self.incoming.put((0, "reply", (room["rid"], "ok", password)))
                    break
            except (ValueError, KeyError, TypeError, InvalidTag, UnicodeDecodeError):
                continue
        sock.close()

    def on_request_answer(self, rid, kind, password):
        room = self.req_room
        if room is None or room["rid"] != rid or self.search_stop is None:
            return                                   # we left the search screen meanwhile
        self.req_room = None
        host = self.mask(room["host"])
        if kind == "no":
            self.search_note.config(text=f"{host} declined your request.", fg=RED)
        else:
            self.search_note.config(text=f"{host} accepted you. Joining...",
                                    fg=STATE_COLORS["ok"])
            self.join_room(room["ip"], password, self.nickname, rid=rid, back="search")

    def add_request_card(self, req):
        """A request to join, in the host's chat, with Accept / Decline."""
        box = tk.Frame(self.msg_frame, bg=PANEL, padx=14, pady=10)
        box.pack(fill="x", padx=14, pady=(10, 2))
        text = tk.Label(box, font=FONT, bg=PANEL, fg=TEXT, anchor="w", justify="left",
                        wraplength=max(200, self.wrap_len() + 20))
        text.pack(fill="x")
        self.live(text, lambda mk: f'{mk(req["nick"])} ({req["ip"]}) wants to join:\n'
                                   f'"{mk(req["msg"])}"')
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x", pady=(8, 0))

        def answer(accept):
            for child in row.winfo_children():
                child.destroy()
            result = self.answer_request(req, accept)
            tk.Label(row, text=result, font=FONT_SMALL, bg=PANEL,
                     fg=STATE_COLORS["ok"] if accept and result.startswith("Accepted") else MUTED
                     ).pack(side="left")
        make_button(row, "Accept", GREEN, GREEN_HOVER, lambda: answer(True),
                    padx=14, pady=4).pack(side="left")
        make_button(row, "Decline", RED, RED_HOVER, lambda: answer(False),
                    padx=14, pady=4).pack(side="left", padx=(8, 0))
        self.scroll_to_bottom()

    def answer_request(self, req, accept):
        """Sends the answer to the person who asked. Returns a line to show the host."""
        room = self.room
        if room is None:
            return "The room is closed."
        if req["ip"] in room.banned:
            return "That person is banned."
        reply = {"app": APP_TAG, "rid": room.rid, "t": "no"}
        if accept:
            if len(room.members) + 1 >= room.max_people:
                return "The room is full."
            ours = X25519PrivateKey.generate()
            shared = ours.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(req["pk"])))
            nonce = os.urandom(12)
            sealed = ChaCha20Poly1305(invite_key(shared, room.rid)).encrypt(
                nonce, room.password.encode("utf-8"), room.rid.encode("utf-8"))
            reply.update({"t": "ok", "pk": raw_public(ours).hex(), "n": nonce.hex(),
                          "ct": sealed.hex()})
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(json.dumps(reply).encode("utf-8"), (req["ip"], req["rp"]))
        except OSError:
            return "Could not reach them."
        finally:
            sock.close()
        return f"Accepted: {req['nick']} can join now." if accept else "Declined."

    def join_by_ip(self):
        values = self.ask_fields(
            "Join by IP", "Join by IP address", "For a host that is hidden or on another network.",
            [("Host IP address", "", 60), ("Room password", "•", 40)], "Join", GREEN, GREEN_HOVER,
            paste=True,
            validate=lambda v: None if (v[0] and v[1]) else "Fill in both boxes.")
        if values:
            self.join_room(values[0], values[1], self.nickname, back="search")

    def join_by_relay(self):
        if mqtt_lib is None:
            self.search_note.config(
                text="This needs the paho-mqtt package. Go to Settings > Packages to install "
                    "it, then try again.")
            return
        values = self.ask_fields(
            "Join using a code", "Join using a code",
            "For a room hosted over the internet relay instead of a network. The relay can see "
            "that this room exists and roughly when it's used, but not what is said in it.",
            [("Room code", "", 60), ("Room password", "•", 40)], "Join", GREEN, GREEN_HOVER,
            paste=True,
            validate=lambda v: None if (v[0] and v[1]) else "Fill in both boxes.")
        if values:
            self.join_relay(values[0].strip(), values[1], self.nickname, back="search")

    def join_relay(self, code, password, nickname, back=None):
        nickname = clean_nickname(nickname)
        self.nickname = nickname
        self.return_to = back
        self.joining_rid = None
        self.session += 1
        self.is_host = False
        self.joined = False
        self.relay = True
        self.my_id = None
        self.show_chat(f"Connecting through the relay...", "wait", relay=True)
        self.add_line(f"Connecting to room {code} through the internet relay as {nickname}...")
        threading.Thread(target=self.connect_to_relay,
                         args=(self.session, code, password, nickname), daemon=True).start()

    def connect_to_relay(self, session, code, password, nickname):
        if mqtt_lib is None:
            self.post(session, "failed", "This needs the paho-mqtt package.")
            return
        connid = secrets.token_hex(8)
        client = mqtt_client("ipchat-g-" + connid)
        my_topic = RELAY_PREFIX + "r/" + code + "/h/" + connid
        their_topic = RELAY_PREFIX + "r/" + code + "/g/" + connid
        pipe = MqttPipe(client, my_topic, their_topic)
        ready, result = threading.Event(), {"ok": False, "error": None}

        def on_connect(c, u, flags, rc, props=None):
            if rc == 0:
                c.subscribe(my_topic, qos=1)
                result["ok"] = True
            else:
                result["error"] = f"the relay refused the connection ({rc})"
            ready.set()

        def on_message(c, u, m):
            pipe.feed(m.payload)

        def on_disconnect(c, u, *a):
            pipe.close()
        client.on_connect, client.on_message, client.on_disconnect = \
            on_connect, on_message, on_disconnect
        try:
            client.connect(RELAY_HOST, RELAY_PORT, 60)
            client.loop_start()
        except OSError as e:
            self.post(session, "failed", f"Could not reach the relay: {e}")
            return
        if not ready.wait(15) or not result["ok"]:
            client.loop_stop()
            self.post(session, "failed", result["error"] or
                      "Could not reach the relay (timed out). Check your internet connection.")
            return
        self.conn_sock = pipe

        try:
            chan, _host_name = handshake(pipe, password, False, nickname, identity=self.identity)
        except HandshakeError:
            pipe.close()
            client.loop_stop()
            self.post(session, "failed",
                      "Could not join: wrong code, wrong password, or the host is busy. Try again.")
            return
        if session != self.session:
            chan.close()
            client.loop_stop()
            return

        self.channel = chan
        chan.sock.settimeout(1.5)   # wake guest_loop regularly to check the host is still there
        threading.Thread(target=self.ping_loop, args=(chan,), daemon=True).start()
        ended = self.guest_loop(session, chan)
        if self.channel is chan:
            self.channel = None
        chan.close()
        client.loop_stop()
        try:
            client.disconnect()
        except Exception:
            pass
        if ended is HANDLED:
            return
        self.post(session, "lost", ended)

    def join_room(self, ip, password, nickname, rid=None, back=None):
        nickname = clean_nickname(nickname)
        self.nickname = nickname
        self.return_to = back
        self.joining_rid = rid
        self.session += 1
        self.is_host = False
        self.joined = False
        self.relay = False
        self.my_id = None
        self.show_chat(f"Connecting to {ip}...", "wait")
        self.add_line(f"Connecting to {ip}:{PORT} as {nickname}...")
        threading.Thread(target=self.connect_to_host,
                         args=(self.session, ip, password, nickname), daemon=True).start()

    def connect_to_host(self, session, ip, password, nickname):
        self._joined_via_loopback = ip in my_lan_ips()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            s.connect((ip, PORT))
        except OSError as e:
            s.close()
            self.post(session, "failed", f"Could not connect: {e}")
            return
        enable_tcp_keepalive(s)
        self.conn_sock = s

        try:
            chan, _host_name = handshake(s, password, False, nickname, identity=self.identity)
        except HandshakeError:
            s.close()
            self.post(session, "failed", "Could not join: wrong password, or the host is busy. Try again.")
            return
        if session != self.session:
            chan.close()
            return

        self.channel = chan
        ended = self.guest_loop(session, chan)
        if self.channel is chan:
            self.channel = None
        chan.close()
        if ended is HANDLED:
            return
        self.post(session, "lost", ended)

    def guest_loop(self, session, chan):
        """Handles everything the host sends us. Returns why the connection ended
        (a text from the host) or None when it simply dropped."""
        joined, reason = False, None
        last_seen = time.monotonic()
        while True:
            try:
                kind, payload = chan.recv()
            except TimeoutError:
                # only happens over the relay (see connect_to_relay) - no data showed up
                # in time, which is normal; only act once the host has truly gone quiet
                if self.relay and time.monotonic() - last_seen > RELAY_PING_TIMEOUT:
                    return "Lost the connection to the host."
                continue
            except (OSError, InvalidTag, ValueError):  # closed connection, or tampered data
                return reason
            last_seen = time.monotonic()
            try:
                if kind == K_PING:
                    pass  # just a liveness signal - last_seen was already refreshed above
                elif kind == K_TYPING:
                    if len(payload) >= 2:
                        (pid,) = struct.unpack(">H", payload[:2])
                        self.post(session, "typing", pid)
                elif kind == K_MSG:
                    d = json.loads(payload.decode("utf-8"))
                    self.post(session, "msg", (str(d["n"])[:NICK_MAX + 6],
                                               str(d["t"])[:MAX_MESSAGE_CHARS]))
                elif kind == K_SYS:
                    self.post(session, "sys", payload.decode("utf-8", errors="replace")[:300])
                elif kind == K_ROSTER:
                    joined = True
                    self.post(session, "roster", json.loads(payload.decode("utf-8")))
                elif kind == K_BYE:
                    reason = payload.decode("utf-8", errors="replace")[:200]
                    if not joined:  # turned away at the door (e.g. the room is full)
                        self.post(session, "failed", reason)
                        return HANDLED
                    return reason  # kicked/banned/host closed the room - end now,
                    # rather than waiting for the socket to show the connection died
                    # (over a relay, closing one side never surfaces on the other)
                elif kind in FILE_KINDS:
                    (pid,) = struct.unpack(">H", payload[:2])
                    self.handle_file_frame(session, pid, kind, payload[2:])
                elif kind == K_FRIEND:
                    (pid,) = struct.unpack(">H", payload[:2])
                    if len(payload) <= 4098:
                        self.post(session, "friend", (pid, payload[2:]))
            except (ValueError, KeyError, TypeError, struct.error):
                continue  # malformed message from the host: ignore it

    def handle_file_frame(self, session, pid, kind, body):
        """A file message from person `pid` (for us), from either kind of connection."""
        if kind == K_OFFER:
            self.post(session, "file", ("offer", pid, None, json.loads(body.decode("utf-8"))))
        elif kind == K_CHUNK:
            self.receive_chunk(session, pid, body)
        elif kind == K_END:
            self.receive_end(session, pid, body)
        elif kind == K_DONE:
            (tid,) = struct.unpack(">I", body[:4])
            self.post(session, "file", ("delivered", pid, tid, body[4:5] == b"\x01"))
        elif kind in (K_ACCEPT, K_REJECT, K_ABORT):
            (tid,) = struct.unpack(">I", body[:4])
            event = {K_ACCEPT: "accepted", K_REJECT: "rejected", K_ABORT: "peer_abort"}[kind]
            self.post(session, "file", (event, pid, tid, None))

    # ---------- events from the network threads (GUI thread) ----------
    def process_queue(self):
        # Network threads can't touch the GUI directly, so they post here instead.
        try:
            while True:
                session, kind, value = self.incoming.get_nowait()
                if kind == "pkg":
                    self.on_package_done(*value)
                    continue
                if kind == "update":
                    self.on_update_event(*value)
                    continue
                if kind == "reply":
                    self.on_request_answer(*value)
                    continue
                if session != self.session:
                    continue  # leftover from an old connection
                if kind == "msg":
                    name, text = value
                    self.add_bubble(text, mine=False, name=name)
                elif kind == "sys":
                    self.add_line(value)
                elif kind == "request":
                    self.add_request_card(value)
                elif kind == "friend":
                    self.on_friend(*value)
                elif kind == "roster":
                    self.on_roster(value)
                elif kind == "typing":
                    self.on_typing_event(value)
                elif kind == "lost":
                    self.on_lost(value)
                elif kind == "file":
                    self.on_file_event(*value)
                elif kind == "failed":
                    back, rid = self.return_to, self.joining_rid
                    self.disconnect()
                    if back == "search":
                        if "banned" in value.lower() and rid:
                            self.banned_rids.add(rid)
                        self.open_search(value)
                    else:
                        self.menu_error.config(text=value)
        except queue.Empty:
            pass
        self.root.after(100, self.process_queue)

    def on_roster(self, data):
        """The list of people in the room changed."""
        try:
            me, mx = int(data["you"]), int(data["max"])
            people = [(int(p["id"]), str(p["name"])[:NICK_MAX + 6])
                      for p in data["people"][:MAX_ROOM_PEOPLE]]
        except (KeyError, TypeError, ValueError):
            return
        old = dict(self.names)
        self.my_id = me
        ids = {}
        for p in data["people"][:MAX_ROOM_PEOPLE]:       # keep only identities that check out
            try:
                pid, uid, pk = int(p["id"]), p.get("uid"), p.get("pk")
                if uid and pk and len(pk) == 64 and uid == uid_from_pub(bytes.fromhex(pk)):
                    ids[pid] = (uid, pk)
            except (KeyError, TypeError, ValueError):
                continue
        host_proof = getattr(self.channel, "peer_identity", None) if not self.is_host else None
        if host_proof:
            ids[HOST_ID] = host_proof                    # we checked the host ourselves
        elif not self.is_host:
            ids.pop(HOST_ID, None)
        if self.is_host and self.identity:
            ids[HOST_ID] = (self.identity.uid, self.identity.pub_hex)
        self.peer_ids = ids
        for pid in ids:
            f = self.friend_of(pid)
            if f is not None and not f.get("xpk") and pid not in self._xpk_asked:
                self._xpk_asked.add(pid)
                self.refresh_friend_key(pid)
            elif f is None and pid not in self._test_tried and self.is_test_peer(pid):
                self._test_tried.add(pid)
                self.try_auto_test_friend(pid)
        for table in (self.friend_out, self.friend_in, self.friend_wait):
            for pid in [k for k in table if k not in ids]:
                del table[pid]
        self.set_people(people, max(2, min(MAX_ROOM_PEOPLE, mx)))
        for pid, name in old.items():
            if pid not in self.names:
                self.on_peer_gone(pid, name)

        n = len(people)
        if self.is_host:
            if n <= 1:
                self.set_status("Waiting for someone to join...", "wait")
            else:
                self.set_status(f"{n} of {self.max_people} people in the room", "ok")
        else:
            if not self.joined:
                self.joined = True
                self.add_line(f"Connected to {self.name_of(HOST_ID)}'s room. "
                              "Messages are encrypted.")
            self.set_status(f"Connected · {n} of {self.max_people} people", "ok")

    def on_lost(self, reason):
        """A guest lost the connection to the host."""
        low = (reason or "").lower()
        if self.relay and ("went quiet" in low or "lost the connection to the host" in low):
            # the relay heartbeat caught a silent/dead connection - go straight back to
            # the search page (same place as a failed join), not just a status message
            self.disconnect()
            self.open_search(reason, bad=True)
            return
        self.on_transfers_interrupted()
        self.set_people([], self.max_people)
        self.set_status("You were banned" if "banned" in low else
                        "You were kicked" if "kicked" in low else
                        "Room closed" if reason else "Connection lost", "bad")
        self.add_line(reason or "Connection lost.")

    # ---------- sending messages ----------
    # ---------- "... is typing" indicator ----------
    def on_typing(self, event=None):
        """Tells whoever we're chatting with that we're typing - throttled to once every
        few seconds (see TYPING_SEND_INTERVAL), and only while there's actually text in
        the box."""
        if not self.entry.get("1.0", "end-1c").strip():
            return
        now = time.monotonic()
        if now - self._last_typing_sent < TYPING_SEND_INTERVAL:
            return
        if self.is_host:
            room = self.room
            if room is not None and room.others():
                self._last_typing_sent = now
                room.send_all(K_TYPING, struct.pack(">H", HOST_ID))
        elif self.joined:
            chan = self.channel
            if chan is not None:
                self._last_typing_sent = now
                try:
                    chan.send(K_TYPING, b"")
                except OSError:
                    pass

    def on_typing_event(self, pid):
        """Somebody (identified by their roster id) just told us they're typing."""
        if pid == self.my_id or pid not in self.names:
            return
        self.typing[pid] = time.monotonic() + TYPING_EXPIRE
        self.update_typing_label()

    def typing_tick(self):
        """Runs continuously: expires stale "is typing" entries and animates the dots
        in front of whichever lines are currently showing."""
        now = time.monotonic()
        had_any = bool(self.typing)
        self.typing = {pid: exp for pid, exp in self.typing.items() if exp > now}
        if self.typing or had_any:
            self._typing_frame = (self._typing_frame + 1) % len(TYPING_DOT_FRAMES)
            self.update_typing_label()
        self.root.after(TYPING_TICK_MS, self.typing_tick)

    def update_typing_label(self):
        label = getattr(self, "typing_label", None)
        if label is None:
            return
        names = [self.name_of(pid) for pid in self.typing]
        dots = TYPING_DOT_FRAMES[self._typing_frame]
        if not names:
            label.config(text="")
        elif len(names) >= 4:
            label.config(text=f"{dots} Multiple people are typing...")
        else:
            label.config(text="\n".join(f"{dots} {n} is typing..." for n in names))

    def convert_emoji(self, event=None):
        """When a shortcode like :sob: has just been typed, swap it for the emoji."""
        if event is not None and event.char != ":":
            return
        before = self.entry.get("insert linestart", "insert")
        m = re.search(r":[A-Za-z0-9_+\-]{1,40}:$", before)
        if not m:
            return
        new = emojize(m.group(0))
        if new != m.group(0):
            self.entry.delete(f"insert-{len(m.group(0))}c", "insert")
            self.entry.insert("insert", new)

    def insert_newline(self, event=None):
        self.entry.insert("insert", "\n")
        return "break"  # stop Tk from also treating this as a plain Enter

    def send_message(self, event=None):
        text = emojize(self.entry.get("1.0", "end-1c").strip())
        if text:
            if len(text) > MAX_MESSAGE_CHARS:
                self.add_line(f"Message too long (max {MAX_MESSAGE_CHARS} characters).")
            elif self.is_host:
                room = self.room
                if room is None or not room.others():
                    self.add_line("Nobody has joined yet.")
                else:
                    msg = json.dumps({"n": room.host_name, "t": text}).encode("utf-8")
                    room.send_all(K_MSG, msg)
                    self.add_bubble(text, mine=True)
                    self.entry.delete("1.0", "end")
            else:
                chan = self.channel
                if chan is None or not self.joined:
                    self.add_line("You are not connected to a room.")
                else:
                    try:
                        chan.send_text(text)
                    except OSError:
                        self.add_line("Failed to send message.")
                    else:
                        self.add_bubble(text, mine=True)
                        self.entry.delete("1.0", "end")
        return "break"  # stops Enter from also adding a newline to the box

    # ---------- file cards (how a transfer looks in the chat) ----------
    def add_file_card(self, t, mine, name="Someone", to=None):
        bg = BUBBLE_ME if mine else BUBBLE_FRIEND
        row = tk.Frame(self.msg_frame, bg=BG)
        row.pack(fill="x", padx=10, pady=(6, 0))
        col = tk.Frame(row, bg=BG)
        col.pack(side="right" if mine else "left")
        panel = RoundedPanel(col, bg=bg, radius=12, padx=12, pady=10)
        panel.pack(anchor="e" if mine else "w")
        card = panel.content

        tk.Label(card, text=t.name, font=FONT_BOLD, bg=bg, fg="white", wraplength=CARD_W,
                 justify="left", anchor="w").pack(anchor="w")
        tk.Label(card, text=human_size(t.size), font=FONT_SMALL, bg=bg,
                 fg="#cbd5e1").pack(anchor="w", pady=(0, 6))
        if not mine and os.path.splitext(t.name)[1].lower() in RISKY_EXTENSIONS:
            tk.Label(card, text=f"⚠ This is a program. Only accept it if you trust {name}.",
                     font=FONT_SMALL, bg=bg, fg="#fbbf24", wraplength=CARD_W,
                     justify="left", anchor="w").pack(anchor="w", pady=(0, 6))
        t.bar = tk.Canvas(card, width=CARD_W, height=6, highlightthickness=0,
                          bg=mix(bg, "#000000", 0.35))
        t.bar.pack(anchor="w")
        t.status_lbl = tk.Label(card, text="", font=FONT_SMALL, bg=bg, fg="#e2e8f0",
                                wraplength=CARD_W, justify="left", anchor="w")
        t.status_lbl.pack(anchor="w", pady=(6, 0))
        t.btn_row = tk.Frame(card, bg=bg)

        who = f"You → {to}" if (mine and to) else ("You" if mine else name)
        stamp = time.strftime("%H:%M")
        meta = tk.Label(col, font=FONT_SMALL, bg=BG, fg=MUTED)
        meta.pack(anchor="e" if mine else "w", pady=(1, 0))
        self.live(meta, lambda mk: f"{mk(who)} · {stamp}")

    def draw_bar(self, t, color="#e2e8f0"):
        t.bar.delete("all")
        t.bar.create_rectangle(0, 0, int(CARD_W * max(0.0, min(1.0, t.frac))), 6,
                               fill=color, outline="")

    def set_progress(self, t, text):
        """Cheap update while data is flowing (no buttons are rebuilt)."""
        t.status_lbl.config(text=text)
        self.draw_bar(t)

    def set_card(self, t, text, buttons=(), color="#e2e8f0"):
        t.status_lbl.config(text=text)
        self.draw_bar(t, color)
        for w in t.btn_row.winfo_children():
            w.destroy()
        t.btn_row.pack_forget()
        if buttons:
            for label, bg, hover, command in buttons:
                make_button(t.btn_row, label, bg, hover, command, padx=12, pady=4,
                            font=FONT_SMALL).pack(side="left", padx=(0, 6))
            t.btn_row.pack(anchor="w", pady=(8, 0))
        self.scroll_to_bottom()

    def finish_card(self, t, state, text, buttons=()):
        t.state = state
        color = {"done": STATE_COLORS["ok"], "failed": STATE_COLORS["bad"]}.get(state, MUTED)
        self.set_card(t, text, buttons, color)

    @staticmethod
    def progress_text(verb, t, done):
        return f"{verb}... {int(t.frac * 100)}%  ·  {human_size(done)} of {human_size(t.size)}"

    # ---------- sending file messages to one person ----------
    def send_file_frame(self, pid, kind, payload, bulk=False):
        """Sends a file message to person `pid`. Raises OSError if they are gone.
        As a guest everything goes via the host, which passes it on."""
        if self.is_host:
            room = self.room
            member = room.get(pid) if room is not None else None
            if member is None:
                raise OSError("that person left the room")
            member.chan.send(kind, struct.pack(">H", HOST_ID) + payload, bulk)
        else:
            chan = self.channel
            if chan is None:
                raise OSError("not connected")
            chan.send(kind, struct.pack(">H", pid) + payload, bulk)

    def send_control(self, pid, kind, tid):
        try:
            self.send_file_frame(pid, kind, struct.pack(">I", tid))
            return True
        except OSError:
            return False

    # ---------- sending a file ----------
    def attach_file(self):
        others = [(pid, name) for pid, name in self.people if pid != self.my_id]
        if not self.joined or not others:
            self.add_line("There is nobody here to send a file to yet.")
            return

        if len(others) == 1:
            pids = [others[0][0]]
        else:
            pids = self.ask_recipients(others)
            if not pids:
                return

        busy = [p for p in pids if self.tx.get(p) is not None and
               self.tx[p].state in ("waiting", "active", "finishing")]
        if busy:
            self.add_line("Already sending a file to " +
                          ", ".join(self.name_of(p) for p in busy) +
                          " - wait until that finishes.")
            pids = [p for p in pids if p not in busy]
            if not pids:
                return

        title = f"Send a file to {self.name_of(pids[0])}" if len(pids) == 1 else \
            f"Send a file to {len(pids)} people"
        path = filedialog.askopenfilename(parent=self.root, title=title)
        if not path:
            return
        try:
            size = os.path.getsize(path)
        except OSError as e:
            self.add_line(f"Can't read that file: {e}")
            return
        if size == 0:
            self.add_line("That file is empty.")
            return
        if size > MAX_FILE_BYTES:
            self.add_line(f"That file is too big. The maximum is "
                          f"{MAX_FILE_BYTES // (1024 * 1024)} MB.")
            return

        for pid in pids:
            if pid not in self.names:
                self.add_line(f"{self.name_of(pid)} left the room.")
                continue
            t = FileTransfer(secrets.randbits(32), os.path.basename(path), size, True,
                             path, peer=pid)
            self.tx[pid] = t
            self.add_file_card(t, mine=True, to=self.name_of(pid))
            self.set_card(t, f"Waiting for {self.name_of(pid)} to accept...",
                          [("Cancel", RED, RED_HOVER, lambda t=t: self.cancel_send(t))])
            offer = json.dumps({"id": t.id, "name": t.name, "size": t.size}).encode("utf-8")
            try:
                self.send_file_frame(pid, K_OFFER, offer)
            except OSError:
                self.finish_card(t, "failed", "Could not send the request.")

    def cancel_send(self, t):
        if t.state not in ("waiting", "active"):
            return
        t.cancel.set()
        self.send_control(t.peer, K_ABORT, t.id)
        self.finish_card(t, "cancelled", "Cancelled.")

    def send_file_thread(self, session, t):
        tid = struct.pack(">I", t.id)
        digest = hashlib.sha256()
        sent, last = 0, 0.0
        try:
            with open(t.path, "rb") as f:
                while not t.cancel.is_set():
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
                    self.send_file_frame(t.peer, K_CHUNK, tid + chunk, bulk=True)
                    sent += len(chunk)
                    now = time.monotonic()
                    if now - last > 0.1:
                        last = now
                        self.post(session, "file", ("tx_progress", t.peer, t.id, sent))
            if t.cancel.is_set():
                return
            if sent != t.size:  # the file changed while it was being sent
                self.send_file_frame(t.peer, K_ABORT, tid)
                self.post(session, "file",
                          ("tx_failed", t.peer, t.id, "The file changed while it was being sent."))
                return
            self.send_file_frame(t.peer, K_END, tid + digest.digest())
            self.post(session, "file", ("tx_sent", t.peer, t.id, None))
        except OSError as e:
            if not t.cancel.is_set():
                self.post(session, "file", ("tx_failed", t.peer, t.id, f"Sending stopped: {e}"))

    # ---------- receiving a file ----------
    def on_offer(self, pid, info):
        peer = self.name_of(pid)
        try:
            tid, size = int(info["id"]), int(info["size"])
            name = safe_filename(str(info["name"]))
        except (KeyError, TypeError, ValueError):
            return
        if not 0 <= tid < 2 ** 32:
            return

        refused = None
        if not 0 < size <= MAX_FILE_BYTES:
            refused = "it is empty or too big"
        elif self.rx is not None and self.rx.state in ("offered", "active"):
            refused = "another file is still in progress"
        if refused:
            self.add_line(f"{peer} tried to send you a file, but it was refused: {refused}.")
            self.send_control(pid, K_REJECT, tid)
            return

        t = FileTransfer(tid, name, size, False, peer=pid)
        self.rx = t
        self.add_file_card(t, mine=False, name=peer)
        self.set_card(t, f"{peer} wants to send you this file.", [
            ("Accept", GREEN, GREEN_HOVER, lambda: self.accept_file(t)),
            ("Decline", BG, INPUT, lambda: self.decline_file(t))])

    def accept_file(self, t):
        error = None
        with t.lock:
            if t.state != "offered":
                return
            try:
                folder = download_dir()
                os.makedirs(folder, exist_ok=True)
                t.path = unique_path(folder, t.name)
                t.part = t.path + ".part"
                t.file = open(t.part, "wb")
            except OSError as e:
                error = e
                t.state = "failed"
            else:
                t.state = "active"
        if error:
            self.send_control(t.peer, K_REJECT, t.id)
            self.finish_card(t, "failed", f"Can't save the file: {error}")
            return
        if not self.send_control(t.peer, K_ACCEPT, t.id):
            self.discard_partial(t)
            self.finish_card(t, "failed", f"{self.name_of(t.peer)} is no longer here.")
            return
        self.set_card(t, "Receiving... 0%",
                      [("Cancel", RED, RED_HOVER, lambda: self.cancel_receive(t))])

    def decline_file(self, t):
        with t.lock:
            if t.state != "offered":
                return
            t.state = "rejected"
        self.send_control(t.peer, K_REJECT, t.id)
        self.finish_card(t, "rejected", "Declined.")

    def cancel_receive(self, t):
        if t.state != "active":
            return
        self.discard_partial(t)
        self.send_control(t.peer, K_REJECT, t.id)
        self.finish_card(t, "cancelled", "Cancelled.")

    def discard_partial(self, t):
        """Closes and deletes a half-received file."""
        with t.lock:
            if t.file is not None:
                try:
                    t.file.close()
                except OSError:
                    pass
                t.file = None
            if t.part and t.state != "done":
                try:
                    os.remove(t.part)
                except OSError:
                    pass
            if t.state in ("offered", "active"):
                t.state = "cancelled"

    def receive_chunk(self, session, pid, body):
        """Runs in a network thread: writes one piece of the file to disk."""
        (tid,) = struct.unpack(">I", body[:4])
        data = body[4:]
        t = self.rx
        if t is None or t.id != tid or t.peer != pid:
            return
        problem = None
        with t.lock:
            if t.state != "active" or t.file is None:
                return  # cancelled in the meantime: drop the piece
            if t.done + len(data) > t.size:
                problem = "The file is bigger than announced."
            else:
                try:
                    t.file.write(data)
                except OSError as e:
                    problem = f"Can't write to disk: {e}"
                else:
                    t.hash.update(data)
                    t.done += len(data)
        if problem:
            self.fail_receive(session, t, problem)
            return
        now = time.monotonic()
        if now - t.last_post > 0.1:
            t.last_post = now
            self.post(session, "file", ("rx_progress", pid, t.id, t.done))

    def receive_end(self, session, pid, body):
        """Runs in a network thread: checks the finished file and saves it."""
        (tid,) = struct.unpack(">I", body[:4])
        digest = body[4:36]
        t = self.rx
        if t is None or t.id != tid or t.peer != pid:
            return
        reason = None
        with t.lock:
            if t.state != "active" or t.file is None:
                return
            try:
                t.file.close()
            except OSError:
                pass
            t.file = None
            if t.done != t.size or digest != t.hash.digest():
                reason = "The file arrived incomplete or damaged."
            else:
                try:
                    final = t.path
                    if os.path.exists(final):
                        final = unique_path(os.path.dirname(final), t.name)
                    os.replace(t.part, final)
                    t.path = final
                except OSError as e:
                    reason = f"Can't save the file: {e}"
            if reason is None:
                t.state = "done"
        if reason:
            self.fail_receive(session, t, reason, finished=True)
            return
        try:
            self.send_file_frame(pid, K_DONE, struct.pack(">I", t.id) + b"\x01")  # saved
        except OSError:
            pass
        self.post(session, "file", ("rx_done", pid, t.id, None))

    def fail_receive(self, session, t, reason, finished=False):
        """The incoming file can't be completed: clean up and tell the sender."""
        self.discard_partial(t)
        t.state = "failed"
        try:
            if finished:  # everything arrived, but it can't be used
                self.send_file_frame(t.peer, K_DONE, struct.pack(">I", t.id) + b"\x00")
            else:         # stopped halfway: sender should stop sending
                self.send_file_frame(t.peer, K_REJECT, struct.pack(">I", t.id))
        except OSError:
            pass
        self.post(session, "file", ("rx_failed", t.peer, t.id, reason))

    # ---------- reacting to transfer events (GUI thread) ----------
    def on_file_event(self, event, pid, tid, data):
        if event == "offer":
            self.on_offer(pid, data)
        elif event in ("accepted", "rejected", "tx_progress", "tx_sent", "tx_failed", "delivered"):
            t = self.tx.get(pid)
            if t is not None and t.id == tid and t.peer == pid:
                self.on_tx_event(t, event, data)
        elif event in ("rx_progress", "rx_done", "rx_failed", "peer_abort"):
            t = self.rx
            if t is not None and t.id == tid and t.peer == pid:
                self.on_rx_event(t, event, data)

    def on_tx_event(self, t, event, data):
        peer = self.name_of(t.peer)
        cancel_btn = [("Cancel", RED, RED_HOVER, lambda: self.cancel_send(t))]
        if event == "accepted" and t.state == "waiting":
            t.state = "active"
            self.set_card(t, "Sending... 0%", cancel_btn)
            threading.Thread(target=self.send_file_thread, args=(self.session, t),
                             daemon=True).start()
        elif event == "rejected" and t.state in ("waiting", "active", "finishing"):
            t.cancel.set()
            self.finish_card(t, "rejected", f"{peer} declined." if t.state == "waiting"
                             else f"{peer} stopped the transfer.")
        elif event == "tx_progress" and t.state == "active":
            t.frac = data / t.size
            self.set_progress(t, self.progress_text("Sending", t, data))
        elif event == "tx_sent" and t.state == "active":
            t.state, t.frac = "finishing", 1.0
            self.set_card(t, f"Sent. Waiting for {peer} to confirm...")
        elif event == "tx_failed" and t.state in ("active", "finishing"):
            self.finish_card(t, "failed", data)
        elif event == "delivered" and t.state in ("active", "finishing"):
            t.frac = 1.0
            if data:
                self.finish_card(t, "done", f"Delivered to {peer} ✓")
            else:
                self.finish_card(t, "failed",
                                 f"{peer} got the file, but it was damaged or could not be saved.")

    def on_rx_event(self, t, event, data):
        peer = self.name_of(t.peer)
        if event == "rx_progress" and t.state == "active":
            t.frac = data / t.size
            self.set_progress(t, self.progress_text("Receiving", t, data))
        elif event == "rx_done":
            t.frac = 1.0
            self.finish_card(t, "done", f"Saved in {os.path.dirname(t.path)}",
                             [("Show in folder", BG, INPUT, lambda: reveal_in_folder(t.path))])
        elif event == "rx_failed":
            self.finish_card(t, "failed", data)
        elif event == "peer_abort" and t.state in ("offered", "active"):
            self.discard_partial(t)
            self.finish_card(t, "cancelled", f"{peer} cancelled the transfer.")

    def on_peer_gone(self, pid, name):
        """Somebody left the room: stop any transfer with them."""
        if self.typing.pop(pid, None) is not None:
            self.update_typing_label()
        for t in (*self.tx.values(), self.rx):
            if t is not None and t.peer == pid and \
                    t.state in ("waiting", "offered", "active", "finishing"):
                if t.outgoing:
                    t.cancel.set()
                else:
                    self.discard_partial(t)
                self.finish_card(t, "failed", f"{name} left the room.")

    def on_transfers_interrupted(self):
        for t in (*self.tx.values(), self.rx):
            if t is not None and t.state in ("waiting", "offered", "active", "finishing"):
                if t.outgoing:
                    t.cancel.set()
                else:
                    self.discard_partial(t)
                self.finish_card(t, "failed", "Connection lost.")

    def cleanup_transfers(self):
        for t in self.tx.values():
            t.cancel.set()
        if self.rx is not None:
            self.discard_partial(self.rx)
        self.tx, self.rx = {}, None

    # ---------- closing things down ----------
    def close_room(self, room):
        """Closes the room: everybody gets a goodbye, then the connections end."""
        with room.lock:
            room.closed = True
            members = list(room.members.values())
            room.members.clear()
            pending = list(room.pending)
            room.pending.clear()
        for s in (room.server_sock, *pending):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass
        for m in members:
            try:
                m.chan.send(K_BYE, "The host closed the room.".encode("utf-8"))
            except OSError:
                pass
            m.chan.close(flush=True)

    def close_connections(self):
        room, self.room = self.room, None
        if room is not None:
            self.close_room(room)
        chan, self.channel = self.channel, None
        if chan is not None:
            try:
                chan.send(K_LEAVE, b"")
            except OSError:
                pass
            chan.close(flush=True)       # closes the same socket, but only once the
            self.conn_sock = None         # goodbye above has actually gone out
        sock, self.conn_sock = self.conn_sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def disconnect(self):
        self.session += 1
        self.cleanup_transfers()
        self.close_connections()
        self.is_host = False
        self.joined = False
        self.relay = False
        self.my_id = None
        self.set_people([], DEFAULT_ROOM_PEOPLE)
        self.peer_ids = {}
        self.friend_out, self.friend_in, self.friend_wait = {}, {}, {}
        self._xpk_asked = set()
        self.test_friends = {}
        self._test_tried = set()
        self._loopback_peers = set()
        self._joined_via_loopback = False
        self.open_person = None
        self.typing = {}
        self.update_typing_label()
        self.show_menu()

    def quit(self):
        self.stop_search()
        self.cleanup_transfers()
        self.close_connections()
        self.root.destroy()


if __name__ == "__main__":
    if ensure_installed():
        sys.exit(0)   # relaunching the installed copy - never show a window for this one

    if ARG_ALLOW_MULTIPLE not in sys.argv[1:]:
        if not acquire_single_instance_lock(steal=ARG_RELAUNCH in sys.argv[1:]):
            try:
                _r = tk.Tk(); _r.withdraw()
                messagebox.showinfo("IP Chat", "IP Chat is already running.")
                _r.destroy()
            except Exception:
                pass
            sys.exit(0)
        atexit.register(release_single_instance_lock)

    root = tk.Tk()
    _crash_root = root
    root.report_callback_exception = _report_tk_callback_exception
    _poll_crash_queue()
    app = ChatApp(root)
    root.after(250, app.startup)
    minimize_console()
    # make sure the chat window (not the console) is the one in front
    root.lift()
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.focus_force()
    root.mainloop()