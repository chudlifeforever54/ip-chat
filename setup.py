"""
IP Chat - Setup

Run this once (double-click it, or "python setup.py" / "pythonw setup.py") to get
IP Chat ready to use: it fetches the current script and its icon straight from
GitHub, builds the "IPChat" folder the program lives in (in AppData, the normal
place for this sort of thing), puts the script and icon there, builds the
"IP Chat.lnk" shortcut using that icon, and then opens the program for you.

This is a standalone installer - it does not need ip-chat.py to already exist
anywhere on this computer, and it is not itself the chat program.

If AppData can't be created or written to (locked-down permissions, an unusual
account setup, whatever stopped it), this falls back to the Documents folder
instead, under a folder called "IPChat Code" (deliberately a different name from
the "IPChat" folder the installed program itself manages - this is just the
one-time setup tool's own fallback). Once installed, the program takes over its
own upkeep (updates, re-creating its shortcut, etc.) from inside itself.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

UPDATE_REPO_OWNER = "chudlifeforever54"
UPDATE_REPO_NAME = "ip-chat"
UPDATE_FILE_RE = re.compile(r"^ip-chat(\d+(?:\.\d+){1,2})\.py$", re.IGNORECASE)
ICON_URL = ("https://raw.githubusercontent.com/chudlifeforever54/ip-chat"
            "/refs/heads/main/iPC.ico")
HTTP_TIMEOUT = 20
CREATE_NO_WINDOW = 0x08000000


def parse_version(text):
    parts = [int(p) for p in re.findall(r"\d+", str(text))]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts) or (0,)


def download_bytes(url, timeout=HTTP_TIMEOUT, max_bytes=50 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": "IPChat-Setup"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(max_bytes)


def git_blob_sha1(content):
    """The same hash GitHub's API reports for a file - lets a download be checked
    against what GitHub itself says it should be, with nothing to maintain by hand."""
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def fetch_latest_release():
    """Lists the repo's files and picks whichever ip-chatX.Y[.Z].py has the highest
    version number in its name. Raises on any network/format problem."""
    api_url = f"https://api.github.com/repos/{UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}/contents/"
    req = urllib.request.Request(api_url, headers={"User-Agent": "IPChat-Setup",
                                                    "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        raw = resp.read(1 << 20)
    entries = json.loads(raw.decode("utf-8"))
    if not isinstance(entries, list):
        raise ValueError("unexpected response listing the repo's files")

    best = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        m = UPDATE_FILE_RE.match(str(entry.get("name", "")))
        if not m:
            continue
        vtuple = parse_version(m.group(1))
        if best is None or vtuple > best[0]:
            best = (vtuple, m.group(1), entry.get("download_url"), entry.get("sha"))
    if best is None or not best[2]:
        raise ValueError(f"no ip-chatX.Y.Z.py files found in {UPDATE_REPO_OWNER}/{UPDATE_REPO_NAME}")
    return {"version": best[1], "url": best[2], "git_sha": best[3]}


def documents_dir():
    """The user's real "Documents" folder (shown by Explorer as "Documenten" on a
    Dutch Windows, etc.) - asks Windows for its real, possibly-redirected location
    when possible, falling back to the ordinary default path."""
    if os.name == "nt":
        try:
            CSIDL_PERSONAL = 5
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, 0, buf) == 0:
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def can_use_as_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".ipchat_write_test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def choose_install_dir():
    """AppData\\IPChat (or ~/.config/IPChat off Windows) if that can actually be made
    and written to; otherwise Documents\\"IPChat Code" instead - a different name
    from the program's own "IPChat" data folder, since this is only this one-time
    setup tool falling back, not the program's own ongoing choice."""
    if os.name == "nt":
        preferred = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        preferred = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    candidate = os.path.join(preferred, "IPChat")
    if can_use_as_folder(candidate):
        return candidate
    return os.path.join(documents_dir(), "IPChat Code")


def create_shortcut(target_script, icon=None):
    """Builds "IP Chat.lnk" next to the installed script, using `icon` as its icon
    when one is given and actually exists. Windows-only; a no-op elsewhere."""
    if os.name != "nt":
        return None
    exe = sys.executable
    if target_script.lower().endswith(".pyw"):
        pyw_exe = os.path.join(os.path.dirname(sys.executable) or "", "pythonw.exe")
        if os.path.exists(pyw_exe):
            exe = pyw_exe
    folder = os.path.dirname(target_script)
    lnk_path = os.path.join(folder, "IP Chat.lnk")
    icon_line = f'$sc.IconLocation = "{icon},0"' if icon and os.path.exists(icon) else ""
    ps = f'''
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{lnk_path}")
$sc.TargetPath = "{exe}"
$sc.Arguments = '"{target_script}"'
$sc.WorkingDirectory = "{folder}"
{icon_line}
$sc.Save()
'''
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                    capture_output=True, text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    return lnk_path


def run_setup():
    install_dir = choose_install_dir()
    os.makedirs(install_dir, exist_ok=True)

    manifest = fetch_latest_release()
    script_bytes = download_bytes(manifest["url"])
    expected = manifest.get("git_sha")
    if expected and git_blob_sha1(script_bytes) != str(expected).strip().lower():
        raise ValueError("the downloaded script didn't match what GitHub said it should be")
    compile(script_bytes, "ip-chat-setup.py", "exec")   # reject a broken/truncated download

    target_script = os.path.join(install_dir, "ip-chat.pyw")
    tmp = target_script + ".new"
    with open(tmp, "wb") as f:
        f.write(script_bytes)
    os.replace(tmp, target_script)

    icon_path = os.path.join(install_dir, "iPC.ico")
    try:
        icon_bytes = download_bytes(ICON_URL, max_bytes=5 * 1024 * 1024)
        with open(icon_path, "wb") as f:
            f.write(icon_bytes)
    except Exception:
        icon_path = None   # best-effort - a missing icon never blocks setup

    lnk_path = None
    try:
        lnk_path = create_shortcut(target_script, icon_path)
    except (OSError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass   # the shortcut is a nice-to-have - a failed one shouldn't fail setup

    exe = sys.executable
    if os.name == "nt":
        pyw_exe = os.path.join(os.path.dirname(sys.executable) or "", "pythonw.exe")
        if os.path.exists(pyw_exe):
            exe = pyw_exe
    try:
        subprocess.Popen([exe, target_script], cwd=install_dir)
        launched = True
    except OSError:
        launched = False

    return install_dir, target_script, lnk_path, manifest["version"], launched


def installed_script_path():
    return os.path.join(choose_install_dir(), "ip-chat.pyw")


def report(title, message, error=False):
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, message, parent=r)
        r.destroy()
    except Exception:
        print(message)


def do_fresh_install():
    """A brand new install: nothing at `installed_script_path()` yet."""
    try:
        install_dir, target_script, lnk_path, version, launched = run_setup()
    except Exception as e:
        report("IP Chat - Setup",
               f"Setup could not finish:\n\n{e}\n\n"
               "Check your internet connection and try running this again.", error=True)
        sys.exit(1)

    lines = [f"IP Chat {version} is installed:", target_script]
    if lnk_path:
        lines.append('\nA shortcut ("IP Chat") was created there too - drag it onto '
                      "your taskbar to pin it.")
    if launched:
        lines.append("\nIt should be opening now.")
    report("IP Chat - Setup", "\n".join(lines))


def show_existing_menu(install_dir):
    """IP Chat is already installed at `install_dir`. Offers three things: leave it
    alone (Exit), wipe it completely except the Downloads\\IP Chat folder of files
    people have sent/received (Delete IPChat), or just fetch the current script,
    icon and shortcut again without touching settings.json, friends.json or ID.json
    (Redownload) - so re-running setup never costs you your identity or friends."""
    import tkinter as tk
    from tkinter import messagebox

    bg, panel, text, muted = "#0f172a", "#1e293b", "#e2e8f0", "#94a3b8"
    root = tk.Tk()
    root.title("IP Chat - Setup")
    root.configure(bg=bg)
    root.resizable(False, False)
    card = tk.Frame(root, bg=panel, padx=28, pady=24)
    card.pack(padx=20, pady=20)
    tk.Label(card, text="IP Chat is already installed", font=("Segoe UI", 14, "bold"),
             bg=panel, fg=text).pack()
    tk.Label(card, text=install_dir, font=("Segoe UI", 9), bg=panel, fg=muted,
             wraplength=380, justify="center").pack(pady=(4, 16))

    def do_exit():
        root.destroy()

    def do_delete():
        if not messagebox.askyesno(
                "Delete IP Chat",
                "This removes the installed program, your settings, your friends "
                "list, and your identity (ID.json).\n\n"
                "Your Downloads\\IP Chat folder - anything you've sent or received - "
                "is NOT touched.\n\nAre you sure?", parent=root):
            return
        try:
            shutil.rmtree(install_dir)
        except OSError as e:
            messagebox.showerror("Delete IP Chat", f"Could not delete everything:\n{e}",
                                 parent=root)
            return
        root.destroy()
        report("IP Chat - Setup", "IP Chat has been removed.")

    def do_redownload():
        root.destroy()
        try:
            _install_dir, target_script, lnk_path, version, launched = run_setup()
        except Exception as e:
            report("IP Chat - Setup",
                   f"Could not redownload:\n\n{e}\n\n"
                   "Check your internet connection and try again.", error=True)
            return
        lines = [f"IP Chat {version} has been redownloaded:", target_script,
                 "\nYour settings, friends and identity were not touched."]
        if launched:
            lines.append("\nIt should be opening now.")
        report("IP Chat - Setup", "\n".join(lines))

    buttons = tk.Frame(card, bg=panel)
    buttons.pack()
    tk.Button(buttons, text="Exit", width=14, command=do_exit).pack(side="left", padx=4)
    tk.Button(buttons, text="Delete IPChat", width=14, command=do_delete).pack(side="left", padx=4)
    tk.Button(buttons, text="Redownload", width=14, command=do_redownload).pack(side="left", padx=4)
    root.mainloop()


def main():
    install_dir = choose_install_dir()
    if os.path.exists(os.path.join(install_dir, "ip-chat.pyw")):
        show_existing_menu(install_dir)
    else:
        do_fresh_install()


if __name__ == "__main__":
    main()
