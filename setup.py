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


def main():
    try:
        install_dir, target_script, lnk_path, version, launched = run_setup()
    except Exception as e:
        message = (f"Setup could not finish:\n\n{e}\n\n"
                   "Check your internet connection and try running this again.")
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("IP Chat - Setup", message)
        except Exception:
            print(message)
        sys.exit(1)

    lines = [f"IP Chat {version} is installed:", target_script]
    if lnk_path:
        lines.append(f'\nA shortcut ("IP Chat") was created there too - drag it onto '
                      "your taskbar to pin it.")
    if launched:
        lines.append("\nIt should be opening now.")
    message = "\n".join(lines)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw()
        messagebox.showinfo("IP Chat - Setup", message)
    except Exception:
        print(message)


if __name__ == "__main__":
    main()
