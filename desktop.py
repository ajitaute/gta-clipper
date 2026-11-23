"""GTA Clipper as a desktop app: its own window, no browser tab.
The shortcuts made by start.bat / start.command open this file."""
import os, sys, socket, threading, time, json, webbrowser, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)
LOCK = HERE / "workspace" / "app.lock"
ICON = HERE / "assets" / "icon.png"
(HERE / "workspace").mkdir(exist_ok=True)

# With no console window (pythonw / the Mac app), keep a log file for troubleshooting
if sys.stdout is None or not sys.stdout.isatty():
    log = open(HERE / "workspace" / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log


def alive(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1.5)
        return True
    except Exception:
        return False


def free_port(start=5000):
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise RuntimeError("No free port found")


def start_server():
    """Start the app's engine in the background, or reuse one that's already running."""
    try:
        port = json.loads(LOCK.read_text())["port"]
        if alive(port):
            return port, False
    except Exception:
        pass
    port = free_port()
    import app as server
    threading.Thread(target=lambda: server.app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
                     daemon=True).start()
    for _ in range(100):
        if alive(port):
            break
        time.sleep(0.1)
    LOCK.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    return port, True


def mac_branding():
    """Show 'GTA Clipper' and our icon in the Dock and menu bar instead of 'Python'."""
    try:
        from Foundation import NSBundle
        from AppKit import NSApplication, NSImage
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = info["CFBundleDisplayName"] = "GTA Clipper"
        NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(ICON)))
    except Exception as ex:
        print("Mac branding skipped:", ex)


def fallback_window(url):
    """If the app window can't be shown, open the browser and keep a small window to quit."""
    webbrowser.open(url)
    try:
        import tkinter as tk
        root = tk.Tk()
        root.title("GTA Clipper")
        root.geometry("320x130")
        tk.Label(root, text="GTA Clipper is running.", font=("Helvetica", 13, "bold")).pack(pady=(16, 8))
        row = tk.Frame(root)
        row.pack()
        tk.Button(row, text="Open app", width=10, command=lambda: webbrowser.open(url)).pack(side="left", padx=6)
        tk.Button(row, text="Quit", width=10, command=root.destroy).pack(side="left", padx=6)
        root.mainloop()
    except Exception:
        while True:
            time.sleep(3600)


def main():
    port, owner = start_server()
    url = f"http://127.0.0.1:{port}/"
    try:
        import webview
    except Exception as ex:
        print("App window not available, using the browser:", ex)
        return fallback_window(url)
    if sys.platform == "darwin":
        mac_branding()
    if os.name == "nt":  # our icon on the taskbar instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GTAClipper.App")
        except Exception:
            pass
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception:
        pass
    webview.create_window("GTA Clipper", url, width=1320, height=880, min_size=(760, 560),
                          background_color="#17122B", text_select=True)
    try:
        webview.start(icon=str(ICON))
    except TypeError:
        webview.start()
    except Exception as ex:
        print("App window failed, using the browser:", ex)
        return fallback_window(url)
    if owner:
        LOCK.unlink(missing_ok=True)
    os._exit(0)  # closing the window quits the app


if __name__ == "__main__":
    main()
