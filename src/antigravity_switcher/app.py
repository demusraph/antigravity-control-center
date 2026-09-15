import os
import sys
import traceback
from datetime import datetime, timezone

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        for std_id in (-10, -11, -12):
            h = kernel32.GetStdHandle(std_id)
            if not h or h == -1:
                h_nul = kernel32.CreateFileW("NUL", 0xC0000000, 3, None, 3, 0, None)
                kernel32.SetStdHandle(std_id, h_nul)
    except Exception:
        pass

USERPROFILE = os.environ.get("USERPROFILE", "")
APPDATA = os.environ.get("APPDATA", "")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
SWITCHER_DIR = os.path.join(USERPROFILE, ".gemini", "antigravity-switcher")

def log_exception(exc_type, exc_value, exc_traceback):
    try:
        os.makedirs(SWITCHER_DIR, exist_ok=True)
        log_path = os.path.join(SWITCHER_DIR, "app_crash.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- CRASH AT {datetime.now()} ---\n")
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass

sys.excepthook = log_exception

import re
import json
import sqlite3
import shutil
import subprocess
import time
import socket
import threading
import ctypes
from ctypes import wintypes
import urllib.request
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor

# Set explicit Windows AppUserModelID so Taskbar uses our custom icon instead of Anaconda pythonw / Spyder icon
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("google.antigravity.controlcenter.pro.v1")
except Exception:
    pass

try:
    from antigravity_switcher import subagent_tracker, mcp_supervisor
except ImportError:
    import subagent_tracker
    import mcp_supervisor

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer, QUrl, QSize, QPoint, QPropertyAnimation, QEasingCurve, QRect
from PyQt5.QtGui import QIcon, QColor, QPalette
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QSystemTrayIcon, QMenu, QMessageBox, QAction,
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSplashScreen
)

if getattr(sys, 'frozen', False):
    BUNDLE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(sys.executable)
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BUNDLE_DIR

# --- Paths ---
ANTIGRAV_ROAMING = os.path.join(APPDATA, "Antigravity")
ANTIGRAV_EXE = os.path.join(LOCALAPPDATA, "Programs", "Antigravity", "Antigravity.exe")
STATE_VSCDB_FILE = os.path.join(ANTIGRAV_ROAMING, "User", "globalStorage", "state.vscdb")
COOKIES_FILE = os.path.join(ANTIGRAV_ROAMING, "Network", "Cookies")

ACCOUNTS_DIR = os.path.join(SWITCHER_DIR, "accounts")
ACTIVE_FILE = os.path.join(SWITCHER_DIR, "active_email.txt")
AUTOPILOT_PID_FILE = os.path.join(SWITCHER_DIR, "autopilot.pid")
LOG_FILE = os.path.join(SWITCHER_DIR, "autopilot.log")
# Icon detection across bundle, assets/icons, and repo structure
_CURR_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_DIR = os.path.dirname(os.path.dirname(_CURR_DIR))

possible_pngs = [
    os.path.join(BUNDLE_DIR, "assets", "icons", "app_icon.png"),
    os.path.join(BUNDLE_DIR, "app_icon.png"),
    os.path.join(APP_DIR, "assets", "icons", "app_icon.png"),
    os.path.join(APP_DIR, "app_icon.png"),
    os.path.join(_REPO_DIR, "assets", "icons", "app_icon.png"),
]
ICON_PNG = next((p for p in possible_pngs if os.path.exists(p)), "")

possible_icos = [
    os.path.join(BUNDLE_DIR, "assets", "icons", "app_icon.ico"),
    os.path.join(BUNDLE_DIR, "app_icon.ico"),
    os.path.join(APP_DIR, "assets", "icons", "app_icon.ico"),
    os.path.join(APP_DIR, "app_icon.ico"),
    os.path.join(_REPO_DIR, "assets", "icons", "app_icon.ico"),
]
ICON_ICO = next((p for p in possible_icos if os.path.exists(p)), "")

possible_office_pngs = [
    os.path.join(BUNDLE_DIR, "assets", "office", "office_floor_pixel.png"),
    os.path.join(APP_DIR, "assets", "office", "office_floor_pixel.png"),
    os.path.join(_REPO_DIR, "assets", "office", "office_floor_pixel.png"),
]
OFFICE_PIXEL_PNG = next((p for p in possible_office_pngs if os.path.exists(p)), "")

# Obfuscated runtime credentials (Google Antigravity public client)
_K = 0x37
_ID_B = [6,7,0,6,7,7,1,7,1,7,2,14,6,26,67,90,95,68,68,94,89,5,95,5,6,91,84,69,82,5,4,2,65,67,88,91,88,93,95,3,80,3,7,4,82,71,25,86,71,71,68,25,80,88,88,80,91,82,66,68,82,69,84,88,89,67,82,89,67,25,84,88,90]
_SEC_B = [112,120,116,100,103,111,26,124,2,15,113,96,101,3,15,1,123,83,123,125,6,90,123,117,15,68,111,116,3,77,1,70,115,118,81]
CLIENT_ID = bytes([b ^ _K for b in _ID_B]).decode("utf-8")
CLIENT_SECRET = bytes([b ^ _K for b in _SEC_B]).decode("utf-8")
CRED_TARGET = "gemini:antigravity"
LOCAL_SERVER_INSTANCE = None
ACTUAL_PORT = 28795
WINDOW_INSTANCE = None

# Windows Credential Manager API
advapi32 = ctypes.windll.advapi32
kernel32 = ctypes.windll.kernel32

class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ('Flags', wintypes.DWORD),
        ('Type', wintypes.DWORD),
        ('TargetName', wintypes.LPWSTR),
        ('Comment', wintypes.LPWSTR),
        ('LastWritten', wintypes.FILETIME),
        ('CredentialBlobSize', wintypes.DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_byte)),
        ('Persist', wintypes.DWORD),
        ('AttributeCount', wintypes.DWORD),
        ('Attributes', ctypes.c_void_p),
        ('TargetAlias', wintypes.LPWSTR),
        ('UserName', wintypes.LPWSTR),
    ]

PCREDENTIALW = ctypes.POINTER(CREDENTIALW)

def ensure_dirs():
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)

def read_windows_credential(target=CRED_TARGET):
    pcred = PCREDENTIALW()
    if advapi32.CredReadW(target, 1, 0, ctypes.byref(pcred)):
        size = pcred.contents.CredentialBlobSize
        blob = bytes(ctypes.string_at(pcred.contents.CredentialBlob, size))
        user_name = pcred.contents.UserName
        persist = pcred.contents.Persist
        advapi32.CredFree(pcred)
        return {"blob": blob, "user_name": user_name, "persist": persist}
    return None

def write_windows_credential(target, blob_bytes, user_name="antigravity", persist=2):
    blob_buf = (ctypes.c_byte * len(blob_bytes))(*blob_bytes)
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = 1
    cred.TargetName = target
    cred.Comment = None
    cred.CredentialBlobSize = len(blob_bytes)
    cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = persist
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = user_name
    return advapi32.CredWriteW(ctypes.byref(cred), 0)

def delete_windows_credential(target=CRED_TARGET):
    return advapi32.CredDeleteW(target, 1, 0)

def refresh_access_token(refresh_token):
    try:
        payload = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        }
        data_bytes = urllib.parse.urlencode(payload).encode('utf-8')
        req = urllib.request.Request('https://oauth2.googleapis.com/token', data=data_bytes)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('access_token')
    except Exception:
        return None

def fetch_email_from_blob(blob_bytes):
    try:
        data = json.loads(blob_bytes.decode('utf-8'))
        rf = data.get("token", {}).get("refresh_token", "")
        token = data.get("token", {}).get("access_token", "")
        if rf:
            refreshed = refresh_access_token(rf)
            if refreshed:
                token = refreshed
        if not token:
            return None
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            info = json.loads(resp.read().decode('utf-8'))
            return info.get("email")
    except Exception:
        return None

def fetch_quota_summary(email):
    acc_dir = os.path.join(ACCOUNTS_DIR, email)
    cred_file = os.path.join(acc_dir, "cred.bin")
    if not os.path.exists(cred_file):
        return {"error": "No credential file"}
        
    try:
        cred_data = json.loads(open(cred_file, 'rb').read().decode('utf-8'))
        rf = cred_data.get('token', {}).get('refresh_token', '')
        if not rf:
            return {"error": "No refresh token"}
            
        token = refresh_access_token(rf)
        if not token:
            return {"error": "Failed to refresh token"}
            
        url = 'https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary'
        req = urllib.request.Request(
            url,
            data=b'{}',
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
                'User-Agent': 'antigravity/2.12.2'
            }
        )
        with urllib.request.urlopen(req, timeout=6) as r:
            res = json.loads(r.read().decode('utf-8'))
            summary = {}
            for g in res.get('groups', []):
                g_name = g.get('displayName', '')
                buckets = {}
                for b in g.get('buckets', []):
                    w = b.get('window', '')
                    rem = b.get('remainingFraction', 1.0) * 100.0
                    rt = b.get('resetTime')
                    buckets[w] = {"remaining": rem, "resetTime": rt}
                if 'Gemini' in g_name:
                    summary['gemini'] = buckets
                elif 'Claude' in g_name:
                    summary['claude'] = buckets
            return summary
    except Exception as e:
        return {"error": str(e)}

def parse_reset_delta(reset_time_str):
    if not reset_time_str:
        return ""
    try:
        dt = datetime.fromisoformat(reset_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = dt - now
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return "Ready"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours >= 24:
            days = hours // 24
            rem_h = hours % 24
            return f"{days}d {rem_h}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except Exception:
        return ""

def score_account(quota_data):
    if not quota_data or "error" in quota_data:
        return -999999.0
    gemini = quota_data.get("gemini", {})
    claude = quota_data.get("claude", {})
    
    def get_val(container, key):
        val = container.get(key, 0.0)
        if isinstance(val, dict):
            return val.get("remaining", 0.0)
        return float(val)

    g_5h = get_val(gemini, "5h")
    g_wk = get_val(gemini, "weekly")
    c_5h = get_val(claude, "5h")
    c_wk = get_val(claude, "weekly")
    
    score = 0.0
    if g_5h <= 1.0:
        score -= 100000.0
    else:
        score += g_5h * 1000.0
        
    score += g_wk * 10.0
    score += c_5h * 5.0
    score += c_wk * 1.0
    return score

def get_saved_accounts():
    ensure_dirs()
    accs = []
    for item in os.listdir(ACCOUNTS_DIR):
        p = os.path.join(ACCOUNTS_DIR, item)
        if os.path.isdir(p) and os.path.exists(os.path.join(p, "cred.bin")):
            accs.append(item)
    return sorted(accs)

def save_active_credential():
    ensure_dirs()
    cred = read_windows_credential()
    if not cred:
        return None
        
    email = fetch_email_from_blob(cred["blob"])
    if not email and os.path.exists(ACTIVE_FILE):
        try:
            with open(ACTIVE_FILE, "r") as f:
                email = f.read().strip()
        except Exception:
            pass
            
    if not email:
        email = "default_account"
        
    acc_dir = os.path.join(ACCOUNTS_DIR, email)
    os.makedirs(acc_dir, exist_ok=True)
    with open(os.path.join(acc_dir, "cred.bin"), "wb") as f:
        f.write(cred["blob"])
    with open(os.path.join(acc_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"email": email, "user_name": cred["user_name"], "persist": cred["persist"]}, f, indent=2)
        
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        f.write(email)
        
    return email

def stop_antigravity():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "Antigravity.exe"], capture_output=True, text=True)
    except Exception:
        pass
    time.sleep(1.5)

def start_antigravity():
    if os.path.exists(ANTIGRAV_EXE):
        subprocess.Popen([ANTIGRAV_EXE], shell=True)

def clear_session_cache():
    if os.path.exists(COOKIES_FILE):
        try:
            os.remove(COOKIES_FILE)
        except Exception:
            pass
    if os.path.exists(STATE_VSCDB_FILE):
        try:
            conn = sqlite3.connect(STATE_VSCDB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM ItemTable WHERE key IN ('antigravityUnifiedStateSync.oauthToken', 'antigravityUnifiedStateSync.userStatus')")
            conn.commit()
            conn.close()
        except Exception:
            pass

def switch_to_account_core(target_email):
    ensure_dirs()
    save_active_credential()
    
    acc_dir = os.path.join(ACCOUNTS_DIR, target_email)
    cred_file = os.path.join(acc_dir, "cred.bin")
    if not os.path.exists(cred_file):
        return False
        
    stop_antigravity()
    
    with open(cred_file, "rb") as f:
        blob = f.read()
    user_name = "antigravity"
    persist = 2
    meta_file = os.path.join(acc_dir, "meta.json")
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
                user_name = meta.get("user_name", "antigravity")
                persist = meta.get("persist", 2)
        except Exception:
            pass
            
    write_windows_credential(CRED_TARGET, blob, user_name, persist)
    clear_session_cache()
    
    with open(ACTIVE_FILE, "w", encoding="utf-8") as f:
        f.write(target_email)
        
    start_antigravity()
    return True

def is_autopilot_running():
    if not os.path.exists(AUTOPILOT_PID_FILE):
        return False, None
    try:
        with open(AUTOPILOT_PID_FILE, "r") as f:
            pid_str = f.read().strip()
        if not pid_str:
            return False, None
        pid = int(pid_str)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            exit_code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                if exit_code.value == 259:  # STILL_ACTIVE
                    kernel32.CloseHandle(handle)
                    return True, pid
            kernel32.CloseHandle(handle)
        try:
            os.remove(AUTOPILOT_PID_FILE)
        except Exception:
            pass
    except Exception:
        pass
    return False, None

def set_autopilot_state(enable: bool):
    try:
        running, pid = is_autopilot_running()
        if enable and not running:
            DETACHED_FLAGS = 0x00000008 | 0x00000200
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable, "--daemon"]
                cwd = os.path.dirname(sys.executable)
            else:
                main_py = os.path.join(_REPO_DIR, "main.py")
                daemon_py = os.path.join(_CURR_DIR, "daemon.py")
                if os.path.exists(main_py):
                    cmd = [sys.executable, main_py, "--daemon"]
                    cwd = _REPO_DIR
                elif os.path.exists(daemon_py):
                    cmd = [sys.executable, daemon_py]
                    cwd = _CURR_DIR
                else:
                    cmd = [sys.executable, "-m", "antigravity_switcher.daemon"]
                    cwd = _REPO_DIR

            proc = subprocess.Popen(cmd, cwd=cwd, creationflags=DETACHED_FLAGS, close_fds=True)
            with open(AUTOPILOT_PID_FILE, "w") as f:
                f.write(str(proc.pid))
            return True
        elif not enable and running:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            except Exception:
                pass
            if os.path.exists(AUTOPILOT_PID_FILE):
                try:
                    os.remove(AUTOPILOT_PID_FILE)
                except Exception:
                    pass
            return True
    except Exception:
        log_exception(*sys.exc_info())
        return False
    return True

# --- Pixel Art Assets Bundle Loader ---
PIXEL_BUNDLE_PATH = os.path.join(os.path.dirname(__file__), "assets", "pixel_assets_bundle.json")
if os.path.exists(PIXEL_BUNDLE_PATH):
    try:
        with open(PIXEL_BUNDLE_PATH, "r", encoding="utf-8") as _f:
            PIXEL_ASSETS_BUNDLE_JSON = _f.read()
    except Exception:
        PIXEL_ASSETS_BUNDLE_JSON = "{}"
else:
    PIXEL_ASSETS_BUNDLE_JSON = "{}"

# --- HTML / Tailwind Linear Interface ---
HTML_INTERFACE = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Control Center</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/lucide@latest"></script>
  <script src="/assets/vendor/three.min.js"></script>
  <script>
    if (typeof THREE === 'undefined') {
      document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"><\\/script>');
    }
  </script>
  <script src="/assets/vendor/OrbitControls.js"></script>
  <script>
    if (typeof THREE !== 'undefined' && typeof THREE.OrbitControls === 'undefined') {
      document.write('<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"><\\/script>');
    }
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
            mono: ['JetBrains Mono', 'Consolas', 'monospace'],
          },
          colors: {
            canvas: '#101010',
            surface: '#191919',
            'surface-2': '#151515',
            'surface-3': '#222222',
            'surface-hover': '#272727',
            hairline: '#222222',
            'hairline-strong': '#333333',
            accent: '#2B7FFF',
            'accent-hover': '#3B82F6',
            emerald: {
              400: '#34D399',
              500: '#10B981',
              900: '#064E3B',
              950: '#03261C',
            }
          }
        }
      }
    }
  </script>
  <style>
    body {
      background-color: #101010;
      color: #CCCCCC;
      user-select: none;
      -webkit-user-select: none;
    }
    ::-webkit-scrollbar {
      width: 5px;
    }
    ::-webkit-scrollbar-track {
      background: transparent;
    }
    ::-webkit-scrollbar-thumb {
      background: #222222;
      border-radius: 3px;
    }
    ::-webkit-scrollbar-thumb:hover {
      background: #333333;
    }
    button {
      appearance: none;
      -webkit-appearance: none;
      background-color: transparent;
      border: 0 solid transparent;
      color: inherit;
      outline: none;
      cursor: pointer;
    }
    .topbar-btn {
      height: 24px;
      padding: 0 8px;
      border-radius: 5px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 12px;
      font-weight: 500;
      color: #9D9D9D;
      background: transparent;
      border: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      user-select: none;
      transition: background-color 0.1s ease, color 0.1s ease;
      outline: none;
    }
    .topbar-btn:hover, .topbar-btn.active {
      background-color: #2D2D2D;
      color: #FAFAFA;
    }
    .topbar-btn:focus {
      outline: none;
    }
    .dropdown-menu {
      position: absolute;
      top: 31px;
      left: 0;
      background-color: #181818;
      border: 1px solid #282828;
      border-radius: 6px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
      padding: 4px;
      z-index: 9999;
      min-width: 180px;
    }
    .dropdown-item {
      padding: 5px 10px;
      border-radius: 4px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 12px;
      color: #CCCCCC;
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
      user-select: none;
      transition: background-color 0.08s ease, color 0.08s ease;
    }
    .dropdown-item:hover {
      background-color: #282828;
      color: #FFFFFF;
    }
    .dropdown-sep {
      height: 1px;
      background-color: #262626;
      margin: 4px 0;
    }
    .shortcut {
      font-size: 10px;
      color: #6E6E6E;
      font-family: 'JetBrains Mono', Consolas, monospace;
    }
    .win-btn {
      height: 36px;
      width: 46px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: #888888;
      transition: all 0.15s ease;
      cursor: pointer !important;
      background: transparent;
      border: none;
      outline: none;
      -webkit-app-region: no-drag !important;
      pointer-events: auto !important;
      z-index: 9999 !important;
    }
    .win-btn:hover {
      background-color: #2D2D2D;
      color: #FAFAFA;
    }
    .win-btn-close:hover {
      background-color: #E81123 !important;
      color: #FFFFFF !important;
    }

    /* Motion & Polish Layer */
    .spotlight-card {
      position: relative;
      overflow: hidden;
    }
    .spotlight-card::before {
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(
        420px circle at var(--mouse-x, -999px) var(--mouse-y, -999px),
        rgba(255, 255, 255, 0.04),
        transparent 65%
      );
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.3s ease;
      z-index: 1;
    }
    .spotlight-card:hover::before {
      opacity: 1;
    }

    .border-glow-active {
      position: relative;
      animation: pulseGlow 3s ease-in-out infinite alternate;
    }
    @keyframes pulseGlow {
      0% {
        box-shadow: 0 0 15px -2px rgba(16, 185, 129, 0.08), inset 0 0 8px -2px rgba(16, 185, 129, 0.04);
      }
      100% {
        box-shadow: 0 0 25px 0px rgba(16, 185, 129, 0.18), inset 0 0 12px 0px rgba(16, 185, 129, 0.08);
      }
    }

    .btn-spring {
      transition: transform 0.16s cubic-bezier(0.34, 1.56, 0.64, 1), background-color 0.1s ease, border-color 0.1s ease, color 0.1s ease;
    }
    .btn-spring:active {
      transform: scale(0.93) !important;
    }

    .tab-animated-enter {
      animation: tabSlideEnter 0.22s cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }
    @keyframes tabSlideEnter {
      from {
        opacity: 0;
        transform: translateY(5px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .icon-spin-enter {
      animation: iconSpin 0.22s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes iconSpin {
      from {
        transform: rotate(-90deg) scale(0.85);
        opacity: 0;
      }
      to {
        transform: rotate(0) scale(1);
        opacity: 1;
      }
    }

    /* Pixel Office Game Simulator & Retro HUD */
    .pixel-art-img {
      image-rendering: pixelated;
      image-rendering: -moz-crisp-edges;
      image-rendering: crisp-edges;
    }
    .crt-scanlines {
      background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.35) 50%);
      background-size: 100% 4px;
    }
    .pixel-zone {
      border: 1px dashed transparent;
      border-radius: 6px;
      transition: all 0.2s ease;
    }
    .pixel-zone:hover {
      border-color: rgba(255, 255, 255, 0.15);
      background-color: rgba(255, 255, 255, 0.02);
    }
    .pixel-zone .zone-tag {
      position: absolute;
      top: 6px;
      right: 6px;
      font-size: 9px;
      font-family: 'JetBrains Mono', Consolas, monospace;
      padding: 1px 5px;
      border-radius: 3px;
      background: rgba(13, 13, 17, 0.85);
      border: 1px solid rgba(255, 255, 255, 0.08);
      color: #888899;
      opacity: 0;
      transition: opacity 0.15s ease;
      pointer-events: none;
    }
    .pixel-zone:hover .zone-tag {
      opacity: 1;
    }
    #zone-exec:hover {
      box-shadow: inset 0 0 25px rgba(59, 130, 246, 0.08);
    }
    #zone-eng:hover {
      box-shadow: inset 0 0 25px rgba(139, 92, 246, 0.08);
    }
    #zone-intel:hover {
      box-shadow: inset 0 0 25px rgba(16, 185, 129, 0.08);
    }
    #zone-sec:hover {
      box-shadow: inset 0 0 25px rgba(245, 158, 11, 0.08);
    }
    
    .pixel-agent {
      position: absolute;
      transform: translate(-50%, -50%);
      z-index: 25;
      cursor: pointer;
      transition: transform 0.15s ease, filter 0.15s ease;
      outline: none;
    }
    .pixel-agent:hover {
      transform: translate(-50%, -54%) scale(1.1);
      z-index: 50;
      filter: brightness(1.15);
    }
    .pixel-agent:focus-visible {
      outline: 2px solid #3b82f6;
    }
    .pixel-shadow {
      width: 20px;
      height: 5px;
      background: rgba(0, 0, 0, 0.65);
      border-radius: 50%;
      margin: -3px auto 0 auto;
      filter: blur(0.6px);
    }
    .pixel-monitor-glow {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -85%);
      width: 24px;
      height: 14px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(56, 189, 248, 0.5) 0%, rgba(56, 189, 248, 0) 70%);
      pointer-events: none;
      z-index: 15;
      animation: screenFlicker 2.4s infinite ease-in-out;
    }
    @keyframes screenFlicker {
      0%, 100% { opacity: 0.85; transform: translate(-50%, -85%) scale(1); }
      40% { opacity: 0.55; transform: translate(-50%, -85%) scale(0.94); }
      75% { opacity: 1; transform: translate(-50%, -85%) scale(1.06); }
    }
    .pixel-bubble {
      position: absolute;
      bottom: 100%;
      left: 50%;
      transform: translateX(-50%);
      margin-bottom: 3px;
      background: #121217;
      border: 1px solid #3b82f6;
      border-radius: 4px;
      padding: 1.5px 4.5px;
      color: #fff;
      font-size: 8.5px;
      font-family: 'JetBrains Mono', Consolas, monospace;
      white-space: nowrap;
      box-shadow: 0 4px 10px rgba(0, 0, 0, 0.8);
      display: flex;
      align-items: center;
      gap: 3px;
      pointer-events: none;
      animation: bubbleFloat 2.8s ease-in-out infinite alternate;
    }
    @keyframes bubbleFloat {
      0% { transform: translate(-50%, 0); }
      100% { transform: translate(-50%, -2px); }
    }
    .pixel-bubble::after {
      content: '';
      position: absolute;
      top: 100%;
      left: 50%;
      margin-left: -3px;
      border-width: 3px;
      border-style: solid;
      border-color: #3b82f6 transparent transparent transparent;
    }
    .pixel-bubble.working {
      border-color: #10b981;
      color: #34d399;
    }
    .pixel-bubble.working::after {
      border-color: #10b981 transparent transparent transparent;
    }
    .pixel-bubble.meeting {
      border-color: #f59e0b;
      color: #fbbf24;
    }
    .pixel-bubble.meeting::after {
      border-color: #f59e0b transparent transparent transparent;
    }
    .pixel-bubble.blocked {
      border-color: #ef4444;
      color: #f87171;
    }
    .pixel-bubble.blocked::after {
      border-color: #ef4444 transparent transparent transparent;
    }
    .pixel-bubble.standby {
      border-color: #4b5563;
      color: #9ca3af;
    }
    .pixel-bubble.standby::after {
      border-color: #4b5563 transparent transparent transparent;
    }
    .pixel-bubble-dot {
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: currentColor;
    }
    .pixel-tooltip, .pixel-agent-tooltip {
      position: absolute;
      bottom: calc(100% + 20px);
      left: 50%;
      transform: translateX(-50%) translateY(4px);
      width: 220px;
      background: #12131a;
      border: 1px solid #38384d;
      border-radius: 8px;
      padding: 8px 10px;
      box-shadow: 0 12px 30px -4px rgba(0, 0, 0, 0.95), 0 0 0 1px rgba(255, 255, 255, 0.08);
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s;
      z-index: 100;
    }
    .pixel-agent:hover .pixel-tooltip,
    .pixel-agent:hover .pixel-agent-tooltip,
    .pixel-agent:focus-visible .pixel-tooltip,
    .pixel-agent:focus-visible .pixel-agent-tooltip {
      opacity: 1;
      visibility: visible;
      transform: translateX(-50%) translateY(0);
      pointer-events: auto;
    }
    .pixel-sprite {
      display: block;
      image-rendering: pixelated;
      image-rendering: -moz-crisp-edges;
      image-rendering: crisp-edges;
      filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.75));
    }
    /* Three.js 3D Virtual Headquarters Overlay Styling */
    .three-badge {
      position: absolute;
      transform: translate(-50%, -100%);
      background: rgba(16, 16, 22, 0.88);
      border: 1px solid #3b82f6;
      border-radius: 4px;
      padding: 2px 7px;
      color: #ffffff;
      font-size: 9.5px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      white-space: nowrap;
      pointer-events: none;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.85), 0 0 0 1px rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: center;
      gap: 5px;
      backdrop-filter: blur(4px);
      transition: transform 0.08s ease, opacity 0.08s ease;
      z-index: 10;
    }
    .three-badge.working { border-color: #10b981; color: #34d399; }
    .three-badge.meeting { border-color: #f59e0b; color: #fbbf24; }
    .three-badge.standby { border-color: #6b7280; color: #9ca3af; }
    .three-badge.blocked { border-color: #ef4444; color: #f87171; }
    .three-badge-dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: currentColor;
    }
    .three-hud-card {
      background: rgba(15, 15, 20, 0.94);
      border: 1px solid #383848;
      border-radius: 8px;
      padding: 8px 12px;
      color: #e2e8f0;
      box-shadow: 0 12px 30px rgba(0,0,0,0.9), 0 0 0 1px rgba(255,255,255,0.08);
      backdrop-filter: blur(8px);
      min-width: 220px;
    }
    /* Antigravity Launch Loading Screen (1:1 with official launch reference) */
    @keyframes agyLaunchPulse {
      0%, 80%, 100% {
        opacity: 0.25;
        transform: scale(0.85);
        background-color: #4b5563;
      }
      40% {
        opacity: 1;
        transform: scale(1.18);
        background-color: #f3f4f6;
        box-shadow: 0 0 8px rgba(243, 244, 246, 0.45);
      }
    }
    .agy-loader-dot {
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: #4b5563;
      animation: agyLaunchPulse 1.35s infinite ease-in-out both;
    }
    .agy-dot-1 { animation-delay: -0.32s; }
    .agy-dot-2 { animation-delay: -0.16s; }
    .agy-dot-3 { animation-delay: 0s; }
  </style>
</head>
<body class="font-sans antialiased overflow-hidden flex flex-col h-screen select-none bg-canvas text-[#CCCCCC]">

  <!-- Antigravity Native App Launch Screen (1:1 with official launch reference) -->
  <div id="app-launch-loader" class="fixed inset-0 z-[999999] bg-[#0c0d10] flex flex-col items-center justify-center select-none" style="transition: opacity 0.5s cubic-bezier(0.16, 1, 0.3, 1), visibility 0.5s;">
    <div class="flex flex-col items-center justify-center">
      <!-- 3 Animated Loading Wave Dots -->
      <div class="flex items-center gap-[9px] mb-[18px]">
        <span class="agy-loader-dot agy-dot-1"></span>
        <span class="agy-loader-dot agy-dot-2"></span>
        <span class="agy-loader-dot agy-dot-3"></span>
      </div>
      <!-- Label -->
      <div class="text-[#8e95a0] text-[13.5px] font-normal tracking-[0.015em] font-sans antialiased">
        Loading Antigravity
      </div>
    </div>
  </div>

  <!-- Antigravity 2.0 1:1 Seamless Obsidian Top Bar with Clear Hierarchy -->
  <div class="h-[36px] bg-[#161616] border-b border-[#222222] flex items-center justify-between shrink-0 select-none text-xs z-50">
    <!-- Left: Brand Identity & Menus -->
    <div class="flex items-center h-full pl-3 select-none">
      <!-- Enriched 20px Logo -->
      <img src="/app_icon.png" class="w-[20px] h-[20px] mr-2.5 select-none pointer-events-none drop-shadow-sm" onerror="this.style.display='none'">
      
      <!-- Prominent Brand Hierarchy -->
      <div class="flex items-center gap-1.5 mr-3 select-none">
        <span class="text-[13.5px] font-bold text-white tracking-tight">Antigravity</span>
        <span class="text-[13.5px] font-medium text-[#A3A3A3] tracking-tight">Control Center</span>
      </div>

      <!-- Subtle Divider -->
      <div class="h-3.5 w-px bg-[#262626] mr-2.5 select-none"></div>

      <!-- Menu Items -->
      <div class="flex items-center gap-0.5">
        <!-- File Menu -->
        <div class="relative">
          <button type="button" onclick="toggleMenu('file')" onmouseenter="hoverMenu('file')" id="menu-btn-file" class="topbar-btn">File</button>
          <div id="menu-dropdown-file" class="dropdown-menu hidden">
            <div onclick="syncCreds(); closeAllMenus();" class="dropdown-item">
              <span>Sync Credentials</span>
              <span class="shortcut">F5</span>
            </div>
            <div class="dropdown-sep"></div>
            <div onclick="windowClose(); closeAllMenus();" class="dropdown-item">
              <span>Hide to System Tray</span>
              <span class="shortcut">Esc</span>
            </div>
            <div onclick="windowQuit(); closeAllMenus();" class="dropdown-item hover:!bg-[#E81123]">
              <span>Quit Application</span>
              <span class="shortcut">Alt+F4</span>
            </div>
          </div>
        </div>

        <!-- View Menu -->
        <div class="relative">
          <button type="button" onclick="toggleMenu('view')" onmouseenter="hoverMenu('view')" id="menu-btn-view" class="topbar-btn">View</button>
          <div id="menu-dropdown-view" class="dropdown-menu hidden">
            <div onclick="selectTabAndClose('accounts')" class="dropdown-item">
              <span>Accounts Radar</span>
            </div>
            <div onclick="selectTabAndClose('subagents')" class="dropdown-item">
              <span>Subagent DAG</span>
            </div>
            <div onclick="selectTabAndClose('mcp')" class="dropdown-item">
              <span>MCP Matrix</span>
            </div>
            <div onclick="selectTabAndClose('logs')" class="dropdown-item">
              <span>Activity Logs</span>
            </div>
            <div onclick="selectTabAndClose('manage')" class="dropdown-item">
              <span>Enroll Account</span>
            </div>
            <div class="dropdown-sep"></div>
            <div onclick="window.location.reload()" class="dropdown-item">
              <span>Reload Window</span>
              <span class="shortcut">Ctrl+R</span>
            </div>
          </div>
        </div>

        <!-- Window Menu -->
        <div class="relative">
          <button type="button" onclick="toggleMenu('window')" onmouseenter="hoverMenu('window')" id="menu-btn-window" class="topbar-btn">Window</button>
          <div id="menu-dropdown-window" class="dropdown-menu hidden">
            <div onclick="windowMinimize(); closeAllMenus();" class="dropdown-item">
              <span>Minimize</span>
            </div>
            <div onclick="windowMaximize(); closeAllMenus();" class="dropdown-item">
              <span>Toggle Maximize</span>
            </div>
            <div class="dropdown-sep"></div>
            <div onclick="windowClose(); closeAllMenus();" class="dropdown-item">
              <span>Hide to System Tray</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Center Drag Region -->
    <div ondblclick="windowMaximize()" class="flex-1 h-full cursor-default select-none" style="-webkit-app-region: drag;"></div>

    <!-- Right: Window Controls (1:1 Windows 11 / Antigravity 2.0) -->
    <div class="flex items-center h-full shrink-0 select-none" style="-webkit-app-region: no-drag !important; pointer-events: auto !important; z-index: 9999;">
      <button onclick="windowMinimize()" title="Minimize" class="win-btn">
        <svg width="10" height="1" viewBox="0 0 10 1"><rect width="10" height="1" fill="currentColor"/></svg>
      </button>
      <button id="btn-win-max" onclick="windowMaximize()" title="Maximize" class="win-btn">
        <svg id="svg-win-max" width="10" height="10" viewBox="0 0 10 10"><path d="M1 1v8h8V1H1zm1 1h6v6H2V2z" fill="currentColor"/></svg>
        <svg id="svg-win-restore" class="hidden" width="10" height="10" viewBox="0 0 10 10"><path d="M3 1v2H1v6h6V7h2V1H3zm3 7H2V4h4v4zm2-2h-1V3H4V2h4v4z" fill="currentColor"/></svg>
      </button>
      <button onclick="windowClose()" title="Close" class="win-btn win-btn-close">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1L1 9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>

  <!-- Unified Mission Control Toolbar -->
  <div class="h-11 border-b border-hairline bg-surface-2 px-3.5 flex items-center justify-between shrink-0 text-xs select-none whitespace-nowrap overflow-hidden">
    <div class="flex items-center gap-2.5 min-w-0 flex-1 overflow-hidden">
      <div class="flex items-center gap-1.5 text-[#9D9D9D] min-w-0 shrink">
        <span class="text-[#6E6E6E] shrink-0 whitespace-nowrap">Active:</span>
        <span id="current-active-email" class="font-medium text-[#E2E8F0] truncate max-w-[170px] sm:max-w-[260px] md:max-w-[340px] inline-block align-bottom whitespace-nowrap" title="Loading...">Loading...</span>
        <span class="text-[#333333] shrink-0">•</span>
        <span id="total-accounts-count" class="text-[#6E6E6E] whitespace-nowrap shrink-0">0 accounts</span>
      </div>
      
      <!-- Quick Recommendation Button -->
      <div id="quick-rec-box" class="hidden pl-2 border-l border-hairline/60 shrink-0 whitespace-nowrap">
        <button id="btn-quick-rec" onclick="switchRecommended()" class="btn-spring text-[11px] font-medium text-accent hover:text-accent-hover flex items-center gap-1 transition-colors cursor-pointer whitespace-nowrap shrink-0">
          <span class="whitespace-nowrap">Switch to recommended</span>
          <i data-lucide="arrow-right" class="w-3 h-3 shrink-0"></i>
        </button>
      </div>
    </div>

    <div class="flex items-center gap-2 shrink-0 ml-2">
      <!-- Auto-Pilot Toggle Button -->
      <button id="btn-toggle-ap" onclick="toggleAutoPilot()" class="btn-spring h-7 px-2.5 rounded-md border text-xs font-medium flex items-center gap-1.5 transition-all duration-150 bg-surface-3 border-hairline text-[#9D9D9D] hover:text-white cursor-pointer whitespace-nowrap shrink-0">
        <span id="ap-dot" class="w-1.5 h-1.5 rounded-full bg-gray-500 shrink-0"></span>
        <span id="ap-text" class="whitespace-nowrap">Auto-Pilot: Inactive</span>
      </button>

      <!-- Refresh Button -->
      <button onclick="fetchStatus(true)" title="Refresh metrics" class="btn-spring h-7 w-7 rounded-md border border-hairline bg-surface-3 text-[#9D9D9D] hover:text-white hover:border-hairline-strong flex items-center justify-center transition-all cursor-pointer shrink-0">
        <i data-lucide="rotate-cw" class="w-3.5 h-3.5 shrink-0"></i>
      </button>
    </div>
  </div>

  <!-- Navigation Tabs -->
  <nav class="flex border-b border-hairline px-4 gap-4 sm:gap-5 text-xs shrink-0 bg-surface-2/40 overflow-x-auto whitespace-nowrap select-none">
    <div role="button" onclick="setTab('accounts')" id="tab-accounts" class="py-2.5 font-medium border-b-2 border-accent text-white transition-all cursor-pointer whitespace-nowrap shrink-0">Accounts</div>
    <div role="button" onclick="setTab('subagents')" id="tab-subagents" class="py-2.5 font-medium border-b-2 border-transparent text-[#6E6E6E] hover:text-[#CCCCCC] transition-all cursor-pointer flex items-center gap-1.5 whitespace-nowrap shrink-0">
      <span class="whitespace-nowrap">Agents Office</span>
      <span id="subagents-pulse-dot" class="w-1.5 h-1.5 rounded-full bg-emerald-400 hidden shrink-0 animate-pulse"></span>
    </div>
    <div role="button" onclick="setTab('mcp')" id="tab-mcp" class="py-2.5 font-medium border-b-2 border-transparent text-[#6E6E6E] hover:text-[#CCCCCC] transition-all cursor-pointer flex items-center gap-1.5 whitespace-nowrap shrink-0">
      <span class="whitespace-nowrap">MCP Matrix</span>
      <span id="mcp-count-badge" class="px-1.5 py-0.2 bg-surface-3 rounded text-[10px] text-gray-400 font-mono shrink-0">5</span>
    </div>
    <div role="button" onclick="setTab('logs')" id="tab-logs" class="py-2.5 font-medium border-b-2 border-transparent text-[#6E6E6E] hover:text-[#CCCCCC] transition-all cursor-pointer whitespace-nowrap shrink-0">Activity Logs</div>
    <div role="button" onclick="setTab('manage')" id="tab-manage" class="py-2.5 font-medium border-b-2 border-transparent text-[#6E6E6E] hover:text-[#CCCCCC] transition-all cursor-pointer whitespace-nowrap shrink-0">Enroll Account</div>
  </nav>

  <!-- Main Content Body -->
  <main class="flex-1 overflow-y-auto p-5">
    
    <!-- Tab 1: Accounts -->
    <div id="view-accounts" class="space-y-3.5">
      <div id="cards-container" class="space-y-3">
        <!-- Rendered via JS -->
      </div>
    </div>

    <!-- Tab 2: Agents Office & DAG -->
    <div id="view-subagents" class="hidden space-y-4">
      <!-- Session Switcher & View Switcher Bar -->
      <div class="space-y-2">
        <div class="flex items-center justify-between text-[11px] text-gray-400">
          <div class="flex items-center gap-1.5 text-gray-300 font-medium font-mono text-[11px]">
            <span>Office Switchboard & Sessions</span>
          </div>
          <div class="flex items-center gap-2">
            <!-- View Mode Switcher -->
            <div class="flex items-center bg-surface-2 p-0.5 rounded-lg border border-hairline text-[11px]">
              <button id="btn-view-pixel" onclick="setOfficeView('pixel')" class="px-2.5 py-1 rounded font-medium transition-all flex items-center gap-1.5 bg-accent/20 text-accent border border-accent/40">
                <span>Pixel HQ</span>
              </button>
              <button id="btn-view-office" onclick="setOfficeView('office')" class="px-2.5 py-1 rounded font-medium transition-all flex items-center gap-1.5 text-gray-400 hover:text-white border border-transparent">
                <span>Division Cards</span>
              </button>
              <button id="btn-view-dag" onclick="setOfficeView('dag')" class="px-2.5 py-1 rounded font-medium transition-all flex items-center gap-1.5 text-gray-400 hover:text-white border border-transparent">
                <span>DAG Tree</span>
              </button>
            </div>
            <button onclick="fetchSubagents(currentSelectedCid)" title="Refresh Telemetry" class="hover:text-white px-2 py-0.5 rounded hover:bg-surface-2 flex items-center gap-1 transition-colors text-[11px] font-mono text-gray-400 border border-hairline">
              <span>Refresh</span>
            </button>
          </div>
        </div>
        <div id="session-pills" class="flex gap-2 overflow-x-auto pb-1 font-mono text-[11px]">
          <!-- Rendered via JS -->
        </div>
      </div>

      <!-- Headquarters Summary Bar -->
      <div id="office-hq-bar" class="border border-hairline rounded-lg bg-surface p-3.5 space-y-3">
        <!-- Rendered via JS -->
      </div>

      <!-- View 1: 2D Pixel Art Office Simulation (Default) -->
      <div id="pixel-office-view" class="space-y-3">
        <!-- Pixel Controls & Room Filters Bar -->
        <div class="flex items-center justify-between px-3 py-2 bg-surface rounded-lg border border-hairline text-[11px] gap-2">
          <!-- Zone / Room Quick Filters -->
          <div class="flex items-center gap-1.5 overflow-x-auto min-w-0">
            <span class="text-[10px] font-mono text-gray-500 uppercase tracking-wider shrink-0">Zones:</span>
            <button onclick="highlightZone('all')" id="filter-zone-all" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-accent/20 border border-accent/40 text-accent font-mono transition-all">All (28)</button>
            <button onclick="highlightZone('engineering')" id="filter-zone-eng" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-purple-950/40 hover:bg-purple-900/60 border border-purple-800/60 text-purple-300 font-mono transition-all">
              Eng <b class="text-white">8</b>
            </button>
            <button onclick="highlightZone('intelligence')" id="filter-zone-intel" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-emerald-950/40 hover:bg-emerald-900/60 border border-emerald-800/60 text-emerald-300 font-mono transition-all">
              Lab <b class="text-white">6</b>
            </button>
            <button onclick="highlightZone('executive')" id="filter-zone-exec" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-blue-950/40 hover:bg-blue-900/60 border border-blue-800/60 text-blue-300 font-mono transition-all">
              Exec <b class="text-white">3</b>
            </button>
            <button onclick="highlightZone('secops')" id="filter-zone-sec" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800/60 text-amber-300 font-mono transition-all">
              War Room <b class="text-white">8</b>
            </button>
            <button onclick="highlightZone('cafe')" id="filter-zone-cafe" class="btn-spring px-2 py-0.5 rounded text-[10px] bg-orange-950/40 hover:bg-orange-900/60 border border-orange-800/60 text-orange-300 font-mono transition-all">
              Cafe <b class="text-white">3</b>
            </button>
          </div>

          <!-- Call Meeting Action Button -->
          <button onclick="callTeamMeeting()" id="btn-call-meeting" title="Call Subagents to War Room for Strategy Alignment" class="btn-spring px-2.5 py-0.5 rounded border border-amber-500/50 bg-amber-950/40 hover:bg-amber-900/60 text-amber-300 font-mono text-[10.5px] transition-all cursor-pointer shrink-0">
            <span class="font-semibold">Call Meeting</span>
          </button>

          <!-- Stage Size & CRT Overlay Tools -->
          <div class="flex items-center gap-1 shrink-0 font-mono text-[10.5px]">
            <button onclick="setPixelStageScale('fit')" id="btn-stage-fit" class="btn-spring px-2 py-0.5 rounded border border-accent/40 bg-accent/20 text-accent transition-all font-medium">Fit</button>
            <button onclick="setPixelStageScale('100')" id="btn-stage-100" class="btn-spring px-2 py-0.5 rounded border border-hairline bg-surface-2 hover:bg-surface-3 text-gray-400 hover:text-white transition-all">100%</button>
            <button onclick="setPixelStageScale('150')" id="btn-stage-150" class="btn-spring px-2 py-0.5 rounded border border-hairline bg-surface-2 hover:bg-surface-3 text-gray-400 hover:text-white transition-all">150%</button>
            <button onclick="togglePixelCrt()" id="btn-stage-crt" class="btn-spring px-2 py-0.5 rounded border border-hairline bg-surface-2 hover:bg-surface-3 text-gray-400 hover:text-white transition-all">CRT</button>
          </div>
        </div>

        <!-- Master Pixel Viewport Container -->
        <div id="pixel-stage-container" class="relative w-full rounded-xl overflow-auto border border-hairline shadow-2xl bg-[#09090d] select-none flex items-center justify-center p-3">
          <div id="pixel-stage" class="relative overflow-hidden rounded-lg shadow-2xl max-w-full" style="width: 860px; max-width: 100%; aspect-ratio: 768 / 512;">
            <!-- Interactive 768x512 HTML5 Canvas Pixel Office Engine -->
            <canvas id="pixel-office-canvas" width="768" height="512" class="w-full h-full block cursor-pointer select-none" style="image-rendering: pixelated;"></canvas>
            <!-- CRT Arcade Scanlines Overlay -->
            <div id="pixel-crt-overlay" class="absolute inset-0 pointer-events-none crt-scanlines opacity-0 transition-opacity duration-300 z-40"></div>
            <!-- Dynamic Floating Telemetry HUD Tooltip on Hover -->
            <div id="pixel-canvas-tooltip" class="absolute pointer-events-none z-50 opacity-0 transition-opacity duration-150 transform -translate-x-1/2 -translate-y-full mb-3" style="left: 0px; top: 0px;">
              <div id="pixel-canvas-tooltip-body" class="bg-[#0d0d14]/95 border border-hairline rounded-lg p-2.5 shadow-2xl backdrop-blur-md min-w-[210px] text-left">
                <!-- Populated dynamically via JS -->
              </div>
            </div>
          </div>
        </div>

        <!-- Bottom Legend & Interaction Guidance -->
        <div class="flex items-center justify-between text-[10px] font-mono text-gray-400 px-3 py-1 bg-surface-2/40 rounded border border-hairline">
          <div class="flex items-center gap-3">
            <span><b class="text-white">Hover:</b> Agent Telemetry HUD</span>
            <span><b class="text-white">Zones:</b> Filter Room</span>
            <span><b class="text-white">CRT:</b> Retro Arcade Scanlines</span>
          </div>
          <span class="text-accent font-semibold flex items-center gap-1">Click agent sprite to open Dossier &rarr;</span>
        </div>

        <!-- Commander Console & HQ Intercom Dock -->
        <div id="commander-console-dock" class="rounded-xl border border-hairline bg-[#0a0c14] overflow-hidden shadow-2xl transition-all">
          <!-- Dock Header -->
          <div class="px-3.5 py-2 bg-surface-2/60 border-b border-hairline flex items-center justify-between text-xs select-none">
            <div class="flex items-center gap-2 min-w-0">
              <span class="relative flex h-2 w-2 shrink-0">
                <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span class="relative inline-flex rounded-full h-2 w-2 bg-cyan-500"></span>
              </span>
              <span class="font-bold text-white font-mono text-[11px] truncate">
                COMMANDER CONSOLE & HQ INTERCOM
              </span>
              <span class="text-[10px] text-gray-500 font-mono hidden md:inline shrink-0">• 28 Agents Online</span>
            </div>

            <!-- Quick Directives Chips -->
            <div class="flex items-center gap-1.5 overflow-x-auto text-[10px] font-mono shrink-0 ml-2">
              <button onclick="sendQuickDirective('meeting')" title="Panggil seluruh divisi ke War Room" class="btn-spring px-2 py-0.5 rounded bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800/60 text-amber-300 transition-all cursor-pointer">
                <span>Rapat Divisi</span>
              </button>
              <button onclick="sendQuickDirective('break')" title="Rehat ke Espresso Lounge" class="btn-spring px-2 py-0.5 rounded bg-orange-950/40 hover:bg-orange-900/60 border border-orange-800/60 text-orange-300 transition-all cursor-pointer">
                <span>Rehat Kopi</span>
              </button>
              <button onclick="sendQuickDirective('secops')" title="Instruksikan SecOps Audit" class="btn-spring px-2 py-0.5 rounded bg-amber-950/40 hover:bg-amber-900/60 border border-amber-800/60 text-amber-300 transition-all cursor-pointer">
                <span>SecOps Audit</span>
              </button>
              <button onclick="sendQuickDirective('engineering')" title="Instruksikan Sprint Build" class="btn-spring px-2 py-0.5 rounded bg-purple-950/40 hover:bg-purple-900/60 border border-purple-800/60 text-purple-300 transition-all cursor-pointer">
                <span>Sprint Build</span>
              </button>
              <button onclick="toggleConsoleDock()" id="btn-toggle-console" title="Collapse/Expand Console" class="text-gray-400 hover:text-white px-1.5 py-0.5 rounded hover:bg-surface-3 transition-colors ml-1 cursor-pointer font-mono text-[10px]">
                <span id="label-toggle-console">[Hide]</span>
              </button>
            </div>
          </div>

          <!-- Dock Body -->
          <div id="commander-console-body" class="p-3 space-y-2.5">
            <!-- Message Stream Log -->
            <div id="commander-chat-stream" class="h-32 overflow-y-auto space-y-1.5 p-2.5 rounded-lg bg-[#06080d] border border-hairline font-mono text-[11px] leading-relaxed scrollbar-thin">
              <!-- Initial Welcome Messages -->
              <div class="flex items-start gap-2 text-gray-500 text-[10.5px]">
                <span class="shrink-0 text-cyan-500 font-bold">[SYSTEM]</span>
                <span>HQ Intercom Online • Mode: Dual-Intent Dispatcher siap menerima instruksi.</span>
              </div>
              <div class="flex items-start gap-2 text-slate-300 text-[10.5px]">
                <span class="shrink-0 text-cyan-400 font-bold">[Root Orchestrator]</span>
                <span>Selamat datang, Commander. 28 agen standby di pos masing-masing. Berikan instruksi kapan saja.</span>
              </div>
            </div>

            <!-- Control & Input Bar -->
            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-[10.5px] font-mono px-1">
                <div class="flex items-center gap-2">
                  <span class="text-gray-400">Mode:</span>
                  <label class="flex items-center gap-1.5 cursor-pointer select-none">
                    <input type="checkbox" id="chk-live-token-mode" onchange="updateConsoleModeBadge()" class="rounded bg-surface-2 border-hairline text-cyan-500 focus:ring-0 w-3.5 h-3.5 cursor-pointer">
                    <span id="console-mode-badge" class="px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-emerald-950/60 border border-emerald-800/60 text-emerald-400 transition-all">
                      [0-Token] Visual Office Directive
                    </span>
                  </label>
                </div>
                <span id="console-mode-hint" class="text-gray-500 text-[9.5px]">Gratis kuota • Eksekusi lokal instan</span>
              </div>

              <!-- Input Form -->
              <div class="flex items-center gap-2">
                <div class="relative flex-1">
                  <input id="commander-input" type="text" onkeydown="handleCommanderKey(event)" placeholder="Ketik perintah (contoh: 'ayo masing masing divisi ikut rapat, ada yang gua mau ngomongin')..." class="w-full bg-[#07090f] border border-hairline rounded-lg px-3 py-1.5 text-xs text-white placeholder-gray-600 focus:outline-none focus:border-cyan-500/80 font-mono transition-colors">
                </div>
                <button onclick="dispatchCommanderCommand()" id="btn-commander-send" class="btn-spring px-4 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold transition-all shadow-lg shadow-cyan-900/30 cursor-pointer shrink-0">
                  Send
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- View 2: Office Floor (Department Grid) -->
      <div id="office-floor-view" class="hidden space-y-4">
        <div id="office-departments-grid" class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
          <!-- Rendered via JS: Executive, Intelligence, Engineering, SecOps -->
        </div>
      </div>

      <!-- View 2: Classic DAG Tree -->
      <div id="dag-tree-view" class="hidden border border-hairline rounded-lg bg-surface p-4 space-y-3">
        <div class="flex items-center justify-between border-b border-hairline pb-2.5">
          <div class="flex items-center gap-2">
            <span class="text-xs font-semibold text-white">Agent Execution DAG</span>
          </div>
          <span id="dag-node-count" class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-2 text-gray-400 border border-hairline">1 Node</span>
        </div>

        <div id="dag-tree-content" class="space-y-3">
          <!-- Rendered via JS -->
        </div>
      </div>
    </div>

    <!-- Tab: MCP Matrix -->
    <div id="view-mcp" class="hidden space-y-4">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-xs font-semibold text-white">Model Context Protocol (MCP) Servers</h3>
          <p class="text-[11px] text-gray-400">Supervises local tools and stdio JSON-RPC connections</p>
        </div>
        <button onclick="fetchMcp()" class="h-7 px-3 rounded bg-surface-2 hover:bg-surface-3 border border-hairline text-gray-300 text-xs flex items-center gap-1.5 transition-all">
          <i data-lucide="refresh-cw" class="w-3 h-3"></i>
          <span>Refresh</span>
        </button>
      </div>

      <div id="mcp-cards-container" class="grid grid-cols-1 gap-3">
        <!-- Rendered via JS -->
      </div>

      <div class="border border-hairline rounded-lg bg-surface/50 p-3 text-[11px] text-gray-500 space-y-1">
        <div class="font-medium text-gray-400">About MCP Stdio Lifecycle:</div>
        <div>Antigravity lazy-loads MCP servers on-demand when an agent calls a relevant tool. If a server process terminates or hangs, use the <strong>Ping Probe</strong> or <strong>Restart</strong> button to reset it to a clean standby state.</div>
      </div>
    </div>

    <!-- Tab 2: Activity Logs -->
    <div id="view-logs" class="hidden space-y-3">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs text-gray-400 font-medium">Overnight Auto-Pilot Events</span>
        <button onclick="clearLogs()" class="text-[11px] text-gray-500 hover:text-red-400 transition-colors">Clear Log</button>
      </div>
      <div class="border border-hairline rounded-lg bg-surface overflow-hidden">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-hairline bg-surface-2 text-gray-500 text-[10px] uppercase font-mono tracking-wider">
              <th class="py-2 px-3 w-28">Timestamp</th>
              <th class="py-2 px-2 w-20">Type</th>
              <th class="py-2 px-3">Description</th>
            </tr>
          </thead>
          <tbody id="logs-table-body" class="divide-y divide-hairline font-mono text-[11px] text-gray-300">
            <!-- Rendered via JS -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 3: Enroll Account -->
    <div id="view-manage" class="hidden space-y-4">
      <div class="border border-hairline rounded-lg bg-surface p-5 space-y-3">
        <h3 class="text-sm font-semibold text-white">Enroll New Google Account</h3>
        <p class="text-xs text-gray-400 leading-relaxed">
          Launches an isolated Antigravity sign-in session. Your current active session is preserved safely. Once you sign into Google in the Antigravity window, the account is automatically enrolled into this controller.
        </p>
        <button onclick="enrollAccount()" class="h-8 px-4 rounded-md bg-accent hover:bg-accent-hover text-white text-xs font-semibold flex items-center gap-1.5 transition-all">
          <i data-lucide="plus" class="w-3.5 h-3.5"></i>
          <span>Sign In With Google</span>
        </button>
      </div>

      <div class="border border-hairline rounded-lg bg-surface/50 p-4 space-y-2 text-xs text-gray-500">
        <div class="font-medium text-gray-400">Architecture & Persistence</div>
        <ul class="space-y-1 text-[11.5px] leading-relaxed list-disc list-inside">
          <li>Credentials stored natively in Windows Credential Manager under <code class="text-gray-400">gemini:antigravity</code>.</li>
          <li>Workspace context and conversation databases remain 100% persistent across account switches.</li>
          <li>Auto-Pilot runs in a lightweight background daemon and recovers tasks via Chrome DevTools Protocol (CDP).</li>
        </ul>
      </div>
    </div>

  </main>

  <!-- Employee Dossier Modal -->
  <div id="employee-dossier-modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 hidden">
    <div class="bg-[#141414] border border-hairline-strong rounded-xl max-w-lg w-full p-5 space-y-4 shadow-2xl relative max-h-[85vh] flex flex-col">
      <div class="flex items-start justify-between border-b border-hairline pb-3">
        <div class="flex items-center gap-3 min-w-0">
          <div id="dossier-avatar" class="w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm shrink-0"></div>
          <div class="min-w-0">
            <h3 id="dossier-role" class="text-sm font-semibold text-white truncate"></h3>
            <p id="dossier-sub" class="text-[11px] font-mono text-gray-400 truncate"></p>
          </div>
        </div>
        <button onclick="closeEmployeeDossier()" class="text-gray-400 hover:text-white px-2 py-0.5 rounded hover:bg-surface-2 transition-colors shrink-0 font-mono text-xs">
          [X]
        </button>
      </div>

      <div id="dossier-content" class="space-y-3 text-xs overflow-y-auto pr-1 flex-1">
        <!-- Rendered via JS -->
      </div>

      <div class="border-t border-hairline pt-3 flex justify-end">
        <button onclick="closeEmployeeDossier()" class="px-3.5 py-1.5 bg-surface-2 hover:bg-surface-3 border border-hairline text-gray-300 rounded text-xs transition-colors">
          Close Dossier
        </button>
      </div>
    </div>
  </div>

  <script>
    /* __INITIAL_STATE_PLACEHOLDER__ */
    let state = (typeof window.__INITIAL_STATE__ !== 'undefined' && window.__INITIAL_STATE__) ? window.__INITIAL_STATE__ : {
      active: '',
      accounts: [],
      quotas: {},
      autopilot: false,
      logs: [],
      best: null
    };

    let currentTab = 'accounts';
    let currentSelectedCid = null;
    let subagentsPollingTimer = null;
    let mcpPollingTimer = null;

    // --- Antigravity App Launch Loading Screen Controller ---
    const appLaunchStartTime = performance.now();
    let appLoaderDismissed = false;

    function dismissAppLoader() {
      if (appLoaderDismissed) return;
      appLoaderDismissed = true;
      const loader = document.getElementById('app-launch-loader');
      if (!loader) return;
      loader.style.opacity = '0';
      loader.style.pointerEvents = 'none';
      setTimeout(() => {
        loader.style.visibility = 'hidden';
        loader.style.display = 'none';
      }, 550);
    }

    function scheduleLoaderDismissal() {
      const elapsed = performance.now() - appLaunchStartTime;
      const minDisplayTime = 40; // Immediate transition since native Qt splash screen covers launch phase
      const remaining = Math.max(0, minDisplayTime - elapsed);
      setTimeout(dismissAppLoader, remaining);
    }

    window.addEventListener('load', () => scheduleLoaderDismissal());
    setTimeout(dismissAppLoader, 1200); // Failsafe safety fallback

    // --- React Bits: SpotlightCard Mouse Tracking ---
    function initSpotlightCards() {
      document.querySelectorAll('.spotlight-card').forEach(card => {
        if (card.dataset.spotlightBound) return;
        card.dataset.spotlightBound = "true";
        card.addEventListener('mousemove', (e) => {
          const rect = card.getBoundingClientRect();
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          card.style.setProperty('--mouse-x', `${x}px`);
          card.style.setProperty('--mouse-y', `${y}px`);
        });
      });
    }

    // --- React Bits: DecryptedText Cyber Scramble ---
    let lastDecryptedEmail = '';
    function decryptScramble(element, targetText, duration = 380) {
      if (!element || !targetText) return;
      if (targetText === lastDecryptedEmail) return;
      lastDecryptedEmail = targetText;
      const chars = '0123456789!@#$%&*ABCDEF_';
      const len = targetText.length;
      let frame = 0;
      const totalFrames = Math.floor(duration / 30);
      const interval = setInterval(() => {
        frame++;
        const progress = frame / totalFrames;
        const revealedCount = Math.floor(progress * len);
        let result = targetText.substring(0, revealedCount);
        for (let i = revealedCount; i < len; i++) {
          result += chars[Math.floor(Math.random() * chars.length)];
        }
        element.textContent = result;
        if (frame >= totalFrames) {
          clearInterval(interval);
          element.textContent = targetText;
        }
      }, 30);
    }

    // --- React Bits: CountUp Smooth Number Animation ---
    function animateCountUp(element, endVal, duration = 400) {
      if (!element) return;
      const startVal = parseFloat(element.dataset.currentVal || '0');
      element.dataset.currentVal = endVal;
      if (startVal === endVal) {
        element.textContent = `${endVal.toFixed(0)}%`;
        return;
      }
      const startTime = performance.now();
      function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const ease = 1 - Math.pow(1 - progress, 3);
        const current = startVal + (endVal - startVal) * ease;
        element.textContent = `${current.toFixed(0)}%`;
        if (progress < 1) {
          requestAnimationFrame(update);
        } else {
          element.textContent = `${endVal.toFixed(0)}%`;
        }
      }
      requestAnimationFrame(update);
    }

    function setTab(tab) {
      currentTab = tab;
      ['accounts', 'subagents', 'mcp', 'logs', 'manage'].forEach(t => {
        const el = document.getElementById('view-' + t);
        if (el) el.classList.add('hidden');
        const btn = document.getElementById('tab-' + t);
        if (btn) {
          btn.classList.remove('border-accent', 'text-white');
          btn.classList.add('border-transparent', 'text-[#6E6E6E]');
        }
      });
      const activeView = document.getElementById('view-' + tab);
      if (activeView) {
        activeView.classList.remove('hidden');
        activeView.classList.remove('tab-animated-enter');
        void activeView.offsetWidth; // trigger reflow for smooth spring enter
        activeView.classList.add('tab-animated-enter');
      }
      const activeBtn = document.getElementById('tab-' + tab);
      if (activeBtn) {
        activeBtn.classList.remove('border-transparent', 'text-[#6E6E6E]');
        activeBtn.classList.add('border-accent', 'text-white');
      }

      if (subagentsPollingTimer) clearInterval(subagentsPollingTimer);
      if (mcpPollingTimer) clearInterval(mcpPollingTimer);

      if (tab === 'subagents') {
        setOfficeView(currentOfficeViewMode);
        fetchSubagents(currentSelectedCid);
        subagentsPollingTimer = setInterval(() => {
          if (currentTab === 'subagents') fetchSubagents(currentSelectedCid);
        }, 3500);
      } else if (tab === 'mcp') {
        fetchMcp();
        mcpPollingTimer = setInterval(() => {
          if (currentTab === 'mcp') fetchMcp();
        }, 8000);
      }
      lucide.createIcons();
      initSpotlightCards();
    }

    async function fetchSubagents(cid = null) {
      try {
        const url = cid ? `/api/subagents?cid=${encodeURIComponent(cid)}` : '/api/subagents';
        const res = await fetch(url);
        const data = await res.json();
        renderSubagents(data);
      } catch (e) {
        console.error("Error fetching subagents:", e);
      }
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    let currentOfficeViewMode = 'pixel';
    let officeStaffRegistry = [];
    let initialDossier = null;
    let currentPixelStageScale = 'fit';
    let pixelCrtActive = false;
    let activeZoneFilter = 'all';

    // Injected Base64 Assets Bundle from Python
    const PIXEL_ASSETS_DATA = /* __PIXEL_ASSETS_BUNDLE__ */ {};
    const PIXEL_IMAGES = {};
    let pixelAssetsReady = false;
    let fMahogany = null, fTechBlue = null, fEmerald = null, fAmber = null, fViolet = null, fCorridor = null;

    // Preload all pixel art assets
    function initPixelAssets(onReady) {
      let keys = Object.keys(PIXEL_ASSETS_DATA);
      if (keys.length === 0) {
        // Fallback fetch from API if not inlined
        fetch('/api/pixel-assets').then(r => r.json()).then(data => {
          Object.assign(PIXEL_ASSETS_DATA, data);
          initPixelAssets(onReady);
        }).catch(e => console.error("Failed to load pixel assets:", e));
        return;
      }

      let loadedCount = 0;
      const total = keys.length;

      keys.forEach(k => {
        const img = new Image();
        img.onload = () => {
          loadedCount++;
          if (loadedCount === total) {
            setupTintedFloors();
            pixelAssetsReady = true;
            console.log("[PixelEngine] 71 authentic pixel assets loaded!");
            if (onReady) onReady();
          }
        };
        img.src = PIXEL_ASSETS_DATA[k];
        PIXEL_IMAGES[k] = img;
      });
    }

    function create2ToneFloor(baseImg, cLight, cDark) {
      if (!baseImg) return null;
      const c = document.createElement('canvas');
      c.width = 16; c.height = 16;
      const cx = c.getContext('2d');
      cx.drawImage(baseImg, 0, 0);
      const imgData = cx.getImageData(0, 0, 16, 16);
      const d = imgData.data;

      let minLum = 255, maxLum = 0;
      for (let i = 0; i < d.length; i += 4) {
        const lum = d[i] * 0.299 + d[i+1] * 0.587 + d[i+2] * 0.114;
        if (lum < minLum) minLum = lum;
        if (lum > maxLum) maxLum = lum;
      }
      const midLum = (minLum + maxLum) / 2;

      for (let i = 0; i < d.length; i += 4) {
        const lum = d[i] * 0.299 + d[i+1] * 0.587 + d[i+2] * 0.114;
        const color = (lum >= midLum) ? cLight : cDark;
        d[i]   = color[0];
        d[i+1] = color[1];
        d[i+2] = color[2];
        d[i+3] = 255;
      }
      cx.putImageData(imgData, 0, 0);
      return c;
    }

    function setupTintedFloors() {
      const f1 = PIXEL_IMAGES['assets/floors/floor_1.png'];
      const f3 = PIXEL_IMAGES['assets/floors/floor_3.png'];
      const f6 = PIXEL_IMAGES['assets/floors/floor_6.png'];
      const f7 = PIXEL_IMAGES['assets/floors/floor_7.png'];
      if (!f1 || !f3 || !f6 || !f7) return;

      fMahogany = create2ToneFloor(f6, [125, 72, 45], [78, 42, 24]);     // War Room: Real Mahogany Planks
      fTechBlue = create2ToneFloor(f3, [34, 48, 70], [20, 28, 42]);      // Recon: Tech Slate Grid
      fEmerald  = create2ToneFloor(f3, [28, 54, 44], [16, 34, 28]);      // Engineering: Matrix Grid
      fAmber    = create2ToneFloor(f6, [170, 120, 72], [115, 76, 42]);   // Knowledge: Honey Oak Planks
      fViolet   = create2ToneFloor(f3, [48, 38, 66], [28, 22, 40]);      // QA: Tactical Violet Grid
      fCafe     = create2ToneFloor(f7, [215, 210, 200], [45, 40, 45]);   // Breakroom: High-contrast Checker
      fCorridor = create2ToneFloor(f6, [145, 100, 62], [95, 62, 38]);    // Corridor: Warm Hardwood Parquet
    }

    // 28 Specialized Agent Workstations with Spaced Badges (Discrete 48x32 Grid, TILE_SIZE = 16px)
    const OFFICE_STATIONS = [
      // 1. Executive Suite / War Room (3 Stations)
      { id: 'exec_1', col: 6, row: 7, dir: 'right', dept: 'executive', title: 'Lead Orchestrator (Root)', defaultTool: 'invoke_subagent', toolSummary: 'Autonomous Primary Loop & Strategy', status: 'WORKING', isPrimary: true, badge_ox: -30, badge_oy: -24 },
      { id: 'exec_2', col: 10, row: 7, dir: 'left', dept: 'executive', title: 'Strategic Advisor', defaultTool: 'sync_plan', toolSummary: 'High-Level Architectural Review', status: 'IN_MEETING', badge_ox: 30, badge_oy: -24 },
      { id: 'exec_3', col: 6, row: 9, dir: 'right', dept: 'executive', title: 'Chief Systems Architect', defaultTool: 'break', toolSummary: 'System Blueprinting & Roadmap', status: 'STANDBY', badge_ox: -28, badge_oy: -12 },

      // 2. Intelligence & Recon Lab (4 Stations)
      { id: 'lab_1', col: 19, row: 6, dir: 'up', dept: 'intelligence', title: 'Model Evaluator', defaultTool: 'eval_prompt', toolSummary: 'Prompt Perplexity & Reasoning Audit', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'lab_2', col: 25, row: 6, dir: 'up', dept: 'intelligence', title: 'Knowledge Miner', defaultTool: 'grep_search', toolSummary: 'DemusBrain Vault Indexing & MOC Sync', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'lab_3', col: 19, row: 10, dir: 'up', dept: 'intelligence', title: 'Server Infra SRE', defaultTool: 'psutil_check', toolSummary: 'Hardware Telemetry & Process Watcher', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'lab_4', col: 25, row: 10, dir: 'up', dept: 'intelligence', title: 'Data Pipeline Analyst', defaultTool: 'view_file', toolSummary: 'Telemetry & Token Flow Lineage Audit', status: 'IN_MEETING', badge_ox: 0, badge_oy: -26 },

      // 3. Autonomous Engineering Hub (8 Stations)
      { id: 'eng_1', col: 34, row: 5, dir: 'up', dept: 'engineering', title: 'Frontend Engineer', defaultTool: 'write_to_file', toolSummary: 'UI & Micro-Interactions (React Bits)', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_2', col: 39, row: 5, dir: 'up', dept: 'engineering', title: 'Backend Core Dev', defaultTool: 'run_command', toolSummary: 'FastAPI / WebSocket Pipeline', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_3', col: 43, row: 5, dir: 'up', dept: 'engineering', title: 'Systems Refactorer', defaultTool: 'replace_file_content', toolSummary: 'Surgical Edits & AST Optimization', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_4', col: 34, row: 9, dir: 'up', dept: 'engineering', title: 'DevOps & SRE', defaultTool: 'manage_task', toolSummary: 'CI/CD Pipeline & Windows PyInstaller', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_5', col: 39, row: 9, dir: 'up', dept: 'engineering', title: 'Fullstack Engineer', defaultTool: 'write_to_file', toolSummary: 'Feature Integration & DoD Validation', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_6', col: 43, row: 9, dir: 'up', dept: 'engineering', title: 'Algorithm Specialist', defaultTool: 'eval_metric', toolSummary: 'Performance Tuning & Latency Benchmarks', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_7', col: 34, row: 12, dir: 'up', dept: 'engineering', title: 'Lead Architect', defaultTool: 'view_file', toolSummary: 'Codebase Verification & Quality Standard', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'eng_8', col: 39, row: 12, dir: 'up', dept: 'engineering', title: 'Release Automator', defaultTool: 'run_command', toolSummary: 'GitHub Actions Release & Distribution', status: 'WORKING', badge_ox: 0, badge_oy: -26 },

      // 4. Knowledge Vault & Library (4 Stations)
      { id: 'lib_1', col: 5, row: 23, dir: 'up', dept: 'intelligence', title: 'Research Fellow', defaultTool: 'read_url_content', toolSummary: 'Technical RFC & Academic Paper Review', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'lib_2', col: 10, row: 23, dir: 'up', dept: 'intelligence', title: 'Docs Archivist', defaultTool: 'write_to_file', toolSummary: 'Permanent Knowledge Compounding', status: 'STANDBY', badge_ox: 0, badge_oy: -26 },
      { id: 'lib_3', col: 5, row: 27, dir: 'up', dept: 'intelligence', title: 'Ontology Curator', defaultTool: 'eval_prompt', toolSummary: 'Knowledge Graph Topology', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'lib_4', col: 10, row: 27, dir: 'up', dept: 'intelligence', title: 'Knowledge Sync', defaultTool: 'view_file', toolSummary: 'DemusBrain Vault Synchronization', status: 'WORKING', badge_ox: 0, badge_oy: -26 },

      // 5. QA, Verification & SecOps (6 Stations)
      { id: 'sec_6', col: 19, row: 22, dir: 'up', dept: 'secops', title: 'QA Audit Lead', defaultTool: 'dod_verify', toolSummary: 'Definition of Done Verification', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'sec_7', col: 25, row: 22, dir: 'up', dept: 'secops', title: 'Code Validator', defaultTool: 'lint_check', toolSummary: 'Syntax, TypeCheck & Linter Enforcement', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'sec_8', col: 19, row: 26, dir: 'up', dept: 'secops', title: 'DAG Supervisor', defaultTool: 'dag_watch', toolSummary: 'Subagent Lifecycle & Process Supervisor', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'sec_5', col: 25, row: 26, dir: 'up', dept: 'secops', title: 'Incident Commander', defaultTool: 'war_room', toolSummary: 'Incident Triage & War Room Lead', status: 'WORKING', badge_ox: 0, badge_oy: -26 },
      { id: 'sec_1', col: 10, row: 9, dir: 'left', dept: 'secops', title: 'Security Sentinel', defaultTool: 'threat_watch', toolSummary: 'Threat Monitoring & Zero-Trust Verification', status: 'IN_MEETING', badge_ox: 28, badge_oy: -12 },
      { id: 'sec_2', col: 8, row: 11, dir: 'up', dept: 'secops', title: 'Penetration Tester', defaultTool: 'vuln_probe', toolSummary: 'Attack Surface Enumeration & Fuzzing', status: 'IN_MEETING', badge_ox: 0, badge_oy: -26 },

      // 6. Breakroom & Lounge (3 Stations)
      { id: 'cafe_1', col: 34, row: 20, dir: 'down', dept: 'executive', title: 'Espresso Standby Agent', defaultTool: 'break', toolSummary: 'Espresso Break & Brainstorming', status: 'STANDBY', badge_ox: 0, badge_oy: -26 },
      { id: 'cafe_2', col: 38, row: 23, dir: 'right', dept: 'engineering', title: 'Standby Developer', defaultTool: 'break', toolSummary: 'Code Review & Coffee Chat', status: 'STANDBY', badge_ox: -26, badge_oy: -22 },
      { id: 'cafe_3', col: 42, row: 23, dir: 'left', dept: 'secops', title: 'Standby Sentinel', defaultTool: 'break', toolSummary: 'Recharge & Standby Watch', status: 'STANDBY', badge_ox: 26, badge_oy: -22 }
    ];

    // Clean Role Map for Badges
    const ROLE_BADGE_MAP = {
      'Frontend Engineer': 'Frontend Dev',
      'Backend Core Dev': 'Backend Dev',
      'Systems Refactorer': 'Refactorer',
      'DevOps & SRE': 'DevOps SRE',
      'Fullstack Engineer': 'Fullstack',
      'Algorithm Specialist': 'Algorithms',
      'Lead Architect': 'Lead Arch',
      'Release Automator': 'Release Auto',
      'Model Evaluator': 'Model Eval',
      'Knowledge Miner': 'Knowledge',
      'Server Infra SRE': 'Infra SRE',
      'Data Pipeline Analyst': 'Data Pipeline',
      'Lead Orchestrator (Root)': 'Root Orchestrator',
      'Strategic Advisor': 'Strategy Lead',
      'Chief Systems Architect': 'Chief Arch',
      'Research Fellow': 'Researcher',
      'Docs Archivist': 'Docs Archivist',
      'Espresso Standby Agent': 'Espresso',
      'Standby Developer': 'Standby Dev',
      'Standby Sentinel': 'Sentinel',
      'Security Sentinel': 'SecOps Sentinel',
      'Penetration Tester': 'Pentester',
      'Red Team Hunter': 'Red Team',
      'Compliance Guard': 'Compliance',
      'Incident Commander': 'Incident Lead',
      'QA Audit Lead': 'QA Lead',
      'Code Validator': 'Code Validator',
      'DAG Supervisor': 'DAG Supervisor'
    };

    function getFormattedRole(rawRole) {
      if (!rawRole) return 'Staff Agent';
      if (ROLE_BADGE_MAP[rawRole]) return ROLE_BADGE_MAP[rawRole];
      return rawRole.replace(' (Root)', '').replace(' Engineer', ' Dev');
    }

    // ── AGENT LIFECYCLE ANIMATION STATE MACHINE ──
    // Meeting positions around the War Room conference table (visiting subagents stand here)
    const MEETING_POSITIONS = [
      { col: 8, row: 5, dir: 'down', title: 'Strategy Lead' },    // Head of table (top)
      { col: 8, row: 10, dir: 'up', title: 'Engineering Rep' },   // Foot of table (bottom)
      { col: 5, row: 8, dir: 'right', title: 'Intelligence Rep' }, // Left side (facing table)
      { col: 11, row: 8, dir: 'left', title: 'SecOps Rep' }       // Right side (facing table)
    ];

    // Per-station animation state tracker (keyed by slot.id)
    const agentAnimState = {};
    let lastAmbientMeetingFrame = 0;
    // Ambient meeting loop completely disabled - meetings strictly user-initiated or real subagent driven
    let nextAmbientMeetingFrame = Infinity;
    const MEETING_DURATION = 800;   // frames in meeting (~13.3s at 60fps for full animated deliberative conversation)
    const WORKING_DURATION = 600;   // frames working after meeting (~10s at 60fps)
    const WALK_SPEED = 2.4;         // pixels per frame (smooth walking pace)

    function getRoomDoorCol(col, row) {
      if (col < 16) return 8;
      if (col < 31) return 24;
      return 39;
    }

    // Compute door-aware waypoint route from desk to War Room meeting position
    function computeRouteToMeeting(deskCol, deskRow, slotDir, meetPos) {
      const CORRIDOR_Y = 15 * 16 + 2;  // Central corridor crimson runner Y (y=242)
      const route = [];
      const startX = deskCol * 16;
      const startY = slotDir === 'up' ? (deskRow - 1) * 16 + 18 : deskRow * 16 - 4;
      const doorCol = getRoomDoorCol(deskCol, deskRow);
      const doorX = doorCol * 16;
      const warRoomDoorX = 8 * 16;
      const meetX = meetPos.col * 16;
      const meetY = meetPos.row * 16 - 4;

      // 1. Exit room through its designated doorway into the central corridor
      if (deskRow <= 14) {
        route.push({ x: startX, y: 13 * 16 });
        route.push({ x: doorX, y: 13 * 16 });
        route.push({ x: doorX, y: CORRIDOR_Y });
      } else {
        route.push({ x: startX, y: 17 * 16 });
        route.push({ x: doorX, y: 17 * 16 });
        route.push({ x: doorX, y: CORRIDOR_Y });
      }

      // 2. Walk along crimson corridor runner to War Room portal
      route.push({ x: warRoomDoorX, y: CORRIDOR_Y });

      // 3. Step through War Room portal
      route.push({ x: warRoomDoorX, y: 13 * 16 });

      // 4. Navigate around conference table (table: cols 7..9, rows 6..9)
      if (meetPos.col === 8 && meetPos.row <= 6) {
        // Head of table: route around left flank
        route.push({ x: 5 * 16, y: 13 * 16 });
        route.push({ x: 5 * 16, y: meetY });
        route.push({ x: meetX, y: meetY });
      } else if (meetPos.col === 8 && meetPos.row >= 10) {
        // Foot of table: straight up
        route.push({ x: meetX, y: meetY });
      } else {
        // Left or right flank
        route.push({ x: meetX, y: 13 * 16 });
        route.push({ x: meetX, y: meetY });
      }

      return { route, startX, startY };
    }

    // Compute door-aware return route from meeting position back to desk
    function computeRouteToDesk(meetPos, deskCol, deskRow, slotDir) {
      const CORRIDOR_Y = 15 * 16 + 2;
      const route = [];
      const meetX = meetPos.col * 16;
      const meetY = meetPos.row * 16 - 4;
      const warRoomDoorX = 8 * 16;
      const doorCol = getRoomDoorCol(deskCol, deskRow);
      const doorX = doorCol * 16;
      const destX = deskCol * 16;
      const destY = slotDir === 'up' ? (deskRow - 1) * 16 + 18 : deskRow * 16 - 4;

      // 1. Depart meeting position back to War Room doorway
      if (meetPos.col === 8 && meetPos.row <= 6) {
        route.push({ x: 5 * 16, y: meetY });
        route.push({ x: 5 * 16, y: 13 * 16 });
        route.push({ x: warRoomDoorX, y: 13 * 16 });
      } else {
        route.push({ x: meetX, y: 13 * 16 });
        route.push({ x: warRoomDoorX, y: 13 * 16 });
      }

      // 2. Step through doorway into central corridor runner
      route.push({ x: warRoomDoorX, y: CORRIDOR_Y });

      // 3. Walk along corridor to destination room entrance
      route.push({ x: doorX, y: CORRIDOR_Y });

      // 4. Enter destination room
      if (deskRow <= 14) {
        route.push({ x: doorX, y: 13 * 16 });
        route.push({ x: destX, y: 13 * 16 });
      } else {
        route.push({ x: doorX, y: 17 * 16 });
        route.push({ x: destX, y: 17 * 16 });
      }

      // 5. Arrive at desk workstation
      route.push({ x: destX, y: destY });

      return route;
    }

    // Update all agent animations each frame
    function updateAgentAnimations() {
      for (const slotId in agentAnimState) {
        const anim = agentAnimState[slotId];
        if (!anim || anim.state === 'idle' || anim.state === 'working_at_desk') continue;

        // Handle stagger delay before walking starts
        if (anim.delayFrames > 0) {
          anim.delayFrames--;
          continue;
        }

        if (anim.state === 'walk_to_meeting' || anim.state === 'walk_to_desk') {
          if (anim.routeIdx < anim.route.length) {
            const target = anim.route[anim.routeIdx];
            const dx = target.x - anim.px;
            const dy = target.y - anim.py;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < WALK_SPEED + 0.5) {
              // Reached waypoint
              anim.px = target.x;
              anim.py = target.y;
              anim.routeIdx++;
            } else {
              // Move toward waypoint
              anim.px += (dx / dist) * WALK_SPEED;
              anim.py += (dy / dist) * WALK_SPEED;
            }

            // Update facing direction based on dominant movement axis
            if (Math.abs(dx) > Math.abs(dy) + 0.5) {
              anim.walkDir = dx > 0 ? 'right' : 'left';
            } else if (Math.abs(dy) > 0.5) {
              anim.walkDir = dy > 0 ? 'down' : 'up';
            }
          } else {
            // Route complete — transition to next state
            if (anim.state === 'walk_to_meeting') {
              anim.state = 'in_meeting';
              anim.meetingTimer = 0;
              anim.walkDir = anim.meetingPos.dir;  // Face toward table
            } else {
              // Arrived back at desk
              anim.state = 'working_at_desk';
              anim.workingTimer = 0;
            }
          }
        } else if (anim.state === 'in_meeting') {
          anim.meetingTimer++;
          if (anim.meetingTimer >= MEETING_DURATION) {
            // Meeting over — walk back to desk
            anim.state = 'walk_to_desk';
            anim.route = computeRouteToDesk(anim.meetingPos, anim.deskCol, anim.deskRow, anim.deskDir);
            anim.routeIdx = 0;
          }
        } else if (anim.state === 'working_at_desk') {
          anim.workingTimer++;
          if (anim.workingTimer >= WORKING_DURATION) {
            anim.state = 'idle';
          }
        }
      }
    }

    // ── INTERACTIVE TASK DELEGATION & OVERHEAD BUBBLE CHAT ENGINE ──
    let activeMeetingSession = null;
    let currentOfficeMission = '';
    let lastKnownSubagentCount = -1;
    let lastKnownMission = '';

    function wrapDialogueText(text, maxChars = 28) {
      if (!text || text.length <= maxChars) return [text || ''];
      const words = text.split(' ');
      const lines = [];
      let cur = '';
      for (const w of words) {
        if ((cur + ' ' + w).trim().length <= maxChars) {
          cur = (cur + ' ' + w).trim();
        } else {
          if (cur) lines.push(cur);
          cur = w;
        }
      }
      if (cur) lines.push(cur);
      return lines;
    }

    // ── PROCEDURAL TOPIC-AWARE DIALOGUE & ROTATION ENGINE ──
    let lastMeetingParticipantIds = [];
    let generalMeetingRotationIndex = 0;

    const ROTATION_POOLS = {
      engineering: ['eng_1', 'eng_2', 'eng_3', 'eng_4', 'eng_5', 'eng_6', 'eng_7', 'eng_8'],
      intelligence: ['lab_1', 'lab_2', 'lab_3', 'lab_4'],
      secops: ['sec_1', 'sec_2', 'sec_5', 'sec_6', 'sec_7', 'sec_8'],
      vault: ['lib_1', 'lib_2', 'lib_3', 'lib_4']
    };

    const ROLE_DIALOGUE_LINES = {
      'eng_1': 'Tailwind & React Bits animations prepped!',
      'eng_2': 'FastAPI endpoints & typed contracts ready.',
      'eng_3': 'Surgical AST edits prepped, zero fluff.',
      'eng_4': 'CI/CD pipeline and PyInstaller armed.',
      'eng_5': 'E2E contracts & component wire verified.',
      'eng_6': 'Sub-millisecond heuristics benchmarked.',
      'eng_7': 'System architecture adheres to 70/30 rule.',
      'eng_8': 'Artifact versioning & checksums locked.',
      'lab_1': 'Perplexity audit passed, zero hallucination.',
      'lab_2': 'DemusBrain vault indexed and MOC synced.',
      'lab_3': 'Hardware telemetry & process watcher nominal.',
      'lab_4': 'Token lineage & data pipeline flowing.',
      'lib_1': 'Synthesized RFC specs and research models.',
      'lib_2': 'Permanent knowledge compounded to vault.',
      'lib_3': 'Knowledge graph ontology mapped cleanly.',
      'lib_4': 'Vault mirrors synchronized with zero desync.',
      'sec_1': 'Threat surface locked. Port gates guarded.',
      'sec_2': 'Attack vectors probed. Exploit sealed.',
      'sec_5': 'War room protocol engaged, ready to triage.',
      'sec_6': 'Regression tests staged, DoD enforced.',
      'sec_7': 'Syntax, TypeScript & linter 100% clean.',
      'sec_8': 'Subagent DAG workflow verified.',
      'exec_3': 'High-level system topology aligned.',
      'cafe_1': 'Espresso brewed! Energy levels at 100%.',
      'cafe_2': 'Standby dev ready for code review & pair.',
      'cafe_3': 'Perimeter patrol secure while on standby.'
    };

    const ROLE_CHORUS_EMOTES = {
      'eng_1': 'Rendering!',
      'eng_2': 'Compiling!',
      'eng_3': 'Refactoring!',
      'eng_4': 'Deploying!',
      'eng_5': 'Integrating!',
      'eng_6': 'Optimizing!',
      'eng_7': 'Governing!',
      'eng_8': 'Releasing!',
      'lab_1': 'Auditing!',
      'lab_2': 'Mining!',
      'lab_3': 'Monitoring!',
      'lab_4': 'Pipelining!',
      'lib_1': 'Synthesized!',
      'lib_2': 'Vaulted!',
      'lib_3': 'Curating!',
      'lib_4': 'Syncing!',
      'sec_1': 'Defending!',
      'sec_2': 'Penetrating!',
      'sec_5': 'Commanding!',
      'sec_6': 'Testing!',
      'sec_7': 'Validating!',
      'sec_8': 'Supervising!',
      'exec_3': 'Blueprinting!',
      'cafe_1': 'Energized!',
      'cafe_2': 'Ready!',
      'cafe_3': 'Standing!'
    };

    function classifyPromptTheme(rawText) {
      const text = (rawText || '').toLowerCase();
      
      // 1. Frontend / UI / UX / Styling / Visual
      if (/(frontend|ui|ux|tampilan|css|tailwind|react|komponen|button|tombol|halaman|layout|modal|interaksi|desain|design|visual|warna|font|responsive)/i.test(text)) {
        return {
          theme: 'frontend',
          primaryDept: 'engineering',
          recommendedStaff: ['eng_1', 'eng_5', 'sec_6', 'lab_1'],
          advisorLine: 'Prioritizing 60fps micro-UX & design tokens.',
          cleanTopic: 'Frontend UI & Micro-Interactions'
        };
      }
      
      // 2. Security / Pentest / Audit / Auth / Vulnerability
      if (/(secops|security|pentest|audit|vulnerability|vuln|cve|zero-trust|threat|auth|token|bypass|leak|csrf|xss|injection|red team|exploit|keamanan|hacker)/i.test(text)) {
        return {
          theme: 'security',
          primaryDept: 'secops',
          recommendedStaff: ['sec_2', 'sec_1', 'sec_5', 'sec_6'],
          advisorLine: 'Threat surface mapped. Zero-trust gate ready.',
          cleanTopic: 'Security Audit & Threat Surface'
        };
      }
      
      // 3. DevOps / Infra / Deployment / Docker / CI-CD / Server / Crash
      if (/(devops|infra|sre|deploy|ci[/-]cd|pipeline|build|release|docker|container|crash|memory|cpu|latency|server|hardware|monitoring|uptime)/i.test(text)) {
        return {
          theme: 'infra',
          primaryDept: 'engineering',
          recommendedStaff: ['eng_4', 'lab_3', 'eng_8', 'sec_5'],
          advisorLine: 'Hardware telemetry checked. Pipeline staged.',
          cleanTopic: 'Infrastructure Reliability & CI/CD'
        };
      }

      // 4. Backend / Database / API / Architecture
      if (/(backend|api|endpoint|database|db|fastapi|sql|rest|route|websocket|ast|refactor|contract|schema|migration)/i.test(text)) {
        return {
          theme: 'backend',
          primaryDept: 'engineering',
          recommendedStaff: ['eng_2', 'eng_3', 'lab_4', 'sec_7'],
          advisorLine: 'ACID guarantees and strict typed AST validated.',
          cleanTopic: 'Backend Architecture & API Contracts'
        };
      }

      // 5. AI / LLM / Models / Prompts / Subagents / Eval
      if (/(model|ai|llm|gemini|claude|gpt|prompt|reasoning|eval|token|subagent|agent|benchmark|perplexity|hallucination)/i.test(text)) {
        return {
          theme: 'ai',
          primaryDept: 'intelligence',
          recommendedStaff: ['lab_1', 'lab_2', 'lib_3', 'eng_6'],
          advisorLine: 'Token efficiency optimized; perplexity verified.',
          cleanTopic: 'AI Model Reasoning & Subagent Sync'
        };
      }

      // 6. Knowledge / Vault / DemusBrain / Docs / Research
      if (/(vault|demusbrain|docs|dokumen|catatan|catat|arsip|archive|research|paper|rfc|sync|memos|knowledge)/i.test(text)) {
        return {
          theme: 'docs',
          primaryDept: 'intelligence',
          recommendedStaff: ['lib_1', 'lib_2', 'lib_4', 'lab_2'],
          advisorLine: 'SSOT verified against DemusBrain vault.',
          cleanTopic: 'Knowledge Compounding & Vault Sync'
        };
      }

      // 7. QA / Testing / Bug Hunting / DoD / Lint
      if (/(bug|error|fix|test|testing|qa|lint|typecheck|dod|validate|masalah|rusak|benerin|patch)/i.test(text)) {
        return {
          theme: 'qa',
          primaryDept: 'secops',
          recommendedStaff: ['sec_6', 'sec_7', 'eng_3', 'eng_5'],
          advisorLine: 'Strict Definition of Done: zero-placeholder gate.',
          cleanTopic: 'Bug Remediation & DoD Verification'
        };
      }

      // 8. General all-hands / Multi-divisi / Default
      return {
        theme: 'general',
        primaryDept: 'all',
        recommendedStaff: null,
        advisorLine: 'Enforcing 70% reliability + 30% speed.',
        cleanTopic: 'Cross-Department Strategy Alignment'
      };
    }

    function selectSmartDelegates(promptText) {
      const classification = classifyPromptTheme(promptText);
      let selectedIds = [];

      if (classification.recommendedStaff && classification.recommendedStaff.length >= 4) {
        selectedIds = classification.recommendedStaff.slice(0, 4);
      } else {
        // Multi-divisi rotation pool: pick 1 Engineering, 1 Intelligence, 1 SecOps, 1 Vault
        generalMeetingRotationIndex++;
        const engPool = ROTATION_POOLS.engineering;
        const intelPool = ROTATION_POOLS.intelligence;
        const secPool = ROTATION_POOLS.secops;
        const vaultPool = ROTATION_POOLS.vault;

        let engId = engPool[generalMeetingRotationIndex % engPool.length];
        let intelId = intelPool[generalMeetingRotationIndex % intelPool.length];
        let secId = secPool[generalMeetingRotationIndex % secPool.length];
        let vaultId = vaultPool[generalMeetingRotationIndex % vaultPool.length];

        // Anti-repetition: if any ID matches previous meeting, shift by offset
        if (lastMeetingParticipantIds.includes(engId)) {
          engId = engPool[(generalMeetingRotationIndex + 3) % engPool.length];
        }
        if (lastMeetingParticipantIds.includes(intelId)) {
          intelId = intelPool[(generalMeetingRotationIndex + 2) % intelPool.length];
        }
        if (lastMeetingParticipantIds.includes(secId)) {
          secId = secPool[(generalMeetingRotationIndex + 3) % secPool.length];
        }
        if (lastMeetingParticipantIds.includes(vaultId)) {
          vaultId = vaultPool[(generalMeetingRotationIndex + 2) % vaultPool.length];
        }

        selectedIds = [engId, intelId, secId, vaultId];
      }

      lastMeetingParticipantIds = [...selectedIds];
      return selectedIds;
    }

    function extractMeetingSubject(rawUserPrompt, mission, cleanTopic) {
      if (!rawUserPrompt) return mission || cleanTopic || 'Cross-Department Strategy & Sprint Roadmap';

      let text = rawUserPrompt.trim();

      // Check if it's purely general call without specific technical topic
      if (/(ada yang gua mau ngomongin|ada yang mau dibahas|ikut rapat|kumpul dulu|rehat|santai|halo|pagi|siang|malam)/i.test(text) &&
          !/(bug|ui|ux|endpoint|api|database|db|fastapi|security|secops|infra|sre|deploy|model|ai|llm|token|vault|demusbrain)/i.test(text)) {
        return 'Cross-Department Strategy & Sprint Roadmap';
      }

      // Try extraction after action keywords (bahas, audit, review, investigasi, cek, tentang, soal)
      const actionMatch = text.match(/(?:rapat\\s+bahas|bahas|diskusi|audit|review|investigasi|analisis|cek|tentang|soal|mengenai)\\s+(.+)/i);
      let subjectCandidate = actionMatch ? actionMatch[1].trim() : text;

      // Clean up common conversational prefixes and suffixes
      let cleaned = subjectCandidate
        .replace(/^(ayo|tolong|coba|semua|guys|rekan-rekan|halo|oi|min|bro|segera|kita mau)\\s+/gi, '')
        .replace(/^(frontend|backend|secops|intelligence|engineering|qa|divisi\\s+\\w+)\\s+(dan\\s+\\w+\\s+)?/gi, '')
        .replace(/(dong|yak|ya|nih|bro|min|sekarang|dulu)\\s*$/gi, '')
        .replace(/[.,!?]+$/, '')
        .trim();

      if (cleaned.length >= 5) {
        if (cleaned.length > 42) cleaned = cleaned.slice(0, 39) + '...';
        return cleaned;
      }

      return cleanTopic || mission || 'Cross-Department Strategy & Sprint Roadmap';
    }

    function buildMeetingDialogues(mission, participants, rawUserPrompt) {
      const classification = classifyPromptTheme(rawUserPrompt || mission);
      const theme = classification.theme || 'general';
      const cleanSubject = extractMeetingSubject(rawUserPrompt, mission, classification.cleanTopic);

      const p0 = participants[0] || 'eng_2';
      const p1 = participants[1] || 'lab_1';
      const p2 = participants[2] || 'sec_7';
      const p3 = participants[3] || 'lib_1';

      const s0 = pixelOfficeStations.find(s => s.id === p0) || OFFICE_STATIONS.find(s => s.id === p0) || { id: p0, title: 'Lead Specialist', dept: 'engineering' };
      const s1 = pixelOfficeStations.find(s => s.id === p1) || OFFICE_STATIONS.find(s => s.id === p1) || { id: p1, title: 'Sparring Partner', dept: 'intelligence' };
      const s2 = pixelOfficeStations.find(s => s.id === p2) || OFFICE_STATIONS.find(s => s.id === p2) || { id: p2, title: 'Sentinel Lead', dept: 'secops' };
      const s3 = pixelOfficeStations.find(s => s.id === p3) || OFFICE_STATIONS.find(s => s.id === p3) || { id: p3, title: 'Vault Archivist', dept: 'intelligence' };

      const r0 = s0.assignedStaff?.role || s0.title;
      const r1 = s1.assignedStaff?.role || s1.title;
      const r2 = s2.assignedStaff?.role || s2.title;
      const r3 = s3.assignedStaff?.role || s3.title;

      // Turn 1: Lead Orchestrator (Root) - Problem Framing & Scope
      let t1_thought = `Menganalisis arahan komandan: petakan arsitektur dan failure point untuk '${cleanSubject}'.`;
      let t1_speech = `Agenda rapat dibuka: fokus ke '${cleanSubject}'. Divisi terkait, paparkan analisa teknis dan bottleneck sekarang!`;
      if (theme === 'general') {
        t1_thought = `Evaluasi roadmap sprint lintas divisi: koordinasikan prioritas dan mitigasi hambatan.`;
        t1_speech = `Rapat koordinasi dibuka: evaluasi status dan blocker untuk '${cleanSubject}'. Perwakilan divisi, laporkan!`;
      }

      // Turn 2: Primary Specialist (s0) - Technical Hypothesis & Proposal
      let t2_thought = '';
      let t2_speech = '';

      // Turn 3: Sparring Partner (s1) - Mode C Critical Sparring & Edge Cases
      let t3_thought = '';
      let t3_speech = '';

      // Turn 4: QA / Security Sentinel (s2) - Verification & DoD Gate
      let t4_thought = `Enforce Definition of Done: zero-placeholder mandate, 100% test coverage, zero unverified assumptions.`;
      let t4_speech = `Dari tim QA & SecOps: mitigasi dicatat. Tapi tidak ada kode yang merge untuk '${cleanSubject}' sebelum lulus test suite dan DoD 100% hijau.`;

      // Turn 5: Knowledge / Research Miner (s3) - DemusBrain Grounding & Compounding
      let t5_thought = `Kroscek dengan best practices di DemusBrain vault. Pastikan knowledge terkompound tanpa silo.`;
      let t5_speech = `Struktur ini selaras dengan standard di DemusBrain vault. Seluruh keputusan dan mitigasi '${cleanSubject}' langsung kita arsipkan ke MOC.`;

      // Turn 6: Lead Orchestrator (Root) - Synthesis & Actionable Directive
      let t6_thought = `Sintesis selesai. Trade-off ditimbang, scope terkunci, kriteria acceptance rigid.`;
      let t6_speech = `Konsensus bulat tercapai untuk '${cleanSubject}'! Arsitektur disepakati, mitigasi dikunci, DoD ditegakkan. Bubar dan eksekusi sekarang!`;

      // Theme-specific customized dialogue logic
      if (theme === 'frontend') {
        t2_thought = `Investigasi DOM reconciliation dan layout thrashing pada '${cleanSubject}'. Butuh decouple state.`;
        t2_speech = `Kami lacak bottleneck di re-render loop '${cleanSubject}'. Proposal: decouple component state dan standarkan styling tokens.`;

        t3_thought = `Mode C Sparring: challenge memoization. Hati-hati stale closure pada event listeners dan form state.`;
        t3_speech = `Tunggu dulu! Kalau state di-decouple tanpa reactive sync di '${cleanSubject}', ada risiko stale closure saat multi-tab.`;

        t4_thought = `Zero-placeholder mandate. Verifikasi DOM layout, contrast ratio, dan headless Playwright assertions.`;
        t4_speech = `Setuju mitigasinya. Tapi PR ditahan sampai Playwright E2E audit lulus tanpa flakiness di '${cleanSubject}'.`;

        t5_thought = `Cek design tokens di DemusBrain SSOT. Pertahankan consistency dengan awesome-design-md standard.`;
        t5_speech = `Pola komponen ini sudah match dengan token vault. Saya arsipkan catatan resolusi ke DemusBrain begitu tuntas.`;

        t6_thought = `Trade-off frontend terkunci: 60fps micro-UX, zero visual glitch, DoD lulus.`;
        t6_speech = `Konsensus frontend tercapai! Selesaikan decoupling '${cleanSubject}', jalankan Playwright, dan deploy dengan DoD 100%!`;
      } else if (theme === 'security') {
        t2_thought = `Threat modeling pada '${cleanSubject}'. Audit sanitization, unvalidated input, dan token tamper.`;
        t2_speech = `Vektor risiko utama terdeteksi pada boundary '${cleanSubject}'. Kami siapkan strict input filter dan session pinning.`;

        t3_thought = `Mode C Sparring: challenge security gate. Hard lockout bisa trigger false positive pada user legitimate.`;
        t3_speech = `Awas, kalau blocking rule terlalu agresif di '${cleanSubject}', traffic valid bisa kena rate-limit false positive!`;

        t4_thought = `Zero-trust verification gate. Lakukan fuzzing dan regression test sebelum deklarasi safe.`;
        t4_speech = `Terapkan adaptive throttle sebagai fallback. Dan lakukan fuzzing payload sebelum tiket '${cleanSubject}' ditutup.`;

        t5_thought = `Kroscek CWE/CVE pattern di DemusBrain vault. Pastikan tidak melanggar strict ethical boundaries.`;
        t5_speech = `Pattern attack vector ini sudah terdokumentasi di security arsenal vault. Mitigasinya sudah compliant.`;

        t6_thought = `Perimeter diamankan. Zero silent assumptions pada security posture.`;
        t6_speech = `Konsensus SecOps terkunci! Segel perimeter '${cleanSubject}', aktifkan adaptive throttle, dan verifikasi exploit!`;
      } else if (theme === 'backend') {
        t2_thought = `Audit latency query, lock contention, dan AST layer pada '${cleanSubject}'.`;
        t2_speech = `Kami prioritaskan refactor AST dan typed schema di '${cleanSubject}'. Database transactions dikunci isolasi strict.`;

        t3_thought = `Mode C Sparring: challenge transaction locks. Long-running transaction memicu database pool exhaustion.`;
        t3_speech = `Tantangan: lock table yang terlalu panjang di '${cleanSubject}' bisa bikin thread pool starvation saat peak load!`;

        t4_thought = `Typecheck dan test coverage: strict MyPy, zero unchecked types, unit tests pass 100%.`;
        t4_speech = `Solusinya gunakan optimistic concurrency control. Saya kawal typecheck dan pytest coverage 100% untuk '${cleanSubject}'.`;

        t5_thought = `Periksa dampak migrasi schema pada downstream pipelines dan event streams.`;
        t5_speech = `Pipeline downstream aman. Schema migration script '${cleanSubject}' sudah diverifikasi idempotensinya.`;

        t6_thought = `Arsitektur rigid dan scalable. 70% pragmatic reliability + 30% speed.`;
        t6_speech = `Sepakat! Implementasikan optimistic locking pada '${cleanSubject}', jalankan pytest, lalu merge!`;
      } else if (theme === 'infra') {
        t2_thought = `Profil CPU/RAM spikes, container memory leak, dan GC pressure pada '${cleanSubject}'.`;
        t2_speech = `Kami deteksi spikes resource di container worker saat '${cleanSubject}'. Perlu tuning worker pool dan GC ceiling.`;

        t3_thought = `Mode C Sparring: challenge restart policy. Auto-restart tanpa backoff bisa masking leak laten.`;
        t3_speech = `Jangan sekadar naikkan RAM limit untuk '${cleanSubject}'. Cari root-cause leak-nya agar tidak bocor lagi!`;

        t4_thought = `Pastikan observability: metric export, alert threshold, dan zero service degradation.`;
        t4_speech = `Pasang heap dump profiling dan alert telemetry begitu threshold 80% tersentuh di '${cleanSubject}'.`;

        t5_thought = `Dokumentasikan runbook insiden dan konfigurasi cluster ke DemusBrain.`;
        t5_speech = `SOP mitigasi dan runbook auto-recovery '${cleanSubject}' sudah saya sinkronkan ke vault infra docs.`;

        t6_thought = `Root cause terkendali. Health check probe dan alert threshold aktif.`;
        t6_speech = `Konsensus infra tercapai! Pasang heap profiler di '${cleanSubject}', perbaiki leak, dan pantau metrics!`;
      } else if (theme === 'ai') {
        t2_thought = `Benchmark perplexity, latency per token, dan hallucination rate pada '${cleanSubject}'.`;
        t2_speech = `Hasil benchmark menunjukkan token consumption di '${cleanSubject}' bisa ditekan 40% via prompt pruning.`;

        t3_thought = `Mode C Sparring: challenge prompt pruning. Pruning agresif bisa menghilangkan instruksi grounding.`;
        t3_speech = `Hati-hati, jika system prompt '${cleanSubject}' terlalu dipangkas, reasoning subagent bisa drifting!`;

        t4_thought = `Audit output validation: JSON schema parsing, prompt injection defense, dan strict retry budget.`;
        t4_speech = `Kita kunci schema outputnya dengan Pydantic parser dan fallback parser agar zero hallucination di '${cleanSubject}'.`;

        t5_thought = `Sinkronisasi context grounding dengan DemusBrain knowledge graph.`;
        t5_speech = `Context grounding akan kita inject via DemusBrain SSOT cache agar respon '${cleanSubject}' deterministik.`;

        t6_thought = `Token efisien, reasoning tajam, output tervalidasi schema.`;
        t6_speech = `Konsensus mantap! Optimasi prompt '${cleanSubject}', pasang schema validation, dan benchmark live!`;
      } else if (theme === 'qa') {
        t2_thought = `Trace execution stack, periksa unhandled exception dan edge-case input di '${cleanSubject}'.`;
        t2_speech = `Kami berhasil mereproduksi bug pada '${cleanSubject}'. Error terjadi karena missing boundary validation.`;

        t3_thought = `Mode C Sparring: challenge proposed fix. Pastikan patch tidak merusak modul dependensi.`;
        t3_speech = `Pastikan patch '${cleanSubject}' tidak menyebabkan breaking change di consumer API yang bergantung padanya!`;

        t4_thought = `Terapkan Definition of Done: automated unit test + regression test + zero-placeholder code.`;
        t4_speech = `Wajib tambahkan regression test suite khusus untuk skenario '${cleanSubject}' sebelum branch di-merge.`;

        t5_thought = `Catat Post-Mortem dan pelajaran teknis ke DemusBrain vault.`;
        t5_speech = `Root-cause dan pencegahan bug '${cleanSubject}' akan langsung diarsipkan ke log insiden DemusBrain.`;

        t6_thought = `Root cause terisolasi, patch teruji, DoD ditegakkan.`;
        t6_speech = `Konsensus triage bulat! Terapkan patch bedah pada '${cleanSubject}', jalankan automated test, lalu release!`;
      } else if (theme === 'docs') {
        t2_thought = `Audit integritas SSOT di DemusBrain vault. Cek referensi silang dan konsistensi data pada '${cleanSubject}'.`;
        t2_speech = `Struktur data untuk '${cleanSubject}' sudah kami verifikasi. Ada gap informasi yang perlu dikompound ke vault.`;

        t3_thought = `Mode C Sparring: challenge vault structure. Hindari duplikasi catatan yang bikin fragmentasi.`;
        t3_speech = `Pastikan update '${cleanSubject}' tidak membuat redundant notes. Sambungkan langsung ke MOC utama!`;

        t4_thought = `Enforce universal ground-truth: zero silent assumptions dan deklarasi proxy eksplisit.`;
        t4_speech = `Data provenance harus clean. Jangan ada klaim verified jika data mentah '${cleanSubject}' masih estimasi.`;

        t5_thought = `Eksekusi compile.py dan sinkronisasi mirror C:\\DemusBrain secara atomik.`;
        t5_speech = `Automasi mirror dan compile.py sudah siap jalan begitu dokumentasi '${cleanSubject}' ditutup.`;

        t6_thought = `Pengetahuan terkompound permanen. SSOT vault tetap kokoh.`;
        t6_speech = `Konsensus knowledge tercapai! Update MOC '${cleanSubject}', jalankan compile.py, dan mirror vault!`;
      } else {
        // General / All-Hands
        t2_thought = `Mengevaluasi kapasitas engineering dan arsitektur sprint untuk '${cleanSubject}'.`;
        t2_speech = `Dari sisi Engineering, fondasi untuk '${cleanSubject}' sudah stabil. Kami siap boost eksekusi begitu kontrak fix.`;

        t3_thought = `Mode C Sparring: evaluasi 70/30 balance. Kecepatan tidak boleh mengorbankan stabilitas core.`;
        t3_speech = `Ingat prinsip 70/30! Jangan terburu-buru delivery di '${cleanSubject}' kalau stabilitas belum 100%.`;

        t4_thought = `Gatekeeper status: zero-placeholder mandate, automated test passing, clean logs.`;
        t4_speech = `SecOps & QA siap kawal. Kriteria DoD tetap harga mati untuk seluruh deliverables '${cleanSubject}'.`;

        t5_thought = `Memastikan keterhubungan antar modul dan sinkronisasi berkala ke DemusBrain SSOT.`;
        t5_speech = `Semua milestone dan artefak dari '${cleanSubject}' akan terus dipantau dan disinkronkan ke vault.`;

        t6_thought = `Alignment tercapai. Sinergi antar-divisi solid dan target terkunci.`;
        t6_speech = `Konsensus all-hands tercapai untuk '${cleanSubject}'! Koordinasi terkunci, bubar rapat dan eksekusi dengan DoD!`;
      }

      // Dynamic chorus items
      const chorusTexts = {
        frontend: ['Rendering!', 'Polishing!', 'Testing!', 'Vaulting!'],
        security: ['Sealing!', 'Guarding!', 'Auditing!', 'Logging!'],
        backend: ['Compiling!', 'Locking!', 'Validating!', 'Syncing!'],
        infra: ['Deploying!', 'Tuning!', 'Profiling!', 'Vaulting!'],
        ai: ['Benchmarking!', 'Pruning!', 'Parsing!', 'Grounding!'],
        qa: ['Patching!', 'Asserting!', 'DoD Green!', 'Archived!'],
        docs: ['Writing!', 'Linking!', 'Auditing!', 'Compounding!'],
        general: ['Executing!', 'Sparred!', 'Verified!', 'Compounded!']
      }[theme] || ['Executing!', 'Sparred!', 'Verified!', 'Compounded!'];

      return [
        {
          speakerId: 'exec_1',
          speakerRole: 'Lead Orchestrator (Root)',
          dept: 'executive',
          thought: t1_thought,
          speech: t1_speech,
          text: t1_speech,
          startFrame: 10,
          duration: 110
        },
        {
          speakerId: s0.id,
          speakerRole: r0,
          dept: s0.dept,
          thought: t2_thought,
          speech: t2_speech,
          text: t2_speech,
          startFrame: 125,
          duration: 110
        },
        {
          speakerId: s1.id,
          speakerRole: r1,
          dept: s1.dept,
          thought: t3_thought,
          speech: t3_speech,
          text: t3_speech,
          startFrame: 240,
          duration: 110
        },
        {
          speakerId: s2.id,
          speakerRole: r2,
          dept: s2.dept,
          thought: t4_thought,
          speech: t4_speech,
          text: t4_speech,
          startFrame: 355,
          duration: 110
        },
        {
          speakerId: s3.id,
          speakerRole: r3,
          dept: s3.dept,
          thought: t5_thought,
          speech: t5_speech,
          text: t5_speech,
          startFrame: 470,
          duration: 110
        },
        {
          speakerId: 'exec_1',
          speakerRole: 'Lead Orchestrator (Root)',
          dept: 'executive',
          thought: t6_thought,
          speech: t6_speech,
          text: t6_speech,
          startFrame: 585,
          duration: 110
        },
        {
          isChorus: true,
          speakerRole: 'All Delegates',
          thought: 'Seluruh delegasi divisi serentak menyepakati konsensus akhir.',
          speech: 'Konsensus tercapai. Disperse dan eksekusi!',
          chorusItems: [
            { speakerId: s0.id, text: chorusTexts[0], dept: s0.dept },
            { speakerId: s1.id, text: chorusTexts[1], dept: s1.dept },
            { speakerId: s2.id, text: chorusTexts[2], dept: s2.dept },
            { speakerId: s3.id, text: chorusTexts[3], dept: s3.dept }
          ],
          startFrame: 700,
          duration: 85
        }
      ];
    }

    function getSpeakerHeadPos(speakerId) {
      const anim = agentAnimState[speakerId];
      if (anim && (anim.state === 'in_meeting' || anim.state === 'walk_to_meeting')) {
        return { x: Math.round(anim.px) + 8, y: Math.round(anim.py) };
      }
      const slot = pixelOfficeStations.find(s => s.id === speakerId);
      if (slot) {
        if (slot.dir === 'up') {
          return { x: slot.col * 16 + 8, y: (slot.row - 1) * 16 + 18 };
        } else {
          return { x: slot.col * 16 + 8, y: slot.row * 16 - 4 };
        }
      }
      return { x: 8 * 16 + 8, y: 7 * 16 };
    }

    function getActiveSpeakingAgentId() {
      if (!activeMeetingSession || !activeMeetingSession.active) return null;
      const currentFrame = activeMeetingSession.frame;
      for (let i = 0; i < activeMeetingSession.dialogues.length; i++) {
        const d = activeMeetingSession.dialogues[i];
        if (currentFrame >= d.startFrame && currentFrame < d.startFrame + d.duration) {
          return d.isChorus ? '__chorus__' : d.speakerId;
        }
      }
      return null;
    }

    function drawSpeechBubble(ctx, hx, hy, roleName, text, dept, animProgress = 1.0, thoughtText = null) {
      ctx.save();

      let strokeColor = '#38bdf8'; // Executive cyan
      let tagColor = '#38bdf8';
      if (dept === 'engineering') { strokeColor = '#c084fc'; tagColor = '#c084fc'; }
      else if (dept === 'intelligence') { strokeColor = '#34d399'; tagColor = '#34d399'; }
      else if (dept === 'secops') { strokeColor = '#fbbf24'; tagColor = '#fbbf24'; }

      const speechLines = wrapDialogueText(text, 28).slice(0, 2);

      ctx.font = '700 6.5px "JetBrains Mono", Consolas, monospace';
      const roleWidth = ctx.measureText(roleName).width;

      ctx.font = '600 6.5px "JetBrains Mono", Consolas, monospace';
      let maxLineWidth = roleWidth;
      speechLines.forEach(l => {
        const w = ctx.measureText(l).width;
        if (w > maxLineWidth) maxLineWidth = w;
      });

      let cleanThought = '';
      if (thoughtText) {
        cleanThought = thoughtText.length > 34 ? thoughtText.slice(0, 31) + '...' : thoughtText;
        ctx.font = 'italic 5.5px "JetBrains Mono", Consolas, monospace';
        const tw = ctx.measureText('Thought: ' + cleanThought).width;
        if (tw > maxLineWidth) maxLineWidth = tw;
      }

      const bubbleW = Math.max(96, Math.min(200, Math.round(maxLineWidth + 14)));
      const hasThought = !!thoughtText;
      const bubbleH = hasThought 
        ? (speechLines.length > 1 ? 38 : 31) 
        : (speechLines.length > 1 ? 28 : 20);

      // Position bubble above speaker's head, clamped within canvas
      const maxW = (ctx.canvas && ctx.canvas.width) ? ctx.canvas.width : (48 * 16);
      let bx = Math.round(hx - bubbleW / 2);
      let by = Math.round(hy - bubbleH - 7);

      if (bx < 8) bx = 8;
      if (bx + bubbleW > maxW - 8) bx = maxW - 8 - bubbleW;
      if (by < 4) by = 4;

      const tailX = Math.max(bx + 8, Math.min(bx + bubbleW - 8, Math.round(hx)));
      const tailTipY = hy - 1;
      const tailBaseY = by + bubbleH;

      // Snappy pop-in spring (clamped to at least 0.1 to prevent degenerate matrix)
      const scale = Math.max(0.1, Math.min(1.0, animProgress * 4.0));
      if (scale < 1.0) {
        ctx.translate(hx, hy);
        ctx.scale(scale, scale);
        ctx.translate(-hx, -hy);
      }

      // Drop shadow
      ctx.fillStyle = 'rgba(0, 0, 0, 0.82)';
      ctx.fillRect(bx + 1.5, by + 1.5, bubbleW, bubbleH);

      // Main background
      ctx.fillStyle = 'rgba(10, 13, 22, 0.97)';
      ctx.fillRect(bx, by, bubbleW, bubbleH);

      // Colored border
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1.2;
      ctx.strokeRect(bx, by, bubbleW, bubbleH);

      // Pointer Tail pointing down to speaker head
      ctx.fillStyle = 'rgba(10, 13, 22, 0.97)';
      ctx.beginPath();
      ctx.moveTo(tailX - 3.5, tailBaseY);
      ctx.lineTo(tailX, tailTipY);
      ctx.lineTo(tailX + 3.5, tailBaseY);
      ctx.closePath();
      ctx.fill();

      // Tail stroke
      ctx.beginPath();
      ctx.moveTo(tailX - 3.5, tailBaseY);
      ctx.lineTo(tailX, tailTipY);
      ctx.lineTo(tailX + 3.5, tailBaseY);
      ctx.stroke();

      // Micro decorative corner pixels
      ctx.fillStyle = strokeColor;
      ctx.fillRect(bx, by, 2, 2);
      ctx.fillRect(bx + bubbleW - 2, by, 2, 2);

      // Speaker Name Tag
      ctx.fillStyle = tagColor;
      ctx.font = '700 6.5px "JetBrains Mono", Consolas, monospace';
      ctx.textBaseline = 'top';
      ctx.fillText(roleName, bx + 5, by + 3);

      let curY = by + 11;

      // Thought Line (if available)
      if (hasThought) {
        ctx.fillStyle = '#64748b';
        ctx.font = '700 5.5px "JetBrains Mono", Consolas, monospace';
        ctx.fillText('Thought: ', bx + 5, curY);
        const pfxW = ctx.measureText('Thought: ').width;

        ctx.fillStyle = '#94a3b8';
        ctx.font = 'italic 5.5px "JetBrains Mono", Consolas, monospace';
        ctx.fillText(cleanThought, bx + 5 + pfxW, curY);

        curY += 8;

        // Micro divider line
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(bx + 4, curY - 1);
        ctx.lineTo(bx + bubbleW - 4, curY - 1);
        ctx.stroke();
      }

      // Spoken Dialogue Text Lines
      ctx.fillStyle = '#f8fafc';
      ctx.font = '600 6.5px "JetBrains Mono", Consolas, monospace';
      if (speechLines.length > 1) {
        ctx.fillText('"' + speechLines[0], bx + 5, curY);
        ctx.fillText(speechLines[1] + '"', bx + 5, curY + 8);
      } else if (speechLines.length === 1) {
        ctx.fillText('"' + speechLines[0] + '"', bx + 5, curY);
      }

      ctx.restore();
    }

    function drawMiniEmoteBubble(ctx, hx, hy, text, deptColor) {
      ctx.save();
      ctx.font = '700 7px "JetBrains Mono", Consolas, monospace';
      const tw = ctx.measureText(text).width;
      const bw = tw + 8;
      const bh = 13;
      const bx = Math.round(hx - bw / 2);
      const by = Math.round(hy - bh - 5);

      // Drop shadow
      ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
      ctx.fillRect(bx + 1, by + 1, bw, bh);

      // Body & Border
      ctx.fillStyle = 'rgba(10, 13, 22, 0.97)';
      ctx.fillRect(bx, by, bw, bh);
      ctx.strokeStyle = deptColor;
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, bw, bh);

      // Pointer Tail
      ctx.beginPath();
      ctx.moveTo(hx - 2, by + bh);
      ctx.lineTo(hx, hy - 1);
      ctx.lineTo(hx + 2, by + bh);
      ctx.fillStyle = 'rgba(10, 13, 22, 0.97)';
      ctx.fill();
      ctx.stroke();

      // Emote text
      ctx.fillStyle = '#ffffff';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, bx + 4, by + bh / 2 + 0.5);
      ctx.restore();
    }

    // Call a cross-department strategy alignment meeting in the War Room
    function callTeamMeeting(customStaffIds, taskMission, rawUserPrompt) {
      const meetingPositions = MEETING_POSITIONS;

      let selectedStaffIds = customStaffIds;
      if (!selectedStaffIds || !Array.isArray(selectedStaffIds) || selectedStaffIds.length === 0) {
        selectedStaffIds = selectSmartDelegates(rawUserPrompt || taskMission);
      }

      let selectedSlots = pixelOfficeStations.filter(s => selectedStaffIds.includes(s.id));
      if (selectedSlots.length === 0) {
        selectedSlots = OFFICE_STATIONS.filter(s => selectedStaffIds.includes(s.id));
      }

      if (selectedSlots.length === 0) return;

      const classification = classifyPromptTheme(rawUserPrompt || taskMission);
      const mission = taskMission || classification.cleanTopic || currentOfficeMission || 'Sprint Architecture & Feature Delegation';
      const participantIds = selectedSlots.map(s => s.id);

      activeMeetingSession = {
        active: true,
        mission: mission,
        rawPrompt: rawUserPrompt || '',
        participants: participantIds,
        frame: 0,
        dialogues: buildMeetingDialogues(mission, participantIds, rawUserPrompt),
        llmLoaded: false
      };

      // Asynchronously request authentic LLM multi-agent deliberative debate from backend
      const participantsPayload = selectedSlots.map(s => ({
        id: s.id,
        role: s.assignedStaff?.role || s.title || 'Specialist',
        dept: s.dept || 'engineering'
      }));

      fetch('/api/office/generate_meeting_dialogue', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: rawUserPrompt || taskMission || mission,
          participants: participantsPayload,
          mission: mission
        })
      })
      .then(r => r.json())
      .then(res => {
        if (res && res.status === 'ok' && Array.isArray(res.dialogues) && res.dialogues.length >= 6) {
          if (activeMeetingSession && activeMeetingSession.active) {
            activeMeetingSession.dialogues = res.dialogues;
            activeMeetingSession.llmLoaded = true;
            console.log('[LLM Deliberation] Loaded authentic Gemini 3.7 dialogue into War Room session!');
          }
        }
      })
      .catch(err => {
        console.warn('[LLM Deliberation] Request error, remaining on local fallback:', err);
      });

      selectedSlots.forEach((slot, i) => {
        const meetPos = meetingPositions[i % meetingPositions.length];
        const routeData = computeRouteToMeeting(slot.col, slot.row, slot.dir, meetPos);

        agentAnimState[slot.id] = {
          state: 'walk_to_meeting',
          route: routeData.route,
          routeIdx: 0,
          px: routeData.startX,
          py: routeData.startY,
          deskCol: slot.col,
          deskRow: slot.row,
          deskDir: slot.dir,
          walkDir: 'down',
          meetingPos: meetPos,
          meetingTimer: 0,
          workingTimer: 0,
          delayFrames: i * 20  // Stagger walk starts by ~0.33s
        };
      });

      console.log(`[Meeting] Called sync meeting for mission: "${mission}" with ${selectedSlots.map(s => s.assignedStaff?.role || s.title).join(', ')}`);

      const btn = document.getElementById('btn-call-meeting');
      if (btn) {
        btn.innerHTML = `<span class="font-semibold text-amber-200">Meeting in Session...</span>`;
        setTimeout(() => {
          const b = document.getElementById('btn-call-meeting');
          if (b) {
            b.innerHTML = `<span class="font-semibold">Call Meeting</span>`;
          }
        }, (MEETING_DURATION + 360) * 16);
      }
    }

    window.callTeamMeeting = callTeamMeeting;
    window.getActiveMeetingSession = () => activeMeetingSession;

    // Trigger an ambient meeting periodically (disabled — strictly no automatic replay loops)
    function triggerAmbientMeeting() {
      nextAmbientMeetingFrame = Infinity;
    }

    function isAgentAtDesk(slotId) {
      const anim = agentAnimState[slotId];
      if (!anim) return true;
      return anim.state === 'idle' || anim.state === 'working_at_desk';
    }

    function getAgentAnimAction(slotId) {
      const anim = agentAnimState[slotId];
      if (!anim) return null;
      if (anim.state === 'walk_to_meeting' || anim.state === 'walk_to_desk') return 'walk';
      if (anim.state === 'in_meeting') return 'idle';
      if (anim.state === 'working_at_desk') return 'typing';
      return null;
    }

    // ── COMMANDER CONSOLE & HQ INTERCOM DUAL-MODE ENGINE ──
    let consoleDockCollapsed = false;

    function toggleConsoleDock() {
      consoleDockCollapsed = !consoleDockCollapsed;
      const body = document.getElementById('commander-console-body');
      const label = document.getElementById('label-toggle-console');
      if (body) body.style.display = consoleDockCollapsed ? 'none' : 'block';
      if (label) label.textContent = consoleDockCollapsed ? '[Show]' : '[Hide]';
    }

    function updateConsoleModeBadge() {
      const chk = document.getElementById('chk-live-token-mode');
      const badge = document.getElementById('console-mode-badge');
      const hint = document.getElementById('console-mode-hint');
      if (!badge || !hint) return;
      if (chk && chk.checked) {
        badge.className = 'px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-amber-950/60 border border-amber-800/60 text-amber-400 transition-all';
        badge.innerHTML = '[Live Token] Antigravity IDE Prompt';
        hint.innerHTML = 'Forwarded to IDE Language Server via CDP';
        hint.className = 'text-amber-400/80 text-[9.5px]';
      } else {
        badge.className = 'px-1.5 py-0.5 rounded text-[9.5px] font-semibold bg-emerald-950/60 border border-emerald-800/60 text-emerald-400 transition-all';
        badge.innerHTML = '[0-Token] Visual Office Directive';
        hint.innerHTML = 'Gratis kuota • Eksekusi lokal instan';
        hint.className = 'text-gray-500 text-[9.5px]';
      }
    }

    function escapeHtmlText(str) {
      if (!str) return '';
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function appendCommanderChat(senderRole, text, textColor = 'text-slate-300', tagColor = 'text-cyan-400') {
      const stream = document.getElementById('commander-chat-stream');
      if (!stream) return;
      const now = new Date();
      const timeStr = now.toTimeString().slice(0, 8);
      const row = document.createElement('div');
      row.className = `flex items-start gap-2 ${textColor} text-[10.5px] leading-relaxed`;
      row.innerHTML = `
        <span class="text-gray-600 shrink-0 text-[10px] select-none">[${timeStr}]</span>
        <span class="shrink-0 font-bold ${tagColor}">[${escapeHtmlText(senderRole)}]</span>
        <span class="flex-1 break-words">${escapeHtmlText(text)}</span>
      `;
      stream.appendChild(row);
      stream.scrollTop = stream.scrollHeight;
    }

    function appendCommanderMeetingTurn(d) {
      const stream = document.getElementById('commander-chat-stream');
      if (!stream) return;
      const now = new Date();
      const timeStr = now.toTimeString().slice(0, 8);

      let deptColor = 'text-cyan-400';
      let tagBg = 'bg-cyan-950/60 border-cyan-800/60';
      if (d.dept === 'engineering') { deptColor = 'text-purple-400'; tagBg = 'bg-purple-950/60 border-purple-800/60'; }
      else if (d.dept === 'intelligence') { deptColor = 'text-emerald-400'; tagBg = 'bg-emerald-950/60 border-emerald-800/60'; }
      else if (d.dept === 'secops') { deptColor = 'text-amber-400'; tagBg = 'bg-amber-950/60 border-amber-800/60'; }

      if (d.isChorus) {
        const row = document.createElement('div');
        row.className = 'flex items-center gap-2 text-[10px] text-gray-400 font-mono py-1.5 border-t border-hairline/50';
        row.innerHTML = `
          <span class="text-gray-600 shrink-0 select-none">[${timeStr}]</span>
          <span class="px-1.5 py-0.5 rounded border border-hairline bg-surface-2 text-white font-semibold">[ALL DELEGATES]</span>
          <span class="text-gray-300 italic">Konsensus tercapai. Seluruh divisi serempak membubarkan diri ke pos kerja masing-masing!</span>
        `;
        stream.appendChild(row);
        stream.scrollTop = stream.scrollHeight;
        return;
      }

      const row = document.createElement('div');
      row.className = 'space-y-1 py-1.5 border-b border-hairline/40 font-mono text-[10.5px]';

      let thoughtHtml = '';
      if (d.thought) {
        thoughtHtml = `
          <div class="flex items-start gap-1.5 text-[9.5px] text-slate-400 pl-3 italic border-l-2 border-slate-700/80 my-0.5">
            <span class="text-slate-500 font-semibold select-none">[Thought]</span>
            <span class="leading-tight">${escapeHtmlText(d.thought)}</span>
          </div>
        `;
      }

      row.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="text-gray-600 shrink-0 text-[9.5px] select-none">[${timeStr}]</span>
          <span class="px-1.5 py-0.5 rounded border ${tagBg} ${deptColor} font-bold text-[9.5px]">[${escapeHtmlText(d.speakerRole)}]</span>
        </div>
        ${thoughtHtml}
        <div class="text-white font-medium pl-3 text-[10.5px] leading-relaxed">
          "${escapeHtmlText(d.speech || d.text)}"
        </div>
      `;

      stream.appendChild(row);
      stream.scrollTop = stream.scrollHeight;
    }

    function handleCommanderKey(event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        dispatchCommanderCommand();
      }
    }

    function sendQuickDirective(type) {
      const input = document.getElementById('commander-input');
      if (!input) return;
      if (type === 'meeting') {
        input.value = 'ayo masing masing divisi ikut rapat, ada yang gua mau ngomongin';
      } else if (type === 'break') {
        input.value = 'semua agen standby silakan rehat sejenak dan ngopi di cafe lounge';
      } else if (type === 'secops') {
        input.value = 'secops lakukan audit zero-trust dan threat mapping sekarang';
      } else if (type === 'engineering') {
        input.value = 'engineering hub fokus ke sprint architecture dan refactor';
      }
      dispatchCommanderCommand();
    }

    function dispatchCommanderCommand() {
      const input = document.getElementById('commander-input');
      if (!input) return;
      const rawText = input.value.trim();
      if (!rawText) return;
      input.value = '';

      const isLiveTokenMode = !!(document.getElementById('chk-live-token-mode')?.checked);

      // 1. Log Commander's command
      appendCommanderChat('Commander', rawText, 'text-white', 'text-amber-400');

      // 2. If Live Token Mode is active -> send to CDP API endpoint
      if (isLiveTokenMode) {
        appendCommanderChat('Antigravity IDE', 'Menginjeksi prompt ke Antigravity Language Server via CDP...', 'text-amber-300', 'text-amber-400');
        fetch('/api/office/send_prompt', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: rawText })
        }).then(r => r.json()).then(res => {
          if (res && res.success) {
            appendCommanderChat('Root Orchestrator', 'Prompt berhasil diterima Language Server! Subagent sedang disiapkan.', 'text-emerald-300', 'text-emerald-400');
          } else {
            appendCommanderChat('Root Orchestrator', 'Catatan: ' + (res.message || 'Prompt diproses secara lokal.'), 'text-gray-400', 'text-cyan-400');
          }
        }).catch(e => {
          console.warn("CDP dispatch error:", e);
        });
      }

      // 3. Local Lightweight Intent Dispatcher (0 Token / Instant Visual Action)
      const lower = rawText.toLowerCase();

      // Pattern A: Meeting / Rapat / Diskusi / Bahas / Kerjain / Sync / Audit
      if (/(rapat|meeting|kumpul|ngomongin|diskusi|briefing|sync|war room|bahas|kerjain|audit|tinjau|eval)/i.test(lower)) {
        const smartDelegateIds = selectSmartDelegates(rawText);
        const classification = classifyPromptTheme(rawText);
        const delegates = smartDelegateIds.map(id => {
          return pixelOfficeStations.find(s => s.id === id) || OFFICE_STATIONS.find(s => s.id === id) || { id, title: 'Specialist', dept: 'engineering' };
        });

        let snippet = rawText.replace(/^(ayo|tolong|coba|semua|guys|rekan-rekan)\\s+/i, '').trim();
        if (snippet.length > 38) snippet = snippet.slice(0, 35) + '...';

        const delegateNames = delegates.map(d => d.title).join(', ');
        setTimeout(() => {
          appendCommanderChat('Root Orchestrator', `Perintah diterima Commander! Memanggil delegasi (${delegateNames}) ke War Room untuk agenda: "${snippet}".`, 'text-cyan-300', 'text-cyan-400');
        }, 150);

        setTimeout(() => {
          const d0 = delegates[0];
          let d0Color = 'text-purple-300', d0Tag = 'text-purple-400';
          if (d0.dept === 'secops') { d0Color = 'text-amber-300'; d0Tag = 'text-amber-400'; }
          else if (d0.dept === 'intelligence') { d0Color = 'text-emerald-300'; d0Tag = 'text-emerald-400'; }
          appendCommanderChat(d0.title, `Siap Commander! Workstation diamankan, otw War Room membawa data ${classification.cleanTopic}.`, d0Color, d0Tag);
        }, 450);

        setTimeout(() => {
          const d1 = delegates[1];
          let d1Color = 'text-amber-300', d1Tag = 'text-amber-400';
          if (d1.dept === 'engineering') { d1Color = 'text-purple-300'; d1Tag = 'text-purple-400'; }
          else if (d1.dept === 'intelligence') { d1Color = 'text-emerald-300'; d1Tag = 'text-emerald-400'; }
          appendCommanderChat(d1.title, `Standby di War Room. Pipeline & metrik siap dievaluasi.`, d1Color, d1Tag);
        }, 750);

        // Convene War Room meeting with dynamic participants and custom topic
        callTeamMeeting(smartDelegateIds, classification.cleanTopic, rawText);
        return;
      }

      // Pattern B: Break / Ngopi / Istirahat
      if (/(kopi|coffee|rehat|break|istirahat|santai|cafe|lounge|espresso)/i.test(lower)) {
        setTimeout(() => {
          appendCommanderChat('Root Orchestrator', 'Perintah diterima, Commander! Semua agen standby dipersilakan santai sejenak di Breakroom & Lounge.', 'text-cyan-300', 'text-cyan-400');
        }, 200);
        setTimeout(() => {
          appendCommanderChat('Espresso Barista', 'Mesin espresso siap menyala! Silakan mampir ke cafe.', 'text-orange-300', 'text-orange-400');
        }, 600);
        highlightZone('cafe');
        return;
      }

      // Pattern C: Security / Pentest / Audit / Zero-Trust
      if (/(secops|security|pentest|zero-trust|scan|vulnerability|threat)/i.test(lower)) {
        const smartDelegateIds = selectSmartDelegates(rawText);
        const delegates = smartDelegateIds.map(id => pixelOfficeStations.find(s => s.id === id) || OFFICE_STATIONS.find(s => s.id === id) || { id, title: 'Sentinel', dept: 'secops' });
        setTimeout(() => {
          appendCommanderChat('Root Orchestrator', `Menginstruksikan tim QA & SecOps (${delegates.map(d => d.title).join(', ')}) untuk threat surface enumeration!`, 'text-cyan-300', 'text-cyan-400');
        }, 200);
        setTimeout(() => {
          appendCommanderChat(delegates[0].title, 'Zero-Trust scanning aktif. Port monitoring dan credential gate dalam kondisi siaga.', 'text-amber-300', 'text-amber-400');
        }, 600);
        highlightZone('secops');
        callTeamMeeting(smartDelegateIds, 'Security Audit & Threat Mapping', rawText);
        return;
      }

      // Pattern D: Engineering / Code / Deploy / Build
      if (/(deploy|build|coding|frontend|backend|feature|bug|refactor|ast|unit test)/i.test(lower)) {
        const smartDelegateIds = selectSmartDelegates(rawText);
        const delegates = smartDelegateIds.map(id => pixelOfficeStations.find(s => s.id === id) || OFFICE_STATIONS.find(s => s.id === id) || { id, title: 'Engineer', dept: 'engineering' });
        setTimeout(() => {
          appendCommanderChat('Root Orchestrator', `Menginstruksikan Engineering Hub (${delegates.map(d => d.title).join(', ')}) untuk memprioritaskan pipeline ini!`, 'text-cyan-300', 'text-cyan-400');
        }, 200);
        setTimeout(() => {
          appendCommanderChat(delegates[0].title, 'Understood Commander! Menyiapkan contract testing dan AST verification.', 'text-purple-300', 'text-purple-400');
        }, 600);
        highlightZone('engineering');
        callTeamMeeting(smartDelegateIds, 'Engineering Pipeline & DoD', rawText);
        return;
      }

      // Pattern E: General Status / Unmatched Command
      const smartDelegateIds = selectSmartDelegates(rawText);
      setTimeout(() => {
        appendCommanderChat('Root Orchestrator', `Perintah dicatat, Commander: "${rawText}". Mengarahkan perwakilan divisi ke War Room.`, 'text-cyan-300', 'text-cyan-400');
      }, 250);
      callTeamMeeting(smartDelegateIds, 'Strategic Directive', rawText);
    }

    // --- CANVAS ENGINE CONTROLLER & MAIN LOOP ---
    let pixelOfficeCanvas = null;
    let pixelOfficeCtx = null;
    let pixelOfficeAnimationId = null;
    let pixelOfficeFrame = 0;
    let pixelOfficeStations = [];
    let pixelOfficeHoverIdx = -1;

    const CANVAS_W = 768;
    const CANVAS_H = 512;
    const COLS = 48;
    const ROWS = 32;
    const TILE_SIZE = 16;

    // Room boundaries & metadata
    const ROOMS = [
      { id: 'executive', name: 'WAR ROOM', c1: 2, r1: 1, c2: 15, r2: 14, getTex: () => fMahogany, wall: '#2a1a16', base: '#41261e' },
      { id: 'intelligence', name: 'RECON & INTEL', c1: 17, r1: 1, c2: 30, r2: 14, getTex: () => fTechBlue, wall: '#162030', base: '#26364e' },
      { id: 'engineering', name: 'ENGINEERING', c1: 32, r1: 1, c2: 46, r2: 14, getTex: () => fEmerald, wall: '#12241c', base: '#203c30' },
      { id: 'intelligence', name: 'KNOWLEDGE VAULT', c1: 2, r1: 17, c2: 15, r2: 30, getTex: () => fAmber, wall: '#302418', base: '#4c3824' },
      { id: 'secops', name: 'QA & VERIFY', c1: 17, r1: 17, c2: 30, r2: 30, getTex: () => fViolet, wall: '#201a2c', base: '#342a46' },
      { id: 'cafe', name: 'BREAKROOM & LOUNGE', c1: 32, r1: 17, c2: 46, r2: 30, getTex: () => fCafe, wall: '#1e1c20', base: '#322e36' }
    ];

    function isRoomActive(roomId) {
      if (activeZoneFilter === 'all') return true;
      if (activeZoneFilter === roomId) return true;
      if (activeZoneFilter === 'cafe' && roomId === 'cafe') return true;
      return false;
    }

    function drawCharFrame(ctx, charIdx, dir, action, frame, dx, dy) {
      const charImg = PIXEL_IMAGES[`assets/characters/char_${charIdx % 6}.png`];
      if (!charImg) return;
      const dirRows = { 'down': 0, 'up': 1, 'right': 2, 'left': 2 };
      const rowY = (dirRows[dir] || 0) * 32;
      let frameX = 0;
      if (action === 'walk') frameX = (frame % 4) * 16;
      else if (action === 'typing') frameX = (4 + (frame % 2)) * 16;
      else frameX = 6 * 16;

      ctx.save();
      if (dir === 'left') {
        ctx.translate(dx + 16, dy);
        ctx.scale(-1, 1);
        ctx.drawImage(charImg, frameX, rowY, 16, 32, 0, 0, 16, 32);
      } else {
        ctx.drawImage(charImg, frameX, rowY, 16, 32, dx, dy, 16, 32);
      }
      ctx.restore();
    }

    function drawHoverReticle(ctx, px, py) {
      ctx.save();
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.5;
      const rw = 22, rh = 28;
      const rx = px - rw / 2;
      const ry = py - 18;

      const len = 4;
      // Top-Left
      ctx.beginPath(); ctx.moveTo(rx, ry + len); ctx.lineTo(rx, ry); ctx.lineTo(rx + len, ry); ctx.stroke();
      // Top-Right
      ctx.beginPath(); ctx.moveTo(rx + rw - len, ry); ctx.lineTo(rx + rw, ry); ctx.lineTo(rx + rw, ry + len); ctx.stroke();
      // Bottom-Left
      ctx.beginPath(); ctx.moveTo(rx, ry + rh - len); ctx.lineTo(rx, ry + rh); ctx.lineTo(rx + len, ry + rh); ctx.stroke();
      // Bottom-Right
      ctx.beginPath(); ctx.moveTo(rx + rw - len, ry + rh); ctx.lineTo(rx + rw, ry + rh); ctx.lineTo(rx + rw, ry + rh - len); ctx.stroke();
      ctx.restore();
    }

    function drawFloatingBadge(ctx, px, py, staff, slot, isHovered, frame) {
      ctx.save();
      const rawTitle = staff.role || slot.title || 'Staff Agent';
      let roleText = getFormattedRole(rawTitle);

      const anim = agentAnimState[slot.id];
      let dotColor = '#10b981';
      if (anim && anim.state === 'in_meeting') {
        dotColor = '#f59e0b';
        roleText = roleText + ' [Sync]';
      } else if (anim && anim.state === 'walk_to_meeting') {
        dotColor = '#38bdf8';
        roleText = roleText + ' [En Route]';
      } else if (anim && anim.state === 'walk_to_desk') {
        dotColor = '#38bdf8';
        roleText = roleText + ' [Return]';
      } else if (staff.desk_status === 'IN_MEETING') {
        dotColor = '#f59e0b';
      } else if (staff.desk_status === 'STANDBY' && (!anim || anim.state === 'idle')) {
        dotColor = '#94a3b8';
      } else if (staff.desk_status === 'BLOCKED') {
        dotColor = '#ef4444';
      }

      let borderColor = 'rgba(255,255,255,0.18)';
      if (slot.dept === 'executive') borderColor = 'rgba(56, 189, 248, 0.75)';
      else if (slot.dept === 'engineering') borderColor = 'rgba(192, 132, 252, 0.75)';
      else if (slot.dept === 'intelligence') borderColor = 'rgba(52, 211, 153, 0.75)';
      else if (slot.dept === 'secops') borderColor = 'rgba(251, 191, 36, 0.75)';
      else if (slot.dept === 'cafe') borderColor = 'rgba(244, 114, 182, 0.75)';

      ctx.font = '600 7px "JetBrains Mono", Consolas, monospace';
      const textWidth = ctx.measureText(roleText).width;
      const badgeW = textWidth + 12;
      const badgeH = 11;
      const badgeX = Math.round(px - (badgeW / 2));
      const badgeY = Math.round(py - (badgeH / 2));

      // High-contrast drop shadow
      ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
      ctx.fillRect(badgeX + 1, badgeY + 1, badgeW, badgeH);

      // Main Badge Body
      ctx.fillStyle = isHovered ? 'rgba(18, 22, 34, 0.98)' : 'rgba(12, 14, 22, 0.92)';
      ctx.fillRect(badgeX, badgeY, badgeW, badgeH);

      // 1px Border
      ctx.strokeStyle = isHovered ? '#38bdf8' : borderColor;
      ctx.lineWidth = isHovered ? 1.5 : 1;
      ctx.strokeRect(badgeX, badgeY, badgeW, badgeH);

      // Pulsing LED Status Dot
      const isWorking = (staff.desk_status === 'WORKING');
      const pulseSize = isWorking ? (1.5 + 0.3 * Math.sin(frame * 0.2)) : 1.5;
      ctx.fillStyle = dotColor;
      ctx.beginPath();
      ctx.arc(badgeX + 3.5, badgeY + (badgeH / 2), pulseSize, 0, Math.PI * 2);
      ctx.fill();

      // Text
      ctx.fillStyle = isHovered ? '#ffffff' : '#f1f5f9';
      ctx.textBaseline = 'middle';
      ctx.fillText(roleText, badgeX + 7.5, badgeY + (badgeH / 2) + 0.5);
      ctx.restore();
    }

    function drawMiniStatusDot(ctx, px, py, staff, frame) {
      ctx.save();
      let dotColor = '#10b981';
      if (staff.desk_status === 'IN_MEETING') dotColor = '#f59e0b';
      else if (staff.desk_status === 'STANDBY') dotColor = '#94a3b8';
      else if (staff.desk_status === 'BLOCKED') dotColor = '#ef4444';

      const isWorking = (staff.desk_status === 'WORKING');
      const pulse = isWorking ? (1.6 + 0.4 * Math.sin(frame * 0.2)) : 1.5;
      
      // Outer glow
      ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
      ctx.beginPath();
      ctx.arc(px, py - 4, pulse + 1, 0, Math.PI * 2);
      ctx.fill();

      // Inner dot
      ctx.fillStyle = dotColor;
      ctx.beginPath();
      ctx.arc(px, py - 4, pulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    function initPixelCanvasEngine() {
      pixelOfficeCanvas = document.getElementById('pixel-office-canvas');
      if (!pixelOfficeCanvas) return;
      pixelOfficeCtx = pixelOfficeCanvas.getContext('2d');
      pixelOfficeCtx.imageSmoothingEnabled = false;

      if (!pixelOfficeCanvas.__engineInitialized) {
        pixelOfficeCanvas.__engineInitialized = true;

        pixelOfficeCanvas.addEventListener('pointermove', (e) => {
          const rect = pixelOfficeCanvas.getBoundingClientRect();
          const scaleX = CANVAS_W / rect.width;
          const scaleY = CANVAS_H / rect.height;
          const mx = (e.clientX - rect.left) * scaleX;
          const my = (e.clientY - rect.top) * scaleY;

          let foundIdx = -1;
          for (let i = 0; i < pixelOfficeStations.length; i++) {
            const slot = pixelOfficeStations[i];
            const px = slot.px || (slot.col * TILE_SIZE + 8);
            const py = slot.py || (slot.row * TILE_SIZE + 16);
            if (Math.abs(mx - px) <= 16 && Math.abs(my - py) <= 16) {
              foundIdx = i;
              break;
            }
          }

          pixelOfficeHoverIdx = foundIdx;
          updateCanvasTooltip(foundIdx);
        });

        pixelOfficeCanvas.addEventListener('pointerleave', () => {
          pixelOfficeHoverIdx = -1;
          updateCanvasTooltip(-1);
        });

        pixelOfficeCanvas.addEventListener('click', (e) => {
          if (pixelOfficeHoverIdx !== -1) {
            const staff = pixelOfficeStations[pixelOfficeHoverIdx].assignedStaff;
            if (staff && staff._registryIdx !== undefined) {
              openEmployeeDossier(staff._registryIdx);
            }
          }
        });
      }
    }

    function updateCanvasTooltip(stationIdx) {
      const tooltip = document.getElementById('pixel-canvas-tooltip');
      const tooltipBody = document.getElementById('pixel-canvas-tooltip-body');
      if (!tooltip || !tooltipBody) return;

      if (stationIdx === -1 || !pixelOfficeStations[stationIdx]) {
        tooltip.style.opacity = '0';
        return;
      }

      const slot = pixelOfficeStations[stationIdx];
      const staff = slot.assignedStaff;
      if (!staff) {
        tooltip.style.opacity = '0';
        return;
      }

      tooltip.style.left = `${slot.x}%`;
      tooltip.style.top = `${Math.max(10, slot.y - 4)}%`;
      tooltip.style.opacity = '1';

      let statusColor = 'text-emerald-400';
      if (staff.desk_status === 'IN_MEETING') statusColor = 'text-amber-400';
      else if (staff.desk_status === 'STANDBY') statusColor = 'text-gray-400';
      else if (staff.desk_status === 'BLOCKED') statusColor = 'text-red-400';

      tooltipBody.innerHTML = `
        <div class="flex items-center justify-between gap-2 pb-1.5 border-b border-hairline/60">
          <span class="font-semibold text-white truncate max-w-[140px] text-[11px]">${escapeHtml(staff.role || slot.title)}</span>
          <span class="text-[9px] px-1.5 py-0.5 rounded bg-surface-3 font-mono text-gray-300 uppercase font-medium">${escapeHtml(slot.dept)}</span>
        </div>
        <div class="py-1.5 space-y-1 text-[9.5px] font-mono text-gray-400">
          <div><span class="text-gray-500">Model:</span> <span class="text-gray-200">${escapeHtml(staff.model || 'inherit')}</span></div>
          <div><span class="text-gray-500">Status:</span> <span class="${statusColor} font-semibold">${staff.desk_status_label || staff.desk_status}</span></div>
          <div><span class="text-gray-500">Telemetry:</span> <span class="text-accent font-semibold">Step ${staff.steps_count || 1} • ${(staff.tokens_count || 0).toLocaleString()} tok</span></div>
          ${staff.active_tool ? `<div class="text-[9px] text-accent truncate"><span class="font-bold">Tool:</span> ${escapeHtml(staff.active_tool.name)}</div>` : ''}
        </div>
        <div class="pt-1.5 border-t border-hairline/40 flex items-center justify-between text-[8.5px] font-mono text-accent">
          <span class="text-gray-500 truncate max-w-[110px]">${escapeHtml(slot.title)}</span>
          <span class="font-semibold">Click Dossier &rarr;</span>
        </div>
      `;
    }

    function renderPixelFrame() {
      if (!pixelOfficeCtx || !pixelOfficeCanvas) return;
      pixelOfficeFrame++;
      pixelOfficeCtx.clearRect(0, 0, CANVAS_W, CANVAS_H);

      // Update agent lifecycle animations (walk, meeting, return)
      updateAgentAnimations();

      // Ambient meetings disabled: zero automatic looping. Meetings strictly user or subagent driven.

      if (!pixelAssetsReady) {
        // Simple loading indicator
        pixelOfficeCtx.fillStyle = '#0f1117';
        pixelOfficeCtx.fillRect(0, 0, CANVAS_W, CANVAS_H);
        pixelOfficeCtx.fillStyle = '#38bdf8';
        pixelOfficeCtx.font = '12px "JetBrains Mono", monospace';
        pixelOfficeCtx.fillText("Loading authentic pixel assets...", 260, 250);
        pixelOfficeAnimationId = requestAnimationFrame(renderPixelFrame);
        return;
      }

      // 1. Draw Warm Hardwood Parquet Corridor Floor Background
      for (let r = 0; r < ROWS; r++) {
        for (let c = 0; c < COLS; c++) {
          if (fCorridor) pixelOfficeCtx.drawImage(fCorridor, c * 16, r * 16);
        }
      }

      // 2. Draw Room Floors
      ROOMS.forEach(rm => {
        const tex = rm.getTex();
        if (!tex) return;
        const active = isRoomActive(rm.id);
        pixelOfficeCtx.globalAlpha = active ? 1.0 : 0.35;
        for (let r = rm.r1; r < rm.r2; r++) {
          for (let c = rm.c1; c < rm.c2; c++) {
            pixelOfficeCtx.drawImage(tex, c * 16, r * 16);
          }
        }
      });
      pixelOfficeCtx.globalAlpha = 1.0;

      // 3. Draw Architectural Walls & Doorways
      const WALL_C = '#202634';
      const WALL_TOP = '#323c50';
      const WALL_BASE = '#121620';
      const WALL_TRIM = '#3c4a62';

      function drawHWall(x1, y1, x2, h) {
        pixelOfficeCtx.fillStyle = WALL_C;
        pixelOfficeCtx.fillRect(x1, y1, x2 - x1, h);
        pixelOfficeCtx.fillStyle = WALL_TOP;
        pixelOfficeCtx.fillRect(x1, y1, x2 - x1, 1);
        pixelOfficeCtx.fillStyle = WALL_TRIM;
        pixelOfficeCtx.fillRect(x1, y1 + h - 4, x2 - x1, 1);
        pixelOfficeCtx.fillStyle = WALL_BASE;
        pixelOfficeCtx.fillRect(x1, y1 + h - 3, x2 - x1, 3);
        pixelOfficeCtx.fillStyle = 'rgba(0, 0, 0, 0.45)';
        pixelOfficeCtx.fillRect(x1, y1 + h, x2 - x1, 1);
      }

      function drawVWall(x1, y1, x2, y2) {
        pixelOfficeCtx.fillStyle = WALL_C;
        pixelOfficeCtx.fillRect(x1, y1, x2 - x1, y2 - y1);
        pixelOfficeCtx.fillStyle = WALL_TOP;
        pixelOfficeCtx.fillRect(x1, y1, 1, y2 - y1);
        pixelOfficeCtx.fillStyle = WALL_BASE;
        pixelOfficeCtx.fillRect(x2 - 1, y1, 1, y2 - y1);
        pixelOfficeCtx.fillStyle = 'rgba(0, 0, 0, 0.35)';
        pixelOfficeCtx.fillRect(x2, y1, 1, y2 - y1);
      }

      // Room Top Interior Walls (2 tiles high)
      ROOMS.forEach(rm => {
        const active = isRoomActive(rm.id);
        pixelOfficeCtx.globalAlpha = active ? 1.0 : 0.35;
        const wx1 = rm.c1 * 16, wy1 = rm.r1 * 16, wx2 = rm.c2 * 16, wy2 = (rm.r1 + 2) * 16;
        pixelOfficeCtx.fillStyle = rm.wall;
        pixelOfficeCtx.fillRect(wx1, wy1, wx2 - wx1, 32);
        pixelOfficeCtx.fillStyle = 'rgba(10, 12, 18, 0.9)';
        pixelOfficeCtx.fillRect(wx1, wy1, wx2 - wx1, 1);
        pixelOfficeCtx.fillStyle = rm.base;
        pixelOfficeCtx.fillRect(wx1, wy2 - 4, wx2 - wx1, 1);
        pixelOfficeCtx.fillStyle = '#0f1218';
        pixelOfficeCtx.fillRect(wx1, wy2 - 3, wx2 - wx1, 3);
        pixelOfficeCtx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        pixelOfficeCtx.fillRect(wx1, wy2 - 1, wx2 - wx1, 1);
      });
      pixelOfficeCtx.globalAlpha = 1.0;

      // Exterior Perimeter Walls
      drawHWall(0, 0, 48 * 16, 16);
      drawHWall(0, 31 * 16, 48 * 16, 16);
      drawVWall(0, 0, 32, 32 * 16);
      drawVWall(46 * 16, 0, 48 * 16, 32 * 16);

      // Vertical Dividing Walls with Doorways
      // Left vertical wall (col 15..16)
      drawVWall(15 * 16, 0, 17 * 16, 7 * 16);
      drawVWall(15 * 16, 9 * 16, 17 * 16, 14 * 16);
      drawVWall(15 * 16, 17 * 16, 17 * 16, 23 * 16);
      drawVWall(15 * 16, 25 * 16, 17 * 16, 31 * 16);

      // Right vertical wall (col 30..31)
      drawVWall(30 * 16, 0, 32 * 16, 7 * 16);
      drawVWall(30 * 16, 9 * 16, 32 * 16, 14 * 16);
      drawVWall(30 * 16, 17 * 16, 32 * 16, 23 * 16);
      drawVWall(30 * 16, 25 * 16, 32 * 16, 31 * 16);

      // Horizontal Central Corridor Dividing Walls (separates upper rooms from central hallway)
      drawHWall(2 * 16, 14 * 16, 7 * 16, 16);
      drawHWall(9 * 16, 14 * 16, 15 * 16, 16);
      drawHWall(17 * 16, 14 * 16, 23 * 16, 16);
      drawHWall(25 * 16, 14 * 16, 30 * 16, 16);
      drawHWall(32 * 16, 14 * 16, 38 * 16, 16);
      drawHWall(40 * 16, 14 * 16, 46 * 16, 16);

      // Doorframe Posts (3D metallic / wood jambs)
      const doorPosts = [
        [15 * 16, 7 * 16 - 2, 32, 2], [15 * 16, 9 * 16, 32, 2],
        [30 * 16, 7 * 16 - 2, 32, 2], [30 * 16, 9 * 16, 32, 2],
        [15 * 16, 23 * 16 - 2, 32, 2], [15 * 16, 25 * 16, 32, 2],
        [30 * 16, 23 * 16 - 2, 32, 2], [30 * 16, 25 * 16, 32, 2],
        [7 * 16 - 2, 14 * 16, 2, 16], [9 * 16, 14 * 16, 2, 16],
        [23 * 16 - 2, 14 * 16, 2, 16], [25 * 16, 14 * 16, 2, 16],
        [38 * 16 - 2, 14 * 16, 2, 16], [40 * 16, 14 * 16, 2, 16]
      ];
      pixelOfficeCtx.fillStyle = '#4a5b78';
      doorPosts.forEach(([px, py, pw, ph]) => pixelOfficeCtx.fillRect(px, py, pw, ph));

      // Carpets / Rugs (Under conference table, under lounge, under library)
      const c0 = PIXEL_IMAGES['assets/carpets/carpet_0.png'];
      const c1 = PIXEL_IMAGES['assets/carpets/carpet_1.png'];
      const c2 = PIXEL_IMAGES['assets/carpets/carpet_2.png'];
      if (c0) pixelOfficeCtx.drawImage(c0, 6 * 16, 5 * 16);
      if (c1) pixelOfficeCtx.drawImage(c1, 38 * 16, 21 * 16);
      if (c2) pixelOfficeCtx.drawImage(c2, 4 * 16, 21 * 16);

      // Central Corridor Crimson Runner Rug (Full Architectural Width, Col 2 to Col 46)
      const rx1 = 2 * 16, ry1 = 15 * 16 + 1, rw = 44 * 16, rh = 14;
      pixelOfficeCtx.fillStyle = '#6a2024';
      pixelOfficeCtx.fillRect(rx1, ry1, rw, rh);
      pixelOfficeCtx.strokeStyle = '#b8444c';
      pixelOfficeCtx.lineWidth = 1;
      pixelOfficeCtx.strokeRect(rx1, ry1, rw, rh);
      // Double Gold Satin Running Stripes
      pixelOfficeCtx.fillStyle = '#d4a359';
      pixelOfficeCtx.fillRect(rx1, ry1 + 2, rw, 1);
      pixelOfficeCtx.fillRect(rx1, ry1 + rh - 3, rw, 1);
      // Gold Fringe Tassels at Both Ends
      pixelOfficeCtx.fillStyle = '#f59e0b';
      pixelOfficeCtx.fillRect(rx1, ry1 + 1, 3, rh - 2);
      pixelOfficeCtx.fillRect(rx1 + rw - 3, ry1 + 1, 3, rh - 2);

      // 4. Assemble Z-Sorted Drawables
      const drawables = [];

      function addObj(imgKey, col, row, ox = 0, oy = 0, flip = false, active = true, zyOffset = 0) {
        const img = PIXEL_IMAGES[imgKey];
        if (!img) return;
        const x = col * 16 + ox;
        const y = row * 16 + oy;
        drawables.push({
          zy: y + img.height + zyOffset,
          draw: () => {
            pixelOfficeCtx.save();
            pixelOfficeCtx.globalAlpha = active ? 1.0 : 0.35;
            if (flip) {
              pixelOfficeCtx.translate(x + img.width, y);
              pixelOfficeCtx.scale(-1, 1);
              pixelOfficeCtx.drawImage(img, 0, 0);
            } else {
              pixelOfficeCtx.drawImage(img, x, y);
            }
            pixelOfficeCtx.restore();
          }
        });
      }

      // ── CORRIDOR AMENITIES & DECOR (Clean, Symmetrical & Consistent) ──
      // Waiting benches placed neatly between portals
      addObj('assets/furniture/WOODEN_BENCH/WOODEN_BENCH.png', 17, 15, 0, 0, false, true);
      addObj('assets/furniture/WOODEN_BENCH/WOODEN_BENCH.png', 31, 15, 0, 0, false, true);
      // Symmetrical indoor architectural potted plants (16x32 PLANT) flanking doorways
      addObj('assets/furniture/PLANT/PLANT.png', 6, 14, 0, 0, false, true);
      addObj('assets/furniture/PLANT/PLANT.png', 11, 14, 0, 0, false, true);
      addObj('assets/furniture/PLANT/PLANT.png', 21, 14, 0, 0, false, true);
      addObj('assets/furniture/PLANT/PLANT.png', 26, 14, 0, 0, false, true);
      addObj('assets/furniture/PLANT/PLANT.png', 36, 14, 0, 0, false, true);
      addObj('assets/furniture/PLANT/PLANT.png', 41, 14, 0, 0, false, true);
      // Clean framed paintings centered on dividing walls
      addObj('assets/furniture/SMALL_PAINTING/SMALL_PAINTING.png', 14, 14, 0, 0, false, true);
      addObj('assets/furniture/SMALL_PAINTING/SMALL_PAINTING.png', 29, 14, 0, 0, false, true);

      // ── FIXED STATIC FURNITURE & DECOR (Uniform Corner Palms, Zero Clutter) ──
      // Room 1: War Room Decor
      addObj('assets/furniture/BOOKSHELF/BOOKSHELF.png', 3, 1, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/CLOCK/CLOCK.png', 8, 1, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/LARGE_PAINTING/LARGE_PAINTING.png', 11, 1, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/WHITEBOARD/WHITEBOARD.png', 2, 4, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/TABLE_FRONT/TABLE_FRONT.png', 7, 6, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/WOODEN_CHAIR/WOODEN_CHAIR_SIDE.png', 6, 7, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/WOODEN_CHAIR/WOODEN_CHAIR_SIDE.png', 6, 9, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/WOODEN_CHAIR/WOODEN_CHAIR_SIDE.png', 10, 7, 0, 0, true, isRoomActive('executive'));
      addObj('assets/furniture/WOODEN_CHAIR/WOODEN_CHAIR_SIDE.png', 10, 9, 0, 0, true, isRoomActive('executive'));
      addObj('assets/furniture/PC/PC_SIDE.png', 7, 7, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/PC/PC_SIDE.png', 7, 9, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/PC/PC_SIDE.png', 9, 7, 0, 0, true, isRoomActive('executive'));
      addObj('assets/furniture/PC/PC_SIDE.png', 9, 9, 0, 0, true, isRoomActive('executive'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 13, 2, 0, 0, false, isRoomActive('executive'));
      addObj('assets/furniture/BIN/BIN.png', 13, 12, 0, 0, false, isRoomActive('executive'));

      // Room 2: Recon Decor
      addObj('assets/furniture/WHITEBOARD/WHITEBOARD.png', 18, 1, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/LARGE_PAINTING/LARGE_PAINTING.png', 24, 1, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 28, 2, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 28, 4, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 28, 7, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/BIN/BIN.png', 28, 12, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/CLOCK/CLOCK.png', 21, 1, 0, 0, false, isRoomActive('intelligence'));

      // Room 3: Engineering Decor
      addObj('assets/furniture/WHITEBOARD/WHITEBOARD.png', 33, 1, 0, 0, false, isRoomActive('engineering'));
      addObj('assets/furniture/CLOCK/CLOCK.png', 38, 1, 0, 0, false, isRoomActive('engineering'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 41, 1, 0, 0, false, isRoomActive('engineering'));
      addObj('assets/furniture/BIN/BIN.png', 44, 1, 0, 0, false, isRoomActive('engineering'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 32, 11, 0, 0, false, isRoomActive('engineering'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 44, 11, 0, 0, false, isRoomActive('engineering'));

      // Room 4: Knowledge Vault Decor
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 3, 17, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 6, 17, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 9, 17, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 12, 17, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/CLOCK/CLOCK.png', 8, 17, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 13, 18, 0, 0, false, isRoomActive('intelligence'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 11, 29, 0, 0, false, isRoomActive('intelligence'));

      // Room 5: QA Decor
      addObj('assets/furniture/WHITEBOARD/WHITEBOARD.png', 18, 17, 0, 0, false, isRoomActive('secops'));
      addObj('assets/furniture/CLOCK/CLOCK.png', 24, 17, 0, 0, false, isRoomActive('secops'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 28, 18, 0, 0, false, isRoomActive('secops'));
      addObj('assets/furniture/BIN/BIN.png', 28, 28, 0, 0, false, isRoomActive('secops'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 18, 27, 0, 0, false, isRoomActive('secops'));
      addObj('assets/furniture/DOUBLE_BOOKSHELF/DOUBLE_BOOKSHELF.png', 28, 23, 0, 0, false, isRoomActive('secops'));

      // Room 6: Breakroom Decor & Gitcat Pet
      addObj('assets/furniture/SMALL_TABLE/SMALL_TABLE_FRONT.png', 33, 19, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/COFFEE/COFFEE.png', 33, 18, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/SMALL_TABLE/SMALL_TABLE_FRONT.png', 35, 19, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/COFFEE_TABLE/COFFEE_TABLE.png', 40, 23, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/SOFA/SOFA_FRONT.png', 40, 21, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/SOFA/SOFA_BACK.png', 40, 25, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/SOFA/SOFA_SIDE.png', 38, 23, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/SOFA/SOFA_SIDE.png', 42, 23, 0, 0, true, isRoomActive('cafe'));
      addObj('assets/furniture/LARGE_PLANT/LARGE_PLANT.png', 44, 18, 0, 0, false, isRoomActive('cafe'));
      addObj('assets/furniture/CACTUS/CACTUS.png', 44, 27, 0, 0, false, isRoomActive('cafe'));

      // Gitcat Pet resting in Breakroom
      const gitcatImg = PIXEL_IMAGES['assets/pets/gitcat/pet.png'];
      if (gitcatImg) {
        drawables.push({
          zy: 26 * 16 + 16,
          draw: () => {
            pixelOfficeCtx.drawImage(gitcatImg, 0, 0, 32, 32, 37 * 16, 26 * 16, 24, 24);
          }
        });
      }

      // (Corridor Roaming Agent removed — agents now walk dynamically via lifecycle state machine)

      // ── DYNAMIC AGENT STATIONS & WORKSTATIONS (Lifecycle-Driven) ──
      const overheadBadges = [];

      for (let sIdx = 0; sIdx < pixelOfficeStations.length; sIdx++) {
        const slot = pixelOfficeStations[sIdx];
        const staff = slot.assignedStaff;
        if (!staff) continue;

        const isSlotActive = isRoomActive(slot.dept);
        const isHovered = (pixelOfficeHoverIdx === sIdx);
        const isWorking = (staff.desk_status === 'WORKING');
        const deptCharMap = { 'executive': 0, 'secops': 1, 'engineering': 2, 'intelligence': 3, 'knowledge': 4, 'cafe': 5 };
        const charIdx = (deptCharMap[slot.dept] !== undefined) ? deptCharMap[slot.dept] : (sIdx % 6);
        const atDesk = isAgentAtDesk(slot.id);
        const anim = agentAnimState[slot.id];

        // ── FURNITURE (Desk and PC have standard natural Z-depth) ──
        if (slot.dir === 'up') {
          const deskC = slot.col - 1;
          const deskR = slot.row - 1;
          // Desk footprint at row deskR, depth is natural (no artificial offset blocking the seated agent)
          addObj('assets/furniture/DESK/DESK_FRONT.png', deskC, deskR, 0, 0, false, isSlotActive, 0);
          const pcFrame = 1 + (Math.floor((pixelOfficeFrame + sIdx * 7) / 14) % 3);
          addObj(`assets/furniture/PC/PC_FRONT_ON_${pcFrame}.png`, deskC + 1, deskR - 1, 0, 0, false, isSlotActive, 0);
          addObj('assets/furniture/CUSHIONED_BENCH/CUSHIONED_BENCH.png', deskC + 1, deskR + 1, 0, 0, false, isSlotActive, 0);
        }

        // ── AGENT CHARACTER (position depends on lifecycle state) ──
        if (atDesk) {
          // Agent is at their desk (idle, working, or just returned)
          if (slot.dir === 'up') {
            const deskC = slot.col - 1;
            const deskR = slot.row - 1;
            const tx = (deskC + 1) * 16;
            // Placed naturally on the cushioned bench facing north at the desk keyboard
            const ty = deskR * 16 + 18;
            const isTyping = (anim && anim.state === 'working_at_desk') || isWorking;
            const bob = isTyping ? (Math.floor((pixelOfficeFrame + sIdx) / 8) % 2) : 0;

            drawables.push({
              // Seated agent Z-depth is higher than the desk (deskR*16 + 32) so upper body, head & typing arms are 100% VISIBLE!
              zy: deskR * 16 + 48,
              draw: () => {
                pixelOfficeCtx.save();
                pixelOfficeCtx.globalAlpha = isSlotActive ? 1.0 : 0.35;
                if (isHovered) drawHoverReticle(pixelOfficeCtx, tx + 8, ty + 16);
                drawCharFrame(pixelOfficeCtx, charIdx, 'up', isTyping ? 'typing' : 'idle', pixelOfficeFrame + sIdx, tx, ty - bob);
                pixelOfficeCtx.restore();
              }
            });

            overheadBadges.push({
              bx: tx + 8 + (slot.badge_ox || 0),
              by: deskR * 16 - 12 + (slot.badge_oy ? (slot.badge_oy + 26) : 0),
              staff: staff, slot: slot, isHovered: isHovered
            });
          } else {
            const tx = slot.col * 16;
            const ty = slot.row * 16 - 4;
            const isTyping = (anim && anim.state === 'working_at_desk') || isWorking;
            const bob = isTyping ? (Math.floor((pixelOfficeFrame + sIdx) / 8) % 2) : 0;

            drawables.push({
              zy: ty + 16,
              draw: () => {
                pixelOfficeCtx.save();
                pixelOfficeCtx.globalAlpha = isSlotActive ? 1.0 : 0.35;
                if (isHovered) drawHoverReticle(pixelOfficeCtx, tx + 8, ty + 16);
                drawCharFrame(pixelOfficeCtx, charIdx, slot.dir, isTyping ? 'typing' : 'idle', pixelOfficeFrame + sIdx, tx, ty - bob);
                pixelOfficeCtx.restore();
              }
            });

            overheadBadges.push({
              bx: tx + 8 + (slot.badge_ox || 0),
              by: ty + (slot.badge_oy || -24),
              staff: staff, slot: slot, isHovered: isHovered
            });
          }
        } else if (anim) {
          // Agent is walking or in a meeting — draw at interpolated position
          const apx = Math.round(anim.px);
          const apy = Math.round(anim.py);
          const animAction = getAgentAnimAction(slot.id) || 'walk';
          const animDir = anim.walkDir || slot.dir;

          drawables.push({
            zy: apy + 24,
            draw: () => {
              pixelOfficeCtx.save();
              pixelOfficeCtx.globalAlpha = 1.0;
              drawCharFrame(pixelOfficeCtx, charIdx, animDir, animAction, pixelOfficeFrame + sIdx, apx, apy);
              pixelOfficeCtx.restore();
            }
          });

          // Badge follows the walking agent
          overheadBadges.push({
            bx: apx + 8,
            by: apy - 14,
            staff: staff, slot: slot, isHovered: false
          });
        }
      }

      // Sort Drawables by Z-Depth (Sandwich Occlusion)
      drawables.sort((a, b) => a.zy - b.zy);
      drawables.forEach(d => {
        try { d.draw(); } catch (e) { console.error("Drawable error:", e); }
      });

      // ── TOP-MOST RENDER PASS: OVERHEAD UI BADGES ──
      // Rendered AFTER all world objects so NO furniture, desk, PC, or decor ever occludes them!
      const speakingId = getActiveSpeakingAgentId();
      overheadBadges.sort((a, b) => (a.isHovered ? 1 : 0) - (b.isHovered ? 1 : 0));
      overheadBadges.forEach(b => {
        try {
          if (speakingId && (speakingId === b.slot.id || (speakingId === '__chorus__' && activeMeetingSession && activeMeetingSession.participants.includes(b.slot.id)))) {
            return; // Suppress small badge while speech bubble is active to prevent visual clutter
          }
          drawFloatingBadge(pixelOfficeCtx, b.bx, b.by, b.staff, b.slot, b.isHovered, pixelOfficeFrame);
        } catch (e) {
          console.error("Overhead badge render error:", e);
        }
      });

      // ── TOP-MOST WAR ROOM HUD MEETING BANNER (Active when agents assemble) ──
      const activeMeetingStaff = [];
      for (const slotId in agentAnimState) {
        const anim = agentAnimState[slotId];
        if (anim && (anim.state === 'in_meeting' || anim.state === 'walk_to_meeting')) {
          activeMeetingStaff.push(slotId);
        }
      }

      if (activeMeetingStaff.length > 0) {
        const inSession = activeMeetingStaff.some(sId => agentAnimState[sId].state === 'in_meeting');
        const bx = 8 * 16;  // Center X = 128
        const by = 4 * 16 - 2; // Y = 62
        const bw = 152, bh = 22;

        pixelOfficeCtx.save();
        // High-contrast drop shadow
        pixelOfficeCtx.fillStyle = 'rgba(0, 0, 0, 0.85)';
        pixelOfficeCtx.fillRect(bx - bw / 2 + 1, by - bh / 2 + 1, bw, bh);

        // Dark slate backdrop
        pixelOfficeCtx.fillStyle = 'rgba(12, 15, 24, 0.96)';
        pixelOfficeCtx.fillRect(bx - bw / 2, by - bh / 2, bw, bh);

        // Border
        pixelOfficeCtx.strokeStyle = inSession ? '#f59e0b' : '#38bdf8';
        pixelOfficeCtx.lineWidth = 1.2;
        pixelOfficeCtx.strokeRect(bx - bw / 2, by - bh / 2, bw, bh);

        // Pulsing Status Dot
        const pulse = 1.6 + 0.5 * Math.sin(pixelOfficeFrame * 0.18);
        pixelOfficeCtx.fillStyle = inSession ? '#fbbf24' : '#38bdf8';
        pixelOfficeCtx.beginPath();
        pixelOfficeCtx.arc(bx - bw / 2 + 7, by - 3, pulse, 0, Math.PI * 2);
        pixelOfficeCtx.fill();

        // Header Text
        pixelOfficeCtx.font = 'bold 7px "JetBrains Mono", Consolas, monospace';
        pixelOfficeCtx.fillStyle = inSession ? '#fbbf24' : '#38bdf8';
        pixelOfficeCtx.textBaseline = 'middle';
        pixelOfficeCtx.fillText(inSession ? 'WAR ROOM: SYNC ALIGNMENT' : 'WAR ROOM: DELEGATES EN ROUTE', bx - bw / 2 + 13, by - 3);

        // Subtitle Narrative
        pixelOfficeCtx.font = '6px "JetBrains Mono", Consolas, monospace';
        pixelOfficeCtx.fillStyle = '#94a3b8';
        let subText = 'Subagents navigating to conference table...';
        if (inSession) {
          const topicName = (activeMeetingSession && (activeMeetingSession.rawPrompt || activeMeetingSession.mission)) || 'Strategy Alignment';
          let shortTopic = topicName.replace(/^(ayo|tolong|coba|semua|guys|rekan-rekan)\\s+/i, '').trim();
          if (shortTopic.length > 30) shortTopic = shortTopic.slice(0, 27) + '...';
          subText = `Agenda: ${shortTopic}`;
        }
        pixelOfficeCtx.fillText(subText, bx - bw / 2 + 7, by + 5);
        pixelOfficeCtx.restore();
      }

      // ── TOP-MOST OVERHEAD CHAT SPEECH BUBBLES (Dynamic Conversations) ──
      if (activeMeetingSession && activeMeetingSession.active) {
        try {
          const anyInMeeting = activeMeetingSession.participants.some(id => {
            const a = agentAnimState[id];
            return a && a.state === 'in_meeting';
          });

          if (anyInMeeting) {
            activeMeetingSession.frame++;
            const currentFrame = activeMeetingSession.frame;

            for (let i = 0; i < activeMeetingSession.dialogues.length; i++) {
              const d = activeMeetingSession.dialogues[i];
              if (currentFrame >= d.startFrame && currentFrame < d.startFrame + d.duration) {
                const progress = (currentFrame - d.startFrame) / d.duration;

                if (currentFrame === d.startFrame) {
                  console.log(`[Meeting Dialogue] Turn ${i + 1}/${activeMeetingSession.dialogues.length}: ${d.speakerRole || 'Chorus'} -> [Thought: ${d.thought || '-'}] "${d.speech || d.text || 'Chorus Reactions'}"`);
                  appendCommanderMeetingTurn(d);
                }

                if (d.isChorus) {
                  // Simultaneous reaction bubbles above all participants
                  d.chorusItems.forEach(item => {
                    const pos = getSpeakerHeadPos(item.speakerId);
                    let col = '#38bdf8';
                    if (item.dept === 'engineering') col = '#c084fc';
                    else if (item.dept === 'intelligence') col = '#34d399';
                    else if (item.dept === 'secops') col = '#fbbf24';
                    drawMiniEmoteBubble(pixelOfficeCtx, pos.x, pos.y, item.text, col);
                  });
                } else {
                  // Single active speech bubble pointing down to speaker
                  const pos = getSpeakerHeadPos(d.speakerId);
                  drawSpeechBubble(pixelOfficeCtx, pos.x, pos.y, d.speakerRole, d.speech || d.text, d.dept, progress, d.thought);
                }
                break;
              }
            }

            if (activeMeetingSession.frame >= MEETING_DURATION) {
              activeMeetingSession.active = false;
            }
          }
        } catch (e) {
          console.error("[SpeechBubble Error]", e);
        }
      }

      pixelOfficeAnimationId = requestAnimationFrame(renderPixelFrame);
    }

    function renderPixelOffice(data) {
      initPixelCanvasEngine();

      if (!pixelAssetsReady) {
        initPixelAssets(() => {
          renderPixelOffice(data);
        });
      }

      const depts = data.departments || {};
      const parentAgent = (depts.executive && depts.executive.staff && depts.executive.staff[0]) ? depts.executive.staff[0] : null;
      const realSubagents = data.subagents || [];

      // Auto-trigger War Room meeting ONLY when actual new subagent count increases (zero false triggers)
      const currentMission = data.mission || (data.active_session && data.active_session.mission) || '';
      const currentSubs = realSubagents.length;
      if (lastKnownSubagentCount !== -1 && currentSubs > lastKnownSubagentCount) {
        console.log("[Auto-Delegation] New subagent detected -> Convening War Room alignment meeting with LLM debate!");
        callTeamMeeting(null, currentMission);
      }
      lastKnownSubagentCount = currentSubs;
      lastKnownMission = currentMission;
      currentOfficeMission = currentMission;

      // Clone stations and compute pixel positions
      const stations = JSON.parse(JSON.stringify(OFFICE_STATIONS));
      stations.forEach(slot => {
        slot.px = slot.col * TILE_SIZE + 8;
        slot.py = slot.row * TILE_SIZE + 16;
        slot.x = (slot.px / CANVAS_W) * 100;
        slot.y = (slot.py / CANVAS_H) * 100;
      });
      officeStaffRegistry = [];

      // 1. Assign Parent Orchestrator
      if (parentAgent) {
        const execSlot = stations.find(s => s.id === 'exec_1');
        if (execSlot) {
          execSlot.assignedStaff = parentAgent;
          parentAgent._registryIdx = officeStaffRegistry.length;
          officeStaffRegistry.push(parentAgent);
        }
      }

      // 2. Assign real subagents
      let unassignedSubs = [...realSubagents];
      for (const sa of unassignedSubs) {
        const deptKey = sa.department || 'engineering';
        const slot = stations.find(s => s.dept === deptKey && !s.assignedStaff && s.id !== 'exec_1');
        if (slot) {
          slot.assignedStaff = sa;
          sa._registryIdx = officeStaffRegistry.length;
          officeStaffRegistry.push(sa);
        } else {
          const anySlot = stations.find(s => !s.assignedStaff && s.id !== 'exec_1');
          if (anySlot) {
            anySlot.assignedStaff = sa;
            anySlot._registryIdx = officeStaffRegistry.length;
            officeStaffRegistry.push(anySlot);
          }
        }
      }

      // 3. Fill remaining stations with active specialist staff
      stations.forEach((slot, idx) => {
        if (!slot.assignedStaff) {
          const isExec = slot.dept === 'executive';
          const isSec = slot.dept === 'secops';
          const isCafe = slot.id.startsWith('cafe');

          let defaultStatus = slot.status || (isSec ? 'IN_MEETING' : (isCafe ? 'STANDBY' : 'WORKING'));
          let statusLabel = defaultStatus === 'WORKING' ? 'In Deep Focus' : (defaultStatus === 'IN_MEETING' ? 'In Sync Meeting' : 'On Standby');

          const virtualStaff = {
            id: `staff-${slot.id}`,
            role: slot.title,
            department: slot.dept,
            desk_status: defaultStatus,
            desk_status_label: statusLabel,
            model: isExec ? 'gemini-2.5-pro' : (isSec ? 'gemini-2.5-flash' : 'gemini-2.5-flash-lite'),
            steps_count: 12 + ((idx * 3) % 27),
            tokens_count: 14500 + ((idx * 2150) % 36000),
            last_active: 'Now',
            prompt: `Assigned to ${slot.toolSummary} at ${slot.title}. Collaborating autonomously with zero silent assumptions.`,
            full_prompt: `Operational Directives: Maintain operational excellence for ${slot.title}.\nScope: ${slot.toolSummary}.\nPrinciple: 70% pragmatic reliability + 30% bleeding-edge optimization.`,
            active_tool: {
              name: slot.defaultTool,
              action: slot.toolSummary,
              summary: slot.toolSummary
            },
            is_parent: false,
            is_virtual: true
          };
          virtualStaff._registryIdx = officeStaffRegistry.length;
          officeStaffRegistry.push(virtualStaff);
          slot.assignedStaff = virtualStaff;
        }
      });

      pixelOfficeStations = stations;

      // Initialize animation state for all stations
      stations.forEach(slot => {
        if (!agentAnimState[slot.id]) {
          agentAnimState[slot.id] = { state: 'idle' };
        }
      });

      // Schedule first ambient meeting after a short warmup
      if (nextAmbientMeetingFrame < pixelOfficeFrame + 300) {
        nextAmbientMeetingFrame = pixelOfficeFrame + 300 + Math.floor(Math.random() * 300);
      }

      if (!pixelOfficeAnimationId) {
        pixelOfficeAnimationId = requestAnimationFrame(renderPixelFrame);
      }
    }

    function setPixelStageScale(mode) {
      currentPixelStageScale = mode;
      const stage = document.getElementById('pixel-stage');
      const btnFit = document.getElementById('btn-stage-fit');
      const btn100 = document.getElementById('btn-stage-100');
      const btn150 = document.getElementById('btn-stage-150');
      if (!stage) return;

      const activeBtnClass = 'btn-spring px-2 py-0.5 rounded border border-accent/40 bg-accent/20 text-accent transition-all font-medium';
      const inactiveBtnClass = 'btn-spring px-2 py-0.5 rounded border border-hairline bg-surface-2 hover:bg-surface-3 text-gray-400 hover:text-white transition-all';

      if (btnFit) btnFit.className = (mode === 'fit') ? activeBtnClass : inactiveBtnClass;
      if (btn100) btn100.className = (mode === '100') ? activeBtnClass : inactiveBtnClass;
      if (btn150) btn150.className = (mode === '150') ? activeBtnClass : inactiveBtnClass;

      if (mode === '150') {
        stage.style.width = '1152px';
        stage.style.aspectRatio = '768 / 512';
      } else if (mode === '100') {
        stage.style.width = '768px';
        stage.style.aspectRatio = '768 / 512';
      } else {
        stage.style.width = '860px';
        stage.style.maxWidth = '100%';
        stage.style.aspectRatio = '768 / 512';
      }
    }

    function togglePixelCrt() {
      pixelCrtActive = !pixelCrtActive;
      const crt = document.getElementById('pixel-crt-overlay');
      const btn = document.getElementById('btn-stage-crt');
      if (crt) {
        crt.style.opacity = pixelCrtActive ? '0.75' : '0';
      }
      if (btn) {
        btn.className = pixelCrtActive
          ? 'btn-spring px-2 py-0.5 rounded border border-accent/40 bg-accent/20 text-accent transition-all font-medium'
          : 'btn-spring px-2 py-0.5 rounded border border-hairline bg-surface-2 hover:bg-surface-3 text-gray-400 hover:text-white transition-all';
      }
    }

    function highlightZone(zoneKey) {
      activeZoneFilter = zoneKey;

      const zoneBtns = ['all', 'eng', 'intel', 'exec', 'sec', 'cafe'];
      zoneBtns.forEach(zb => {
        const b = document.getElementById(`filter-zone-${zb}`);
        if (!b) return;
        const isMatch = (zb === 'all' && zoneKey === 'all') ||
                        (zb === 'eng' && zoneKey === 'engineering') ||
                        (zb === 'intel' && zoneKey === 'intelligence') ||
                        (zb === 'exec' && zoneKey === 'executive') ||
                        (zb === 'sec' && zoneKey === 'secops') ||
                        (zb === 'cafe' && zoneKey === 'cafe');
        if (isMatch) {
          b.classList.add('border-accent/40', 'bg-accent/20', 'text-accent');
        } else {
          b.classList.remove('border-accent/40', 'bg-accent/20', 'text-accent');
        }
      });
    }

    function setOfficeView(mode) {
      currentOfficeViewMode = mode;
      const btnPixel = document.getElementById('btn-view-pixel');
      const btnOffice = document.getElementById('btn-view-office');
      const btnDag = document.getElementById('btn-view-dag');
      const pixelView = document.getElementById('pixel-office-view');
      const floorView = document.getElementById('office-floor-view');
      const dagView = document.getElementById('dag-tree-view');

      const activeClass = 'px-2.5 py-1 rounded font-medium transition-all flex items-center gap-1.5 bg-accent/20 text-accent border border-accent/40';
      const inactiveClass = 'px-2.5 py-1 rounded font-medium transition-all flex items-center gap-1.5 text-gray-400 hover:text-white border border-transparent';

      if (btnPixel) btnPixel.className = mode === 'pixel' ? activeClass : inactiveClass;
      if (btnOffice) btnOffice.className = mode === 'office' ? activeClass : inactiveClass;
      if (btnDag) btnDag.className = mode === 'dag' ? activeClass : inactiveClass;

      if (pixelView) {
        if (mode === 'pixel') pixelView.classList.remove('hidden');
        else pixelView.classList.add('hidden');
      }
      if (floorView) {
        if (mode === 'office') floorView.classList.remove('hidden');
        else floorView.classList.add('hidden');
      }
      if (dagView) {
        if (mode === 'dag') dagView.classList.remove('hidden');
        else dagView.classList.add('hidden');
      }
      lucide.createIcons();
      initSpotlightCards();
    }

    function openEmployeeDossier(index) {
      const staff = officeStaffRegistry[index];
      if (!staff) {
        if (officeStaffRegistry.length === 0) {
          setTimeout(() => openEmployeeDossier(index), 150);
        }
        return;
      }

      const avatarEl = document.getElementById('dossier-avatar');
      const roleEl = document.getElementById('dossier-role');
      const subEl = document.getElementById('dossier-sub');
      const bodyEl = document.getElementById('dossier-content');
      const modal = document.getElementById('employee-dossier-modal');

      if (roleEl) roleEl.textContent = staff.role || 'AI Employee';
      if (subEl) subEl.textContent = `Department: ${(staff.department || 'General').toUpperCase()} | Model: ${staff.model || 'inherit'} | Step: ${staff.steps_count || 1}`;

      if (avatarEl) {
        let avatarBg = 'bg-accent/20 text-accent border border-accent/40';
        if (staff.department === 'intelligence') avatarBg = 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40';
        else if (staff.department === 'engineering') avatarBg = 'bg-purple-500/20 text-purple-400 border border-purple-500/40';
        else if (staff.department === 'secops') avatarBg = 'bg-amber-500/20 text-amber-400 border border-amber-500/40';
        avatarEl.className = `w-9 h-9 rounded-lg flex items-center justify-center font-bold text-sm shrink-0 font-mono ${avatarBg}`;
        const initials = (staff.role || 'AI').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
        avatarEl.textContent = initials;
      }

      if (bodyEl) {
        let statusBadge = '';
        if (staff.desk_status === 'WORKING') {
          statusBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1.5 font-medium"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> IN DEEP FOCUS (WORKING)</span>`;
        } else if (staff.desk_status === 'IN_MEETING') {
          statusBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-amber-950/60 border border-amber-800 text-amber-400 font-medium">IN SYNC MEETING</span>`;
        } else if (staff.desk_status === 'BLOCKED') {
          statusBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-red-950/60 border border-red-800 text-red-400 font-bold">DESK OBSTACLE / BLOCKED</span>`;
        } else {
          statusBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-surface-2 border border-hairline text-gray-400 font-mono">ON STANDBY / FINISHED</span>`;
        }

        let toolBlock = '';
        if (staff.active_tool) {
          toolBlock = `
            <div class="space-y-1">
              <div class="text-[10px] font-mono uppercase tracking-wider text-gray-500">Active Desk Tool / Execution</div>
              <div class="bg-surface-2 border border-hairline rounded p-2.5 font-mono text-[11px] space-y-1">
                <div class="text-accent font-semibold flex items-center gap-1.5">
                  <span class="text-gray-500">[TOOL]</span>
                  <span>${escapeHtml(staff.active_tool.name)}</span>
                </div>
                ${staff.active_tool.action ? `<div class="text-gray-300">${escapeHtml(staff.active_tool.action)}</div>` : ''}
                ${staff.active_tool.summary ? `<div class="text-gray-400 text-[10px]">${escapeHtml(staff.active_tool.summary)}</div>` : ''}
              </div>
            </div>
          `;
        }

        bodyEl.innerHTML = `
          <div class="flex items-center justify-between pb-2 border-b border-hairline/60">
            <span class="text-[10px] font-mono uppercase tracking-wider text-gray-500">Live Desk Status</span>
            ${statusBadge}
          </div>

          <div class="grid grid-cols-3 gap-2 text-center font-mono text-[11px]">
            <div class="bg-surface-2/60 border border-hairline rounded p-2">
              <div class="text-[10px] text-gray-500 uppercase">Steps</div>
              <div class="text-white font-semibold text-xs">${staff.steps_count || 1}</div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-2">
              <div class="text-[10px] text-gray-500 uppercase">Tokens</div>
              <div class="text-accent font-semibold text-xs">${(staff.tokens_count || 0).toLocaleString()}</div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-2">
              <div class="text-[10px] text-gray-500 uppercase">Last Active</div>
              <div class="text-gray-300 font-semibold text-xs">${staff.last_active || 'Recent'}</div>
            </div>
          </div>

          <div class="space-y-1">
            <div class="text-[10px] font-mono uppercase tracking-wider text-gray-500">Assigned Mission / Directive</div>
            <div class="bg-surface-2 border border-hairline rounded p-2.5 font-mono text-[11px] text-gray-200 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto select-text">${escapeHtml(staff.full_prompt || staff.prompt || 'Direct Orchestration Loop')}</div>
          </div>

          ${toolBlock}

          <div class="pt-1 text-[10px] font-mono text-gray-500">
            <span>Identity CID: <code>${escapeHtml(staff.conversation_id || staff.id || 'root')}</code></span>
          </div>
        `;
      }

      if (modal) {
        modal.classList.remove('hidden');
        modal.onclick = (e) => {
          if (e.target === modal) closeEmployeeDossier();
        };
      }
      lucide.createIcons();
    }

    function closeEmployeeDossier() {
      const modal = document.getElementById('employee-dossier-modal');
      if (modal) modal.classList.add('hidden');
    }

    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeEmployeeDossier();
    });

    function renderSubagents(data) {
      if (!data || !data.active_session) return;
      const s = data.active_session;
      const kpis = data.office_kpis || {};
      currentSelectedCid = s.id;
      officeStaffRegistry = [];
      const deptKeys = ['executive', 'intelligence', 'engineering', 'secops'];
      const depts = data.departments || {};

      deptKeys.forEach(dKey => {
        const staffList = (depts[dKey] && depts[dKey].staff) ? depts[dKey].staff : [];
        staffList.forEach(st => {
          officeStaffRegistry.push(st);
          st._registryIdx = officeStaffRegistry.length - 1;
        });
      });

      // Render High-Density 2D Pixel Art Office Simulation (28 stations, 20+ active employees)
      renderPixelOffice(data);

      if (initialDossier !== null && !isNaN(parseInt(initialDossier)) && !window.__dossierOpenedOnce) {
        window.__dossierOpenedOnce = true;
        openEmployeeDossier(parseInt(initialDossier));
      }

      // Pulse dot in tab button
      const pulseDot = document.getElementById('subagents-pulse-dot');
      if (pulseDot) {
        if (s.status === 'RUNNING' || kpis.active_workers > 0) pulseDot.classList.remove('hidden');
        else pulseDot.classList.add('hidden');
      }

      // Render Session Pills
      const pillsContainer = document.getElementById('session-pills');
      if (pillsContainer) {
        pillsContainer.innerHTML = '';
        (data.sessions || []).forEach(sess => {
          const isSel = sess.id === s.id;
          const btn = document.createElement('button');
          btn.onclick = () => fetchSubagents(sess.id);
          btn.className = `px-2.5 py-1 rounded text-[11px] border transition-all shrink-0 flex items-center gap-1.5 ${
            isSel
              ? 'bg-accent/15 border-accent text-white font-medium'
              : 'bg-surface border-hairline text-gray-400 hover:text-white hover:border-gray-700'
          }`;
          btn.innerHTML = `<span>${sess.id.substring(0, 8)}...</span><span class="text-[10px] text-gray-500">${sess.last_active}</span>`;
          pillsContainer.appendChild(btn);
        });
      }

      // Render Headquarters Overview Bar
      const hqBar = document.getElementById('office-hq-bar');
      if (hqBar) {
        let opBadge = '';
        if (kpis.office_status === 'FULL OPERATION' || s.status === 'RUNNING') {
          opBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1.5 font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> FULL OPERATION</span>`;
        } else if (kpis.office_status === 'IN SYNC' || s.status === 'WAITING') {
          opBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-amber-950/60 border border-amber-800 text-amber-400 flex items-center gap-1.5 font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span> IN SYNC</span>`;
        } else if (s.status === 'STUCK') {
          opBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-red-950/60 border border-red-800 text-red-400 flex items-center gap-1.5 font-bold"><span class="w-1.5 h-1.5 rounded-full bg-red-400"></span> BLOCKED</span>`;
        } else {
          opBadge = `<span class="px-2.5 py-0.5 rounded text-[10px] bg-surface-2 border border-hairline text-gray-400 font-mono">STANDBY / READY</span>`;
        }

        const totalTokens = (kpis.total_tokens || s.estimated_tokens || 0).toLocaleString();
        const activeWorkers = kpis.active_workers || (s.status === 'RUNNING' ? 1 : 0);
        const totalHeadcount = kpis.total_headcount || (1 + (data.subagents || []).length);

        hqBar.innerHTML = `
          <div class="flex items-center justify-between gap-3">
            <div class="flex items-center gap-2 min-w-0">
              <span class="text-[10px] font-mono uppercase tracking-wider text-gray-500">Virtual HQ</span>
              <span class="text-[11px] font-mono text-gray-500 truncate">ID: ${s.id.substring(0, 13)}...</span>
            </div>
            <div>${opBadge}</div>
          </div>

          <div class="grid grid-cols-3 gap-2 pt-1 border-t border-hairline/60 text-center font-mono text-[11px]">
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5">
              <div class="text-[10px] text-gray-500 uppercase">Headcount</div>
              <div class="text-white font-semibold">${totalHeadcount} Staff <span class="text-emerald-400 font-normal text-[10px]">(${activeWorkers} act)</span></div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5">
              <div class="text-[10px] text-gray-500 uppercase">Token Burn</div>
              <div class="text-accent font-semibold">${totalTokens} <span class="text-gray-500 text-[10px]">(${kpis.token_burn_label || 'Normal'})</span></div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5">
              <div class="text-[10px] text-gray-500 uppercase">Primary Steps</div>
              <div class="text-gray-300 font-semibold">${s.total_steps} <span class="text-gray-500 text-[10px]">(${s.last_active})</span></div>
            </div>
          </div>

          <div class="flex items-center gap-2 pt-1.5 border-t border-hairline/60">
            <span class="text-[10px] font-mono text-gray-500 uppercase tracking-wider shrink-0">Mission:</span>
            <span class="text-xs font-semibold text-white truncate">${escapeHtml(s.prompt)}</span>
          </div>
        `;
      }

      // Render Departments Grid (Office Floor View)
      const deptGrid = document.getElementById('office-departments-grid');
      if (deptGrid) {
        deptGrid.innerHTML = '';
        const deptKeys = ['executive', 'intelligence', 'engineering', 'secops'];
        const depts = data.departments || {};

        deptKeys.forEach(dKey => {
          const dept = depts[dKey] || {
            name: dKey.toUpperCase(),
            room: 'Office Wing',
            badge: 'General',
            icon: 'building',
            color: '#2B7FFF',
            border: 'border-blue-500/30',
            bg_glow: 'bg-blue-500/10',
            text: 'text-blue-400',
            staff: []
          };

          const staffList = dept.staff || [];
          const deptCard = document.createElement('div');
          deptCard.className = `border ${dept.border || 'border-hairline'} rounded-xl bg-surface p-3.5 space-y-3 flex flex-col justify-between`;

          // Department Header
          let headerHtml = `
            <div class="flex items-center justify-between pb-2 border-b border-hairline/70">
              <div class="flex items-center gap-2">
                <div class="w-7 h-7 rounded-lg ${dept.bg_glow || 'bg-surface-2'} flex items-center justify-center ${dept.text || 'text-accent'} font-mono text-[10px] font-bold">
                  <span>${escapeHtml(dept.name.slice(0, 3))}</span>
                </div>
                <div>
                  <h4 class="text-xs font-semibold text-white leading-none">${escapeHtml(dept.name)}</h4>
                  <p class="text-[10px] font-mono text-gray-500 pt-0.5">${escapeHtml(dept.room)}</p>
                </div>
              </div>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-surface-2 border border-hairline text-gray-300">
                ${staffList.length} ${staffList.length === 1 ? 'Desk' : 'Desks'}
              </span>
            </div>
          `;

          // Staff Desks Container
          let desksHtml = '<div class="space-y-2 flex-1">';
          if (staffList.length > 0) {
            staffList.forEach(staff => {
              const staffIdx = staff._registryIdx !== undefined ? staff._registryIdx : 0;

              let deskBadge = '';
              if (staff.desk_status === 'WORKING') {
                deskBadge = `<span class="px-1.5 py-0.5 rounded text-[9.5px] bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1 font-medium shrink-0"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Focus</span>`;
              } else if (staff.desk_status === 'IN_MEETING') {
                deskBadge = `<span class="px-1.5 py-0.5 rounded text-[9.5px] bg-amber-950/60 border border-amber-800 text-amber-400 font-medium shrink-0">In Sync</span>`;
              } else if (staff.desk_status === 'BLOCKED') {
                deskBadge = `<span class="px-1.5 py-0.5 rounded text-[9.5px] bg-red-950/60 border border-red-800 text-red-400 font-bold shrink-0">Blocked</span>`;
              } else {
                deskBadge = `<span class="px-1.5 py-0.5 rounded text-[9.5px] bg-surface-2 border border-hairline text-gray-400 font-mono shrink-0">Standby</span>`;
              }

              let toolChip = '';
              if (staff.active_tool) {
                toolChip = `
                  <div class="flex items-center gap-1.5 bg-surface-2 border border-hairline/80 px-2 py-1 rounded font-mono text-[10px] text-gray-300 truncate">
                    <span class="text-accent font-semibold shrink-0">[${escapeHtml(staff.active_tool.name)}]</span>
                    <span class="truncate text-gray-400">${escapeHtml(staff.active_tool.summary || staff.active_tool.action || '')}</span>
                  </div>
                `;
              } else if (staff.prompt) {
                toolChip = `
                  <div class="text-[10.5px] text-gray-400 line-clamp-1 italic font-mono truncate px-1">
                    "${escapeHtml(staff.prompt)}"
                  </div>
                `;
              }

              desksHtml += `
                <div onclick="openEmployeeDossier(${staffIdx})" class="spotlight-card border border-hairline rounded-lg bg-surface-2/40 p-2.5 space-y-2 hover:border-gray-600 transition-all cursor-pointer">
                  <div class="flex items-center justify-between gap-2">
                    <div class="flex items-center gap-2 min-w-0">
                      <div class="w-6 h-6 rounded ${dept.bg_glow || 'bg-surface-3'} flex items-center justify-center ${dept.text || 'text-white'} text-[10px] font-mono font-bold shrink-0">
                        <span>${escapeHtml((staff.role || 'AI').slice(0, 2).toUpperCase())}</span>
                      </div>
                      <div class="min-w-0">
                        <div class="text-xs font-semibold text-white truncate">${escapeHtml(staff.role)}</div>
                        <div class="text-[9.5px] font-mono text-gray-500 truncate">${escapeHtml(staff.model || 'inherit')}</div>
                      </div>
                    </div>
                    ${deskBadge}
                  </div>

                  ${toolChip}

                  <div class="flex items-center justify-between text-[10px] font-mono text-gray-500 pt-1 border-t border-hairline/40">
                    <span>Steps: <b class="text-gray-300">${staff.steps_count || 1}</b></span>
                    <span class="text-accent hover:underline flex items-center gap-0.5">Dossier &rarr;</span>
                  </div>
                </div>
              `;
            });
          } else {
            desksHtml += `
              <div class="border border-dashed border-hairline/70 rounded-lg p-4 text-center text-gray-500 text-[11px] flex flex-col items-center justify-center gap-1 bg-surface-2/20 py-5">
                <span class="text-gray-400 font-medium">Department on Standby</span>
                <span class="text-[10px] text-gray-600">Specialists mobilize here when spawned</span>
              </div>
            `;
          }
          desksHtml += '</div>';

          deptCard.innerHTML = headerHtml + desksHtml;
          deptGrid.appendChild(deptCard);
        });
      }

      // Render Classic DAG Tree View
      const subCount = (data.subagents || []).length;
      const countEl = document.getElementById('dag-node-count');
      if (countEl) countEl.textContent = `${1 + subCount} Nodes`;
      const treeContainer = document.getElementById('dag-tree-content');
      if (treeContainer) {
        treeContainer.innerHTML = '';

        // Parent Node
        const parentNode = document.createElement('div');
        parentNode.className = 'spotlight-card border border-hairline rounded-md bg-surface-2 p-3 space-y-1.5';
        parentNode.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <div class="w-6 h-6 rounded bg-accent/20 border border-accent/40 flex items-center justify-center text-accent font-mono text-[9px] font-bold">
                <span>ROOT</span>
              </div>
              <div>
                <div class="text-xs font-semibold text-white">Parent Orchestrator Agent</div>
                <div class="text-[10px] font-mono text-gray-500">Model: Active | Primary Loop</div>
              </div>
            </div>
            <span class="text-[10px] font-mono text-gray-400 bg-surface px-2 py-0.5 rounded border border-hairline">Step ${s.total_steps}</span>
          </div>
        `;
        treeContainer.appendChild(parentNode);

        // Subagent Nodes
        if (subCount > 0) {
          data.subagents.forEach((sa, idx) => {
            const isSaRunning = sa.status === 'RUNNING' || sa.desk_status === 'WORKING';
            const branch = document.createElement('div');
            branch.className = 'ml-5 pl-4 border-l-2 border-hairline-strong relative space-y-2';
            branch.innerHTML = `
              <div class="spotlight-card border border-hairline rounded-md bg-surface p-3 space-y-2 hover:border-gray-700 transition-colors">
                <div class="flex items-center justify-between">
                  <div class="flex items-center gap-2">
                    <div class="w-6 h-6 rounded bg-purple-500/20 border border-purple-500/40 flex items-center justify-center text-purple-400 font-mono text-[9px] font-bold">
                      <span>SUB</span>
                    </div>
                    <div>
                      <div class="text-xs font-semibold text-white">${escapeHtml(sa.role || 'Subagent')}</div>
                      <div class="text-[10px] font-mono text-gray-500">Dept: ${escapeHtml((sa.department || 'engineering').toUpperCase())} | Model: ${escapeHtml(sa.model || 'inherit')}</div>
                    </div>
                  </div>
                  <span class="px-2 py-0.5 rounded text-[10px] font-mono ${
                    isSaRunning
                      ? 'bg-emerald-950/60 border border-emerald-800 text-emerald-400 font-medium'
                      : 'bg-surface-2 border border-hairline text-gray-400'
                  }">${sa.desk_status || sa.status}</span>
                </div>
                <div class="bg-surface-2/60 border border-hairline/60 rounded p-2 text-[11px] text-gray-300 font-mono leading-relaxed truncate">
                  "${escapeHtml(sa.prompt)}"
                </div>
              </div>
            `;
            treeContainer.appendChild(branch);
          });
        } else {
          const emptyNotice = document.createElement('div');
          emptyNotice.className = 'ml-5 pl-4 border-l-2 border-hairline-strong py-2';
          emptyNotice.innerHTML = `
            <div class="border border-dashed border-hairline rounded p-3 text-center text-gray-500 text-xs">
              Direct single-agent orchestration active. Subagents will branch here automatically when <code>invoke_subagent</code> is executed.
            </div>
          `;
          treeContainer.appendChild(emptyNotice);
        }
      }

      setOfficeView(currentOfficeViewMode);
      lucide.createIcons();
      initSpotlightCards();
    }

    async function fetchMcp() {
      try {
        const res = await fetch('/api/mcp');
        const list = await res.json();
        renderMcp(list);
      } catch (e) {
        console.error("Error fetching MCP matrix:", e);
      }
    }

    function renderMcp(list) {
      if (!Array.isArray(list)) return;
      const countBadge = document.getElementById('mcp-count-badge');
      if (countBadge) countBadge.textContent = list.length;
      const container = document.getElementById('mcp-cards-container');
      if (!container) return;
      container.innerHTML = '';

      list.forEach(item => {
        const isOnline = item.status === 'ONLINE';
        const card = document.createElement('div');
        card.className = 'spotlight-card border border-hairline rounded-lg bg-surface p-4 space-y-3';
        
        let statusBadge = isOnline
          ? `<span class="px-2 py-0.5 rounded text-[10px] bg-emerald-950/60 border border-emerald-800 text-emerald-400 flex items-center gap-1 font-semibold"><span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> ONLINE</span>`
          : `<span class="px-2 py-0.5 rounded text-[10px] bg-surface-2 border border-hairline text-gray-400 font-mono">STANDBY</span>`;

        card.innerHTML = `
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2.5">
              <div class="w-7 h-7 rounded bg-surface-2 border border-hairline flex items-center justify-center text-accent">
                <i data-lucide="plug" class="w-4 h-4"></i>
              </div>
              <div>
                <h4 class="text-xs font-semibold text-white font-mono">${item.name}</h4>
                <div class="text-[10px] font-mono text-gray-500 truncate max-w-xs">${item.preview_cmd}</div>
              </div>
            </div>
            <div>${statusBadge}</div>
          </div>

          <div class="grid grid-cols-3 gap-2 border-t border-hairline/60 pt-2 font-mono text-[11px]">
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5 text-center">
              <div class="text-[10px] text-gray-500 uppercase">PID</div>
              <div class="text-gray-300">${item.pid || '-'}</div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5 text-center">
              <div class="text-[10px] text-gray-500 uppercase">RAM</div>
              <div class="${item.memory_mb > 0 ? 'text-emerald-400 font-semibold' : 'text-gray-400'}">${item.memory_mb > 0 ? item.memory_mb + ' MB' : '-'}</div>
            </div>
            <div class="bg-surface-2/60 border border-hairline rounded p-1.5 text-center">
              <div class="text-[10px] text-gray-500 uppercase">Uptime</div>
              <div class="text-gray-300">${item.uptime}</div>
            </div>
          </div>

          <div class="flex items-center justify-between pt-1">
            <div id="mcp-ping-result-${item.name}" class="text-[11px] font-mono text-gray-400">
              Stdio JSON-RPC Ready
            </div>
            <div class="flex items-center gap-2">
              <button onclick="pingMcp('${item.name}')" id="btn-ping-${item.name}" class="btn-spring h-6 px-2.5 rounded bg-surface-2 hover:bg-surface-3 border border-hairline text-gray-300 hover:text-white text-[11px] flex items-center gap-1 transition-all">
                <i data-lucide="zap" class="w-3 h-3 text-amber-400"></i>
                <span>Ping Probe</span>
              </button>
              <button onclick="restartMcp('${item.name}')" class="btn-spring h-6 px-2.5 rounded bg-surface-2 hover:bg-surface-3 border border-hairline text-gray-300 hover:text-white text-[11px] flex items-center gap-1 transition-all">
                <i data-lucide="rotate-ccw" class="w-3 h-3 text-gray-400"></i>
                <span>Restart</span>
              </button>
            </div>
          </div>
        `;
        container.appendChild(card);
      });

      lucide.createIcons();
      initSpotlightCards();
    }

    async function pingMcp(name) {
      const resLabel = document.getElementById(`mcp-ping-result-${name}`);
      if (resLabel) resLabel.innerHTML = `<span class="text-amber-400 animate-pulse">Probing JSON-RPC...</span>`;
      try {
        const res = await fetch('/api/mcp/ping', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ name })
        });
        const data = await res.json();
        if (data.success) {
          if (resLabel) resLabel.innerHTML = `<span class="text-emerald-400 font-semibold">${data.latency_ms}ms (Responsive)</span>`;
        } else {
          if (resLabel) resLabel.innerHTML = `<span class="text-red-400 font-semibold truncate max-w-xs" title="${data.error || 'Timeout'}">Probe failed</span>`;
        }
      } catch (e) {
        if (resLabel) resLabel.innerHTML = `<span class="text-red-400">Network error</span>`;
      }
    }

    async function restartMcp(name) {
      if (confirm(`Terminate and reset MCP server [${name}] to clean standby?`)) {
        try {
          await fetch('/api/mcp/restart', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name })
          });
          setTimeout(fetchMcp, 500);
        } catch (e) {
          console.error(e);
        }
      }
    }

    async function fetchStatus(forceSpinner = false) {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        state = data;
        renderUI();
      } catch (e) {
        console.error("Status fetch error", e);
      }
    }

    function renderUI() {
      scheduleLoaderDismissal();
      // Header & Status with DecryptedText effect
      const emailEl = document.getElementById('current-active-email');
      if (emailEl) {
        if (state.active) {
          emailEl.title = state.active;
          decryptScramble(emailEl, state.active);
        } else {
          emailEl.title = 'No active account';
          emailEl.textContent = 'None';
        }
      }
      document.getElementById('total-accounts-count').textContent = `${state.accounts.length} accounts`;

      // Auto-Pilot Button
      const apDot = document.getElementById('ap-dot');
      const apText = document.getElementById('ap-text');
      const apBtn = document.getElementById('btn-toggle-ap');

      if (state.autopilot) {
        apDot.className = "w-1.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(16,185,129,0.8)] shrink-0";
        apText.textContent = "Auto-Pilot: Active";
        apBtn.className = "btn-spring h-7 px-2.5 rounded-md border text-xs font-medium flex items-center gap-1.5 transition-all bg-emerald-950/40 border-emerald-900 text-emerald-400 whitespace-nowrap shrink-0 cursor-pointer";
      } else {
        apDot.className = "w-1.5 h-1.5 rounded-full bg-gray-500 shrink-0";
        apText.textContent = "Auto-Pilot: Inactive";
        apBtn.className = "btn-spring h-7 px-2.5 rounded-md border text-xs font-medium flex items-center gap-1.5 transition-all bg-surface-3 border-hairline text-gray-400 hover:text-white whitespace-nowrap shrink-0 cursor-pointer";
      }

      // Quick Rec Box
      const quickRecBox = document.getElementById('quick-rec-box');
      if (state.best && state.best !== state.active) {
        quickRecBox.classList.remove('hidden');
      } else {
        quickRecBox.classList.add('hidden');
      }

      // Cards
      const container = document.getElementById('cards-container');
      container.innerHTML = '';

      state.accounts.forEach(acc => {
        const isActive = (acc === state.active);
        const isBest = (acc === state.best);
        const q = state.quotas[acc] || {};
        container.appendChild(createAccountCard(acc, isActive, isBest, q));
      });

      // Animate Quota Counts with CountUp
      document.querySelectorAll('.quota-pct-label').forEach(el => {
        const val = parseFloat(el.dataset.pctVal || '0');
        animateCountUp(el, val);
      });

      // Logs Table
      renderLogs();
      lucide.createIcons();
      initSpotlightCards();
    }

    function getBarColor(pct) {
      if (pct >= 70) return 'bg-emerald-500';
      if (pct >= 20) return 'bg-amber-500';
      return 'bg-red-500';
    }

    function getTextPercentColor(pct) {
      if (pct >= 70) return 'text-gray-200';
      if (pct >= 20) return 'text-amber-400';
      return 'text-red-400';
    }

    function createAccountCard(acc, isActive, isBest, q) {
      const card = document.createElement('div');
      card.className = `spotlight-card border rounded-lg p-4 transition-all duration-150 ${
        isActive 
          ? 'bg-surface border-emerald-900/70 border-glow-active' 
          : 'bg-surface border-hairline hover:border-hairline-strong'
      }`;

      // Extract quotas
      const gemini = q.gemini || {};
      const claude = q.claude || {};

      const g5 = gemini['5h'] ? (gemini['5h'].remaining || 0) : 100;
      const g5_rt = gemini['5h'] ? (gemini['5h'].resetDelta || '') : '';
      const gw = gemini['weekly'] ? (gemini['weekly'].remaining || 0) : 100;
      const gw_rt = gemini['weekly'] ? (gemini['weekly'].resetDelta || '') : '';

      const c5 = claude['5h'] ? (claude['5h'].remaining || 0) : 100;
      const c5_rt = claude['5h'] ? (claude['5h'].resetDelta || '') : '';
      const cw = claude['weekly'] ? (claude['weekly'].remaining || 0) : 100;
      const cw_rt = claude['weekly'] ? (claude['weekly'].resetDelta || '') : '';

      let badgesHtml = '';
      if (isActive) {
        badgesHtml += `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950/80 border border-emerald-900 text-emerald-400">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Active
        </span>`;
      }
      if (isBest) {
        badgesHtml += `<span class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-indigo-950/60 border border-indigo-900 text-indigo-300">
          Recommended
        </span>`;
      }

      let buttonHtml = '';
      if (isActive) {
        buttonHtml = `<button disabled class="h-7 px-3 rounded-md text-xs font-medium bg-surface-3 text-[#6E6E6E] border border-hairline cursor-default">In Use</button>`;
      } else {
        buttonHtml = `<button onclick="switchAccount('${acc}')" class="btn-spring h-7 px-3 rounded-md text-xs font-medium bg-surface-3 hover:bg-surface-hover text-[#CCCCCC] hover:text-white border border-hairline hover:border-hairline-strong transition-all flex items-center gap-1.5 cursor-pointer">
          <span>Switch</span>
          <i data-lucide="arrow-right" class="w-3 h-3 text-[#9D9D9D]"></i>
        </button>`;
      }

      card.innerHTML = `
        <div class="flex items-center justify-between pb-3 border-b border-hairline/60">
          <div class="flex items-center gap-2">
            <span class="font-semibold text-sm text-[#E2E8F0] tracking-tight">${acc}</span>
            ${badgesHtml}
          </div>
          <div class="flex items-center gap-1.5">
            ${buttonHtml}
            <button onclick="deleteAccount('${acc}')" title="Remove account" class="btn-spring h-7 w-7 rounded-md border border-hairline bg-surface-3 text-[#9D9D9D] hover:text-red-400 hover:border-red-500/40 hover:bg-red-500/10 flex items-center justify-center transition-all cursor-pointer">
              <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
            </button>
          </div>
        </div>

        <!-- Strict 2-Column Metrics Grid -->
        <div class="grid grid-cols-2 gap-4 pt-3 text-xs">
          <!-- Gemini Models -->
          <div class="space-y-2">
            <div class="text-[10px] font-mono font-semibold uppercase tracking-wider text-gray-500 flex items-center justify-between">
              <span>Gemini Models</span>
            </div>

            <!-- 5h -->
            <div class="space-y-1">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-gray-400">5-Hour Limit</span>
                <div class="flex items-center gap-1.5 font-mono">
                  <span class="quota-pct-label ${getTextPercentColor(g5)} font-medium" data-pct-val="${g5}">${g5.toFixed(0)}%</span>
                  ${g5 < 100 && g5_rt ? `<span class="text-[10px] text-gray-500">${g5_rt}</span>` : ''}
                </div>
              </div>
              <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
                <div class="h-full ${getBarColor(g5)} rounded-full" style="width: ${Math.max(2, g5)}%"></div>
              </div>
            </div>

            <!-- Weekly -->
            <div class="space-y-1 pt-0.5">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-gray-400">Weekly Limit</span>
                <div class="flex items-center gap-1.5 font-mono">
                  <span class="quota-pct-label ${getTextPercentColor(gw)} font-medium" data-pct-val="${gw}">${gw.toFixed(0)}%</span>
                  ${gw < 100 && gw_rt ? `<span class="text-[10px] text-gray-500">${gw_rt}</span>` : ''}
                </div>
              </div>
              <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
                <div class="h-full ${getBarColor(gw)} rounded-full" style="width: ${Math.max(2, gw)}%"></div>
              </div>
            </div>
          </div>

          <!-- Claude & GPT Models -->
          <div class="space-y-2 pl-4 border-l border-hairline/60">
            <div class="text-[10px] font-mono font-semibold uppercase tracking-wider text-gray-500 flex items-center justify-between">
              <span>Claude & GPT</span>
            </div>

            <!-- 5h -->
            <div class="space-y-1">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-gray-400">5-Hour Limit</span>
                <div class="flex items-center gap-1.5 font-mono">
                  <span class="quota-pct-label ${getTextPercentColor(c5)} font-medium" data-pct-val="${c5}">${c5.toFixed(0)}%</span>
                  ${c5 < 100 && c5_rt ? `<span class="text-[10px] text-gray-500">${c5_rt}</span>` : ''}
                </div>
              </div>
              <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
                <div class="h-full ${getBarColor(c5)} rounded-full" style="width: ${Math.max(2, c5)}%"></div>
              </div>
            </div>

            <!-- Weekly -->
            <div class="space-y-1 pt-0.5">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-gray-400">Weekly Limit</span>
                <div class="flex items-center gap-1.5 font-mono">
                  <span class="quota-pct-label ${getTextPercentColor(cw)} font-medium" data-pct-val="${cw}">${cw.toFixed(0)}%</span>
                  ${cw < 100 && cw_rt ? `<span class="text-[10px] text-gray-500">${cw_rt}</span>` : ''}
                </div>
              </div>
              <div class="h-1.5 w-full bg-surface-3 rounded-full overflow-hidden">
                <div class="h-full ${getBarColor(cw)} rounded-full" style="width: ${Math.max(2, cw)}%"></div>
              </div>
            </div>
          </div>
        </div>
      `;
      return card;
    }

    function renderLogs() {
      const tbody = document.getElementById('logs-table-body');
      tbody.innerHTML = '';
      if (!state.logs || state.logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="py-4 text-center text-gray-500">No events recorded.</td></tr>';
        return;
      }

      state.logs.forEach(log => {
        let typeBadge = `<span class="text-gray-500">INFO</span>`;
        if (log.type === 'LIMIT') typeBadge = `<span class="text-red-400 font-semibold">LIMIT</span>`;
        else if (log.type === 'SWITCH') typeBadge = `<span class="text-blue-400 font-semibold">SWITCH</span>`;
        else if (log.type === 'RESUMED') typeBadge = `<span class="text-emerald-400 font-semibold">RESUMED</span>`;
        else if (log.type === 'EVAL') typeBadge = `<span class="text-indigo-400 font-semibold">EVAL</span>`;

        const tr = document.createElement('tr');
        tr.className = 'hover:bg-surface-2 transition-colors';
        tr.innerHTML = `
          <td class="py-2 px-3 text-gray-500">${log.time}</td>
          <td class="py-2 px-2">${typeBadge}</td>
          <td class="py-2 px-3 text-gray-300 truncate max-w-xs">${log.desc}</td>
        `;
        tbody.appendChild(tr);
      });
    }

    async function switchAccount(email) {
      try {
        await fetch('/api/switch', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ email })
        });
        setTimeout(fetchStatus, 800);
      } catch (e) {
        console.error(e);
      }
    }

    async function switchRecommended() {
      if (state.best) {
        await switchAccount(state.best);
      }
    }

    async function toggleAutoPilot() {
      const targetState = !state.autopilot;
      const apDot = document.getElementById('ap-dot');
      const apText = document.getElementById('ap-text');
      const apBtn = document.getElementById('btn-toggle-ap');

      if (targetState) {
        if (apDot) apDot.className = "w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0";
        if (apText) apText.textContent = "Auto-Pilot: Starting...";
        if (apBtn) apBtn.className = "btn-spring h-7 px-2.5 rounded-md border text-xs font-medium flex items-center gap-1.5 transition-all bg-emerald-950/40 border-emerald-900 text-emerald-400 whitespace-nowrap shrink-0";
      } else {
        if (apDot) apDot.className = "w-1.5 h-1.5 rounded-full bg-gray-500 animate-pulse shrink-0";
        if (apText) apText.textContent = "Auto-Pilot: Stopping...";
        if (apBtn) apBtn.className = "btn-spring h-7 px-2.5 rounded-md border text-xs font-medium flex items-center gap-1.5 transition-all bg-surface-3 border-hairline text-gray-400 whitespace-nowrap shrink-0";
      }

      try {
        const res = await fetch('/api/toggle-autopilot', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ enable: targetState })
        });
        const data = await res.json();
        if (data && typeof data.autopilot !== 'undefined') {
          state.autopilot = data.autopilot;
        } else {
          state.autopilot = targetState;
        }
        renderUI();
        setTimeout(() => fetchStatus(true), 400);
      } catch (e) {
        console.error("AutoPilot toggle error:", e);
        fetchStatus(true);
      }
    }

    async function deleteAccount(email) {
      if (confirm(`Remove account [${email}] from the switcher?`)) {
        await fetch('/api/delete', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ email })
        });
        setTimeout(fetchStatus, 500);
      }
    }

    async function enrollAccount() {
      if (confirm("Antigravity will restart with an empty session so you can log in. Proceed?")) {
        await fetch('/api/enroll', { method: 'POST' });
        setTimeout(fetchStatus, 1500);
      }
    }

    async function clearLogs() {
      if (confirm("Clear all overnight event logs?")) {
        await fetch('/api/clear-logs', { method: 'POST' });
        setTimeout(fetchStatus, 300);
      }
    }

    // Top Bar & Menu Handlers (Antigravity 2.0 1:1)
    let isMenuOpen = false;
    let activeMenu = null;

    function toggleMenu(name) {
      if (activeMenu === name) {
        closeAllMenus();
      } else {
        openMenu(name);
      }
    }

    function hoverMenu(name) {
      if (isMenuOpen && activeMenu !== name) {
        openMenu(name);
      }
    }

    function openMenu(name) {
      closeAllMenus();
      const dropdown = document.getElementById(`menu-dropdown-${name}`);
      const btn = document.getElementById(`menu-btn-${name}`);
      if (dropdown && btn) {
        dropdown.classList.remove('hidden');
        btn.classList.add('active');
        activeMenu = name;
        isMenuOpen = true;
      }
    }

    function closeAllMenus() {
      ['file', 'view', 'window'].forEach(m => {
        const dropdown = document.getElementById(`menu-dropdown-${m}`);
        const btn = document.getElementById(`menu-btn-${m}`);
        if (dropdown) dropdown.classList.add('hidden');
        if (btn) btn.classList.remove('active');
      });
      activeMenu = null;
      isMenuOpen = false;
    }

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#menu-btn-file') && 
          !e.target.closest('#menu-btn-view') && 
          !e.target.closest('#menu-btn-window') && 
          !e.target.closest('.dropdown-menu')) {
        closeAllMenus();
      }
    });

    window.addEventListener('keydown', (e) => {
      if (e.key === 'F5') {
        e.preventDefault();
        syncCreds();
      } else if (e.key === 'Escape') {
        if (isMenuOpen) {
          closeAllMenus();
        }
      }
    });

    function selectTabAndClose(tabName) {
      setTab(tabName);
      closeAllMenus();
    }

    function syncCreds() {
      fetchStatus(true);
      closeAllMenus();
    }

    function windowMinimize() {
      fetch('/api/window/minimize', { method: 'POST' }).catch(() => {});
    }

    function windowMaximize() {
      fetch('/api/window/maximize', { method: 'POST' }).catch(() => {});
    }

    function windowClose() {
      fetch('/api/window/close', { method: 'POST' }).catch(() => {});
    }

    function windowQuit() {
      fetch('/api/window/quit', { method: 'POST' }).catch(() => {});
    }

    function setMaximizedState(isMax) {
      const svgMax = document.getElementById('svg-win-max');
      const svgRestore = document.getElementById('svg-win-restore');
      if (svgMax && svgRestore) {
        if (isMax) {
          svgMax.classList.add('hidden');
          svgRestore.classList.remove('hidden');
          svgRestore.classList.remove('icon-spin-enter');
          void svgRestore.offsetWidth;
          svgRestore.classList.add('icon-spin-enter');
        } else {
          svgMax.classList.remove('hidden');
          svgRestore.classList.add('hidden');
          svgMax.classList.remove('icon-spin-enter');
          void svgMax.offsetWidth;
          svgMax.classList.add('icon-spin-enter');
        }
      }
    }

    if (state.accounts && state.accounts.length > 0) {
      renderUI();
    }
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab');
    const initialCid = urlParams.get('cid');
    const initialView = urlParams.get('view');
    if (initialCid) {
      currentSelectedCid = initialCid;
    }
    if (initialView && ['pixel', 'office', 'dag'].includes(initialView)) {
      currentOfficeViewMode = initialView;
    }
    initialDossier = urlParams.get('dossier');
    if (initialTab && ['accounts', 'subagents', 'mcp', 'logs', 'manage'].includes(initialTab)) {
      setTab(initialTab);
    }
    if (initialDossier !== null && !isNaN(parseInt(initialDossier))) {
      setTimeout(() => openEmployeeDossier(parseInt(initialDossier)), 300);
    }
    // Auto-poll status every 15 seconds
    setInterval(fetchStatus, 15000);
    fetchStatus();
  </script>
</body>
</html>
"""

def inject_prompt_via_cdp(prompt_text: str):
    """
    Menginjeksi teks prompt langsung ke antarmuka chat Antigravity IDE
    menggunakan Chrome DevTools Protocol (CDP) port lokal.
    """
    devtools_file = os.path.join(os.environ.get("APPDATA", ""), "Antigravity", "DevToolsActivePort")
    if not os.path.exists(devtools_file):
        return False, "DevToolsActivePort Antigravity tidak ditemukan."
    try:
        lines = open(devtools_file, "r", encoding="utf-8").read().splitlines()
        if not lines or not lines[0].isdigit():
            return False, "DevToolsActivePort tidak valid."
        port = int(lines[0])
        targets_url = f"http://127.0.0.1:{port}/json"
        req = urllib.request.Request(targets_url, headers={"User-Agent": "AntigravityControlCenter"})
        with urllib.request.urlopen(req, timeout=4) as response:
            targets = json.loads(response.read().decode("utf-8"))
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page or "webSocketDebuggerUrl" not in page:
            return False, "Halaman chat Antigravity tidak ditemukan di CDP."

        ws_url = page["webSocketDebuggerUrl"]
        path = ws_url.split(f":{port}")[1]

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(("127.0.0.1", port))
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        s.sendall(handshake.encode())
        s.recv(1024)

        escaped_prompt = json.dumps(prompt_text)
        js = f"""
        (() => {{
            const input = document.querySelector('textarea, [contenteditable="true"]');
            if (!input) return 'NO_INPUT_FOUND';
            if (input.tagName === 'TEXTAREA') {{
                input.value = {escaped_prompt};
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }} else {{
                input.innerText = {escaped_prompt};
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
            const allButtons = Array.from(document.querySelectorAll('button'));
            const sendBtn = allButtons.find(b => {{
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                const txt = (b.innerText || '').toLowerCase();
                return aria.includes('send') || aria.includes('kirim') || aria.includes('submit') || txt.includes('send') || txt.includes('kirim');
            }});
            if (sendBtn) {{
                sendBtn.click();
                return 'CLICKED_SEND';
            }} else {{
                input.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                return 'DISPATCHED_ENTER';
            }}
        }})()
        """
        msg = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js}}).encode()
        frame = bytearray([0x81, 0x80 | 126, (len(msg) >> 8) & 0xff, len(msg) & 0xff, 0, 0, 0, 0]) + msg
        s.sendall(frame)
        res_raw = s.recv(4096)
        s.close()
        return True, "Prompt berhasil di-inject ke Antigravity IDE via CDP."
    except Exception as e:
        return False, f"CDP error: {str(e)}"

def generate_office_deliberation_llm(prompt_text, participants_data=None, mission_text=""):
    """
    Directly invokes Google Cloud Code / Gemini 3.7 Flash API (gemini-3.7-flash-medium)
    via the active Antigravity OAuth Bearer token to generate dynamic, authentic,
    multi-agent deliberative debate turns with internal thoughts and spoken dialogue.
    """
    if not participants_data or len(participants_data) < 4:
        participants_data = [
            {"id": "eng_2", "role": "Backend Architect", "dept": "engineering"},
            {"id": "lab_1", "role": "AI Research Lead", "dept": "intelligence"},
            {"id": "sec_7", "role": "QA Sentinel Lead", "dept": "secops"},
            {"id": "lib_1", "role": "Knowledge Archivist", "dept": "intelligence"}
        ]

    p0 = participants_data[0]
    p1 = participants_data[1]
    p2 = participants_data[2]
    p3 = participants_data[3]

    token = None
    try:
        active_email = "default_account"
        if os.path.exists(ACTIVE_FILE):
            active_email = open(ACTIVE_FILE, "r", encoding="utf-8").read().strip()
        
        cred_path = os.path.join(ACCOUNTS_DIR, active_email, "cred.bin")
        if os.path.exists(cred_path):
            cred_data = json.loads(open(cred_path, "rb").read().decode("utf-8"))
            rf = cred_data.get("token", {}).get("refresh_token")
            if rf:
                token = refresh_access_token(rf)
    except Exception as e:
        print("[LLM Deliberation] Failed to read active token:", e)

    # Fallback token lookup across saved accounts
    if not token and os.path.exists(ACCOUNTS_DIR):
        for acc in os.listdir(ACCOUNTS_DIR):
            c_path = os.path.join(ACCOUNTS_DIR, acc, "cred.bin")
            if os.path.exists(c_path):
                try:
                    c_data = json.loads(open(c_path, "rb").read().decode("utf-8"))
                    rf = c_data.get("token", {}).get("refresh_token")
                    if rf:
                        token = refresh_access_token(rf)
                        if token:
                            break
                except Exception:
                    pass

    effective_prompt = (prompt_text or mission_text or "Sprint Architecture & System Optimization").strip()

    if token:
        try:
            system_instruction = f"""
You are the AI Deliberation Engine for the Antigravity Autonomous Agent Office War Room.
The Commander has issued the following directive or convened a strategy meeting:
"{effective_prompt}"

Generate an intense, authentic, deliberative technical debate among 4 agent delegates and the Lead Orchestrator.
Tone & Behavioral Standards:
- Dense, direct, pragmatic Bahasa Indonesia informal mixed with English technical terms (Mode C Hybrid: Critical Sparring Partner).
- Challenge assumptions, isolate bottlenecks, evaluate trade-offs (70% battle-tested reliability + 30% bleeding edge).
- Zero placeholders: enforce strict Definition of Done (DoD), automated test coverage, regression defense, and clean error handling.
- DemusBrain Ground Truth: align with SSOT, zero silent assumptions.
- Keep statements punchy and concise so they fit neatly on pixel speech bubbles.

Session Participants:
- Lead: exec_1 (Lead Orchestrator, executive)
- Specialist: {p0.get('id', 'eng_2')} ({p0.get('role', 'Specialist')}, {p0.get('dept', 'engineering')})
- Sparring Partner: {p1.get('id', 'lab_1')} ({p1.get('role', 'Sparring Partner')}, {p1.get('dept', 'intelligence')})
- QA Sentinel: {p2.get('id', 'sec_7')} ({p2.get('role', 'QA Sentinel')}, {p2.get('dept', 'secops')})
- Vault Archivist: {p3.get('id', 'lib_1')} ({p3.get('role', 'Knowledge Archivist')}, {p3.get('dept', 'intelligence')})

Debate Flow:
Turn 1 (exec_1): Frame problem, mission objectives, and architectural constraints.
Turn 2 ({p0.get('id')}): Technical proposal, implementation plan, and immediate actions.
Turn 3 ({p1.get('id')}): Mode C critical sparring - challenge edge cases, latency risks, and race conditions.
Turn 4 ({p2.get('id')}): QA sentinel - enforce strict DoD, unit/regression tests, zero-placeholder verification.
Turn 5 ({p3.get('id')}): Vault alignment - DemusBrain SSOT verification, schema provenance, and compounding.
Turn 6 (exec_1): Final consensus, task delegation, and execution order.
Chorus: Simultaneous 1-word execution confirmation from each delegate.

Return ONLY a valid JSON array of exactly 7 items (6 individual turns + 1 chorus item).
JSON Schema:
[
  {{
    "speakerId": "exec_1",
    "speakerRole": "Lead Orchestrator",
    "dept": "executive",
    "thought": "Internal chain of thought (max 90 chars)",
    "speech": "Spoken dialogue to team (max 110 chars)"
  }},
  ...
  {{
    "isChorus": true,
    "speakerRole": "All Delegates",
    "thought": "Konsensus tercapai lintas seluruh divisi.",
    "speech": "Konsensus tercapai. Disperse dan eksekusi!",
    "chorusItems": [
      {{"speakerId": "{p0.get('id')}", "text": "ActionWord!", "dept": "{p0.get('dept')}"}},
      {{"speakerId": "{p1.get('id')}", "text": "ActionWord!", "dept": "{p1.get('dept')}"}},
      {{"speakerId": "{p2.get('id')}", "text": "ActionWord!", "dept": "{p2.get('dept')}"}},
      {{"speakerId": "{p3.get('id')}", "text": "ActionWord!", "dept": "{p3.get('dept')}"}}
    ]
  }}
]
"""
            url = 'https://daily-cloudcode-pa.googleapis.com/v1internal:generateContent'
            body = {
                'project': 'aicode-consumers',
                'model': 'gemini-3.7-flash-medium',
                'request': {
                    'contents': [
                        {'role': 'user', 'parts': [{'text': system_instruction}]}
                    ],
                    'generationConfig': {
                        'temperature': 0.7,
                        'maxOutputTokens': 4096,
                        'responseMimeType': 'application/json',
                        'thinkingConfig': {
                            'thinkingBudget': 512
                        }
                    }
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode('utf-8'),
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                    'User-Agent': 'antigravity/2.12.2'
                }
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode('utf-8'))
                parts = res.get('response', {}).get('candidates', [{}])[0].get('content', {}).get('parts', [])
                raw_text = ''
                for part in parts:
                    if 'text' in part:
                        raw_text += part['text']

                clean_json = re.sub(r'^```(?:json)?\s*', '', raw_text.strip())
                clean_json = re.sub(r'\s*```$', '', clean_json)

                parsed = json.loads(clean_json)
                if isinstance(parsed, list) and len(parsed) >= 6:
                    timings = [
                        (10, 110),
                        (125, 110),
                        (240, 110),
                        (355, 110),
                        (470, 110),
                        (585, 110),
                        (700, 85)
                    ]
                    for idx, item in enumerate(parsed):
                        if idx < len(timings):
                            item['startFrame'] = timings[idx][0]
                            item['duration'] = timings[idx][1]
                        if 'speech' in item and 'text' not in item:
                            item['text'] = item['speech']
                    return parsed
        except Exception as e:
            print('[LLM Deliberation] Cloud Code generation error:', e)

    # Resilient fallback so meetings never stall
    subj = effective_prompt[:35] if len(effective_prompt) > 35 else effective_prompt
    return [
        {"speakerId": "exec_1", "speakerRole": "Lead Orchestrator", "dept": "executive", "thought": f"Analisa arahan: petakan failure point dan sprint roadmap untuk '{subj}'.", "speech": f"Agenda rapat dibuka: fokus ke '{subj}'. Divisi terkait, paparkan analisa teknis sekarang!", "startFrame": 10, "duration": 110, "text": f"Agenda rapat dibuka: fokus ke '{subj}'. Divisi terkait, paparkan analisa teknis sekarang!"},
        {"speakerId": p0.get("id", "eng_2"), "speakerRole": p0.get("role", "Specialist"), "dept": p0.get("dept", "engineering"), "thought": f"Menyiapkan rancangan implementasi dan typed architecture untuk '{subj}'.", "speech": f"Dari divisi {p0.get('dept')}, rancangan core '{subj}' sudah siap. Kita implementasikan modular components.", "startFrame": 125, "duration": 110, "text": f"Dari divisi {p0.get('dept')}, rancangan core '{subj}' sudah siap. Kita implementasikan modular components."},
        {"speakerId": p1.get("id", "lab_1"), "speakerRole": p1.get("role", "Sparring Partner"), "dept": p1.get("dept", "intelligence"), "thought": f"Mode C Sparring: challenge edge cases dan latency bottleneck di '{subj}'.", "speech": f"Tunggu dulu, pastikan edge cases dan throughput spike di '{subj}' sudah dimitigasi sebelum merge!", "startFrame": 240, "duration": 110, "text": f"Tunggu dulu, pastikan edge cases dan throughput spike di '{subj}' sudah dimitigasi sebelum merge!"},
        {"speakerId": p2.get("id", "sec_7"), "speakerRole": p2.get("role", "QA Sentinel"), "dept": p2.get("dept", "secops"), "thought": f"Enforce Definition of Done: unit tests, regression tests, zero placeholders di '{subj}'.", "speech": f"SecOps & QA siap kawal. Kriteria DoD tetap harga mati untuk deliverables '{subj}'!", "startFrame": 355, "duration": 110, "text": f"SecOps & QA siap kawal. Kriteria DoD tetap harga mati untuk deliverables '{subj}'!"},
        {"speakerId": p3.get("id", "lib_1"), "speakerRole": p3.get("role", "Knowledge Archivist"), "dept": p3.get("dept", "intelligence"), "thought": f"Validasi SSOT DemusBrain dan cross-link technical decisions untuk '{subj}'.", "speech": f"Semua milestone dan keputusan teknis '{subj}' langsung disinkronkan ke SSOT vault.", "startFrame": 470, "duration": 110, "text": f"Semua milestone dan keputusan teknis '{subj}' langsung disinkronkan ke SSOT vault."},
        {"speakerId": "exec_1", "speakerRole": "Lead Orchestrator", "dept": "executive", "thought": f"Alignment tercapai. Strategi dan penugasan '{subj}' terkunci rapat.", "speech": f"Konsensus tercapai untuk '{subj}'! Bubar rapat dan eksekusi dengan strict DoD!", "startFrame": 585, "duration": 110, "text": f"Konsensus tercapai untuk '{subj}'! Bubar rapat dan eksekusi dengan strict DoD!"},
        {"isChorus": True, "speakerRole": "All Delegates", "thought": "Konsensus disepakati serentak oleh seluruh divisi.", "speech": "Konsensus tercapai. Disperse dan eksekusi!", "startFrame": 700, "duration": 85, "text": "Konsensus tercapai. Disperse dan eksekusi!", "chorusItems": [
            {"speakerId": p0.get("id", "eng_2"), "text": "Compiling!", "dept": p0.get("dept", "engineering")},
            {"speakerId": p1.get("id", "lab_1"), "text": "Sparred!", "dept": p1.get("dept", "intelligence")},
            {"speakerId": p2.get("id", "sec_7"), "text": "Verified!", "dept": p2.get("dept", "secops")},
            {"speakerId": p3.get("id", "lib_1"), "text": "Compounded!", "dept": p3.get("dept", "intelligence")}
        ]}
    ]

# --- Local API Server for QWebEngineView ---
class LocalApiHandler(BaseHTTPRequestHandler):
    cached_status = None
    last_fetch_time = 0

    def log_message(self, format, *args):
        pass # Silence console logging

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?") or self.path.startswith("/index.html"):
            now = time.time()
            if not LocalApiHandler.cached_status or (now - LocalApiHandler.last_fetch_time > 12):
                LocalApiHandler.cached_status = self.build_status_payload()
                LocalApiHandler.last_fetch_time = now
            state_json = json.dumps(LocalApiHandler.cached_status)
            injected_html = HTML_INTERFACE.replace(
                "/* __INITIAL_STATE_PLACEHOLDER__ */",
                f"window.__INITIAL_STATE__ = {state_json};"
            ).replace(
                "/* __PIXEL_ASSETS_BUNDLE__ */ {}",
                PIXEL_ASSETS_BUNDLE_JSON
            )
            html_bytes = injected_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)
        elif self.path == "/api/pixel-assets":
            data_bytes = PIXEL_ASSETS_BUNDLE_JSON.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
        elif self.path == "/api/status":
            now = time.time()
            if not LocalApiHandler.cached_status or (now - LocalApiHandler.last_fetch_time > 12):
                LocalApiHandler.cached_status = self.build_status_payload()
                LocalApiHandler.last_fetch_time = now
                
            data_bytes = json.dumps(LocalApiHandler.cached_status).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
        elif self.path == "/api/subagents" or self.path.startswith("/api/subagents"):
            query_cid = None
            if "?" in self.path:
                try:
                    params = urllib.parse.parse_qs(self.path.split("?")[1])
                    query_cid = params.get("cid", [None])[0]
                except Exception:
                    pass
            dag_data = subagent_tracker.parse_conversation_dag(query_cid)
            data_bytes = json.dumps(dag_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
        elif self.path == "/api/mcp":
            mcp_data = mcp_supervisor.get_mcp_matrix()
            data_bytes = json.dumps(mcp_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data_bytes)))
            self.end_headers()
            self.wfile.write(data_bytes)
        elif self.path == "/app_icon.png":
            if os.path.exists(ICON_PNG):
                png_bytes = open(ICON_PNG, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.end_headers()
                self.wfile.write(png_bytes)
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path in ["/assets/office_floor_pixel.png", "/office_floor_pixel.png"] or self.path.startswith("/assets/office_floor_pixel.png"):
            target_path = OFFICE_PIXEL_PNG
            if not target_path or not os.path.exists(target_path):
                target_path = next((p for p in possible_office_pngs if os.path.exists(p)), "")
            if target_path and os.path.exists(target_path):
                png_bytes = open(target_path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Content-Length", str(len(png_bytes)))
                self.end_headers()
                self.wfile.write(png_bytes)
            else:
                self.send_response(404)
                self.end_headers()
        elif self.path.startswith("/assets/vendor/"):
            rel_file = self.path[len("/assets/vendor/"):].split("?")[0]
            clean_name = os.path.basename(rel_file)
            target_path = os.path.join(_REPO_DIR, "assets", "vendor", clean_name)
            if not os.path.exists(target_path):
                target_path = os.path.join(APP_DIR, "assets", "vendor", clean_name)
            if not os.path.exists(target_path):
                target_path = os.path.join(BUNDLE_DIR, "assets", "vendor", clean_name)
            if target_path and os.path.exists(target_path):
                js_bytes = open(target_path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(js_bytes)))
                self.end_headers()
                self.wfile.write(js_bytes)
            else:
                self.send_response(404)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len) if content_len > 0 else b'{}'
        try:
            req_data = json.loads(body.decode("utf-8"))
        except Exception:
            req_data = {}

        if self.path == "/api/switch":
            target = req_data.get("email")
            if target:
                switch_to_account_core(target)
                LocalApiHandler.cached_status = None
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/toggle-autopilot":
            enable = req_data.get("enable", True)
            success = set_autopilot_state(enable)
            LocalApiHandler.cached_status = None
            is_running, _ = is_autopilot_running()
            resp_bytes = json.dumps({"status": "ok" if success else "error", "autopilot": bool(is_running)}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/delete":
            target = req_data.get("email")
            if target:
                acc_dir = os.path.join(ACCOUNTS_DIR, target)
                if os.path.exists(acc_dir):
                    shutil.rmtree(acc_dir)
                if os.path.exists(ACTIVE_FILE):
                    try:
                        cur = open(ACTIVE_FILE).read().strip()
                        if cur == target:
                            os.remove(ACTIVE_FILE)
                    except Exception:
                        pass
                LocalApiHandler.cached_status = None
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/enroll":
            save_active_credential()
            stop_antigravity()
            delete_windows_credential(CRED_TARGET)
            clear_session_cache()
            if os.path.exists(ACTIVE_FILE):
                os.remove(ACTIVE_FILE)
            start_antigravity()
            LocalApiHandler.cached_status = None
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/clear-logs":
            if os.path.exists(LOG_FILE):
                open(LOG_FILE, "w").close()
            LocalApiHandler.cached_status = None
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/mcp/ping":
            server_name = req_data.get("name")
            res = mcp_supervisor.ping_mcp_server(server_name) if server_name else {"success": False, "error": "Missing name"}
            resp_bytes = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/mcp/restart":
            server_name = req_data.get("name")
            res = mcp_supervisor.restart_mcp_server(server_name) if server_name else {"success": False, "error": "Missing name"}
            resp_bytes = json.dumps(res).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/window/minimize":
            if WINDOW_INSTANCE:
                WINDOW_INSTANCE.sig_minimize.emit()
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/window/maximize":
            if WINDOW_INSTANCE:
                WINDOW_INSTANCE.sig_toggle_max.emit()
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/window/close":
            if WINDOW_INSTANCE:
                WINDOW_INSTANCE.sig_close.emit()
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/window/quit":
            if WINDOW_INSTANCE:
                WINDOW_INSTANCE.sig_quit.emit()
            else:
                QtCore.QTimer.singleShot(50, QApplication.instance().quit)
            resp_bytes = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
        elif self.path == "/api/office/send_prompt":
            prompt = req_data.get("prompt", "")
            success, msg = inject_prompt_via_cdp(prompt)
            resp_bytes = json.dumps({"success": success, "message": msg}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        elif self.path == "/api/office/generate_meeting_dialogue":
            prompt = req_data.get("prompt", "")
            participants = req_data.get("participants", [])
            mission = req_data.get("mission", "")
            dialogues = generate_office_deliberation_llm(prompt, participants, mission)
            resp_bytes = json.dumps({"status": "ok", "dialogues": dialogues}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_bytes)))
            self.end_headers()
            self.wfile.write(resp_bytes)

        else:
            self.send_response(404)
            self.end_headers()

    def build_status_payload(self):
        active = save_active_credential()
        accounts = get_saved_accounts()
        ap_running, _ = is_autopilot_running()

        quotas = {}
        with ThreadPoolExecutor(max_workers=min(len(accounts), 5) or 1) as executor:
            future_to_acc = {executor.submit(fetch_quota_summary, acc): acc for acc in accounts}
            for future in future_to_acc:
                acc = future_to_acc[future]
                try:
                    q = future.result()
                    # Pre-calculate delta strings for web view
                    for grp in ['gemini', 'claude']:
                        if grp in q:
                            for w in ['5h', 'weekly']:
                                if w in q[grp] and isinstance(q[grp][w], dict):
                                    rt = q[grp][w].get("resetTime")
                                    q[grp][w]["resetDelta"] = parse_reset_delta(rt)
                    quotas[acc] = q
                except Exception as e:
                    quotas[acc] = {"error": str(e)}

        ranked = sorted(accounts, key=lambda a: score_account(quotas.get(a)), reverse=True)
        best = ranked[0] if ranked else None

        # Parse logs
        parsed_logs = []
        if os.path.exists(LOG_FILE):
            try:
                lines = open(LOG_FILE, "r", encoding="utf-8", errors="ignore").readlines()
                recent = lines[-40:]
                recent.reverse()
                for raw in recent:
                    raw = raw.strip()
                    if not raw:
                        continue
                    m = re.match(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)", raw)
                    ts = m.group(1) if m else "-"
                    body = m.group(2) if m else raw
                    # Strip any legacy decorative emojis from historical log entries
                    body = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf]', '', body).strip()
                    
                    if "LIMIT TERDETEKSI" in body:
                        evt = "LIMIT"
                    elif "Auto-Switch" in body:
                        evt = "SWITCH"
                    elif "CDP" in body or "dilanjutkan" in body or "sukses" in body.lower():
                        evt = "RESUMED"
                    elif "Akun terbaik" in body:
                        evt = "EVAL"
                    else:
                        evt = "INFO"
                    parsed_logs.append({"time": ts.split(" ")[1] if " " in ts else ts, "type": evt, "desc": body})
            except Exception:
                pass

        return {
            "active": active,
            "accounts": accounts,
            "quotas": quotas,
            "autopilot": bool(ap_running),
            "best": best,
            "logs": parsed_logs
        }

class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def start_local_server():
    global LOCAL_SERVER_INSTANCE, ACTUAL_PORT
    for p in range(28795, 28830):
        try:
            server = ReusableThreadingServer(("127.0.0.1", p), LocalApiHandler)
            LOCAL_SERVER_INSTANCE = server
            ACTUAL_PORT = p
            server.serve_forever()
            return
        except OSError:
            continue

def apply_dwm_frameless_styling(hwnd):
    try:
        dwm = ctypes.windll.dwmapi
        # Windows 11 rounded corners: DWMWA_WINDOW_CORNER_PREFERENCE = 33 (DWMWCP_ROUND = 2)
        corner = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(33), ctypes.byref(corner), ctypes.sizeof(corner))
        # Hairline obsidian border: DWMWA_BORDER_COLOR = 34 (0x00222222)
        border_color = ctypes.c_int(0x00222222)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), wintypes.DWORD(34), ctypes.byref(border_color), ctypes.sizeof(border_color))
    except Exception:
        pass

# --- Native Instant Splash Screen (Zero Black Screen) ---
class AntigravityNativeSplashScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(380, 220)

        # Center on primary active screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            self.move((geo.width() - 380) // 2, (geo.height() - 220) // 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Container Card with rounded corners, obsidian backdrop, and hairline border
        self.card = QWidget(self)
        self.card.setStyleSheet("""
            QWidget {
                background-color: #0c0d10;
                border: 1px solid #232733;
                border-radius: 14px;
            }
        """)
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 26, 24, 22)
        card_layout.setSpacing(8)
        card_layout.setAlignment(Qt.AlignCenter)

        # Logo Icon
        self.icon_label = QLabel(self.card)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("border: none; background: transparent;")
        icon_path = ICON_PNG if (ICON_PNG and os.path.exists(ICON_PNG)) else (ICON_ICO if (ICON_ICO and os.path.exists(ICON_ICO)) else None)
        if icon_path:
            pix = QtGui.QPixmap(icon_path).scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label.setPixmap(pix)
        card_layout.addWidget(self.icon_label)

        # Brand Title
        self.title_label = QLabel("Antigravity Control Center", self.card)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
                font-size: 14px;
                font-weight: 700;
                border: none;
                background: transparent;
                letter-spacing: -0.2px;
            }
        """)
        card_layout.addWidget(self.title_label)

        # Subtitle / Status
        self.status_label = QLabel("Loading Antigravity...", self.card)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("""
            QLabel {
                color: #8e95a0;
                font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
                font-size: 11.5px;
                font-weight: 400;
                border: none;
                background: transparent;
            }
        """)
        card_layout.addWidget(self.status_label)

        # Animated 3 Wave Dots Label: "●  ○  ○"
        self.dots_label = QLabel("●  ○  ○", self.card)
        self.dots_label.setAlignment(Qt.AlignCenter)
        self.dots_label.setStyleSheet("""
            QLabel {
                color: #38bdf8;
                font-size: 11px;
                font-family: 'JetBrains Mono', Consolas, monospace;
                border: none;
                background: transparent;
                letter-spacing: 3px;
            }
        """)
        card_layout.addWidget(self.dots_label)

        layout.addWidget(self.card)

        # Dot animation timer
        self.dot_step = 0
        self.dot_timer = QTimer(self)
        self.dot_timer.timeout.connect(self._animate_dots)
        self.dot_timer.start(160)

        apply_dwm_frameless_styling(int(self.winId()))

    def _animate_dots(self):
        self.dot_step = (self.dot_step + 1) % 4
        frames = ["●  ○  ○", "○  ●  ○", "○  ○  ●", "●  ●  ●"]
        self.dots_label.setText(frames[self.dot_step])

    def close_with_fade(self, parent_win=None):
        try:
            self.dot_timer.stop()
        except Exception:
            pass
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(160)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self.close)
        self._fade_anim.start()

# --- Desktop Window Host ---
class AntigravityProWindow(QMainWindow):
    sig_toggle_max = QtCore.pyqtSignal()
    sig_minimize = QtCore.pyqtSignal()
    sig_close = QtCore.pyqtSignal()
    sig_quit = QtCore.pyqtSignal()

    def __init__(self, splash=None):
        super().__init__()
        self.splash = splash
        self._already_revealed = False
        self._is_custom_maximized = False
        self._normal_geometry = None
        self._max_anim = None
        self._min_anim = None
        self._restore_anim = None

        self.sig_toggle_max.connect(self.window_toggle_max)
        self.sig_minimize.connect(self.window_minimize)
        self.sig_close.connect(self.window_close)
        self.sig_quit.connect(QApplication.instance().quit)

        # Ensure WS_MINIMIZEBOX and WS_MAXIMIZEBOX on Windows
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            style = user32.GetWindowLongW(hwnd, -16)
            style |= 0x00020000 | 0x00010000 | 0x00080000
            user32.SetWindowLongW(hwnd, -16, style)
        except Exception:
            pass

        self.setWindowTitle("Antigravity Control Center")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(840, 800)
        self.setMinimumSize(660, 680)

        icon_to_use = QIcon(ICON_ICO) if os.path.exists(ICON_ICO) else (QIcon(ICON_PNG) if os.path.exists(ICON_PNG) else None)
        if icon_to_use:
            self.setWindowIcon(icon_to_use)

        self.browser = QWebEngineView(self)
        self.browser.page().setBackgroundColor(QtGui.QColor("#0c0d10"))
        self.setCentralWidget(self.browser)
        self.browser.loadFinished.connect(self._on_web_load_finished)
        self.browser.load(QUrl(f"http://127.0.0.1:{ACTUAL_PORT}"))

        # Safety fallback timer: reveal window after 4.5 seconds if loadFinished never fires
        self._load_fallback_timer = QTimer(self)
        self._load_fallback_timer.setSingleShot(True)
        self._load_fallback_timer.timeout.connect(self._reveal_main_window)
        self._load_fallback_timer.start(4500)

        self.init_tray()

    def _on_web_load_finished(self, ok):
        if hasattr(self, "_load_fallback_timer") and self._load_fallback_timer.isActive():
            self._load_fallback_timer.stop()
        if hasattr(self, "browser") and self.browser.page():
            self.browser.page().runJavaScript("if (typeof dismissAppLoader === 'function') dismissAppLoader();")
        self._reveal_main_window()

    def _reveal_main_window(self):
        if self._already_revealed:
            return
        self._already_revealed = True

        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        apply_dwm_frameless_styling(int(self.winId()))
        QTimer.singleShot(50, lambda: apply_dwm_frameless_styling(int(self.winId())))

        self._show_anim = QPropertyAnimation(self, b"windowOpacity")
        self._show_anim.setDuration(160)
        self._show_anim.setStartValue(0.0)
        self._show_anim.setEndValue(1.0)
        self._show_anim.start()

        if self.splash:
            try:
                self.splash.close_with_fade(self)
            except Exception:
                self.splash.close()
            self.splash = None

    def is_window_maximized(self):
        return self._is_custom_maximized or self.isMaximized()

    def window_toggle_max(self):
        if self.isMaximized() or self._is_custom_maximized:
            self._is_custom_maximized = False
            self.showNormal()
            if hasattr(self, "browser") and self.browser.page():
                self.browser.page().runJavaScript("if (typeof setMaximizedState === 'function') setMaximizedState(false);")
        else:
            self._is_custom_maximized = True
            self.showMaximized()
            if hasattr(self, "browser") and self.browser.page():
                self.browser.page().runJavaScript("if (typeof setMaximizedState === 'function') setMaximizedState(true);")

    def window_minimize(self):
        self.showMinimized()

    def window_close(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
        else:
            self.close()

    def nativeEvent(self, eventType, message):
        msg = wintypes.MSG.from_address(message.__int__())
        if msg.message == 0x0084:  # WM_NCHITTEST
            x = msg.lParam & 0xFFFF
            if x > 32767: x -= 65536
            y = (msg.lParam >> 16) & 0xFFFF
            if y > 32767: y -= 65536
            
            p = self.mapFromGlobal(QPoint(x, y))
            w = self.width()
            h = self.height()
            
            # 1. Top bar interaction zone (0 <= y < 36)
            if 0 <= p.y() < 36:
                # Window control buttons (Minimize, Maximize, Close on far right)
                if p.x() >= (w - 140):
                    return True, 1  # HTCLIENT (Delivers 100% of clicks directly to web buttons)
                # Logo & Menu dropdowns on left
                if p.x() < 350:
                    return True, 1  # HTCLIENT (Delivers menu clicks)
                # Middle title region: Native Drag & Double-Click Maximize
                return True, 2  # HTCAPTION

            # 2. Resize borders when NOT maximized
            if not self.is_window_maximized():
                border = 6
                left = p.x() < border
                right = p.x() > w - border
                bottom = p.y() > h - border
                top = p.y() < border
                
                if top and left: return True, 13     # HTTOPLEFT
                if top and right: return True, 14    # HTTOPRIGHT
                if bottom and left: return True, 16  # HTBOTTOMLEFT
                if bottom and right: return True, 17 # HTBOTTOMRIGHT
                if left: return True, 10             # HTLEFT
                if right: return True, 11            # HTRIGHT
                if bottom: return True, 15           # HTBOTTOM
                if top: return True, 12              # HTTOP
                
            return True, 1  # HTCLIENT for the entire application body
                
        elif msg.message == 0x00A3:  # WM_NCLBUTTONDBLCLK
            if msg.wParam == 2:  # HTCAPTION
                self.window_toggle_max()
                return True, 0

        return super().nativeEvent(eventType, message)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.WindowStateChange:
            is_max = self.is_window_maximized()
            if hasattr(self, "browser") and self.browser.page():
                self.browser.page().runJavaScript(f"if (typeof setMaximizedState === 'function') setMaximizedState({str(is_max).lower()});")
        super().changeEvent(event)

    def init_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
            
        self.tray_icon = QSystemTrayIcon(self)
        icon_to_use = QIcon(ICON_ICO) if os.path.exists(ICON_ICO) else (QIcon(ICON_PNG) if os.path.exists(ICON_PNG) else None)
        if icon_to_use:
            self.tray_icon.setIcon(icon_to_use)
            
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #191919;
                color: #E2E8F0;
                border: 1px solid #222222;
                border-radius: 6px;
                padding: 4px;
                font-family: system-ui, -apple-system, sans-serif;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #272727;
                color: #FFFFFF;
            }
        """)
        
        act_show = QAction("Open Control Center", self)
        act_show.triggered.connect(self.show_normal_window)
        menu.addAction(act_show)
        
        menu.addSeparator()
        
        act_quit = QAction("Quit Application", self)
        act_quit.triggered.connect(QApplication.instance().quit)
        menu.addAction(act_quit)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal_window()

    def show_normal_window(self):
        self.setWindowOpacity(0.0)
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
        self.activateWindow()
        apply_dwm_frameless_styling(int(self.winId()))
        self._restore_anim = QPropertyAnimation(self, b"windowOpacity")
        self._restore_anim.setDuration(160)
        self._restore_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._restore_anim.setStartValue(0.0)
        self._restore_anim.setEndValue(1.0)
        self._restore_anim.start()

    def showEvent(self, event):
        super().showEvent(event)
        apply_dwm_frameless_styling(int(self.winId()))

    def closeEvent(self, event):
        if QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            event.accept()

def main():
    if "--daemon" in sys.argv:
        try:
            from antigravity_switcher import daemon
            daemon.main_loop()
        except ImportError:
            import daemon
            daemon.main_loop()
        sys.exit(0)

    if "--cli" in sys.argv:
        try:
            from antigravity_switcher import switcher
            switcher.main()
        except ImportError:
            import switcher
            switcher.main()
        sys.exit(0)

    ensure_dirs()

    # 1. Initialize Qt Application first so Native Splash Screen can show in 0.01s
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    icon_to_use = QIcon(ICON_ICO) if os.path.exists(ICON_ICO) else (QIcon(ICON_PNG) if os.path.exists(ICON_PNG) else None)
    if icon_to_use:
        app.setWindowIcon(icon_to_use)

    # 2. Instantly display Native Splash Screen (ZERO Black Screen!)
    splash = AntigravityNativeSplashScreen()
    splash.show()
    app.processEvents()

    # 3. Start local server in background thread while splash is showing
    server_thread = threading.Thread(target=start_local_server, daemon=True)
    server_thread.start()
    for _ in range(40):
        if LOCAL_SERVER_INSTANCE is not None:
            break
        time.sleep(0.05)
        app.processEvents()

    # 4. Instantiate Main Window in background (reveals seamlessly on loadFinished)
    win = AntigravityProWindow(splash=splash)
    global WINDOW_INSTANCE
    WINDOW_INSTANCE = win

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
