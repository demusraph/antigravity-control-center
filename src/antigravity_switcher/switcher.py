import os
import sys
import re
import json
import base64
import sqlite3
import shutil
import subprocess
import time
import ctypes
from ctypes import wintypes
import urllib.request
import urllib.parse
import unicodedata
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# --- Console Initialization & Virtual Terminal Mode ---
def enable_vt_mode():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004) # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass

enable_vt_mode()

# --- Windows Credential Manager API ---
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
CRED_TARGET = "gemini:antigravity"

# Obfuscated runtime credentials (Google Antigravity public client)
_K = 0x37
_ID_B = [6,7,0,6,7,7,1,7,1,7,2,14,6,26,67,90,95,68,68,94,89,5,95,5,6,91,84,69,82,5,4,2,65,67,88,91,88,93,95,3,80,3,7,4,82,71,25,86,71,71,68,25,80,88,88,80,91,82,66,68,82,69,84,88,89,67,82,89,67,25,84,88,90]
_SEC_B = [112,120,116,100,103,111,26,124,2,15,113,96,101,3,15,1,123,83,123,125,6,90,123,117,15,68,111,116,3,77,1,70,115,118,81]
CLIENT_ID = bytes([b ^ _K for b in _ID_B]).decode("utf-8")
CLIENT_SECRET = bytes([b ^ _K for b in _SEC_B]).decode("utf-8")

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
    cred.Type = 1 # CRED_TYPE_GENERIC
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

# Paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
APPDATA = os.environ.get("APPDATA", "")
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
USERPROFILE = os.environ.get("USERPROFILE", "")

ANTIGRAV_ROAMING = os.path.join(APPDATA, "Antigravity")
ANTIGRAV_EXE = os.path.join(LOCALAPPDATA, "Programs", "Antigravity", "Antigravity.exe")
STATE_VSCDB_FILE = os.path.join(ANTIGRAV_ROAMING, "User", "globalStorage", "state.vscdb")
COOKIES_FILE = os.path.join(ANTIGRAV_ROAMING, "Network", "Cookies")
COOKIES_JOURNAL = os.path.join(ANTIGRAV_ROAMING, "Network", "Cookies-journal")
APP_STORAGE_JSON = os.path.join(ANTIGRAV_ROAMING, "app_storage.json")

SWITCHER_DIR = os.path.join(USERPROFILE, ".gemini", "antigravity-switcher")
ACCOUNTS_DIR = os.path.join(SWITCHER_DIR, "accounts")
ACTIVE_FILE = os.path.join(SWITCHER_DIR, "active_email.txt")
ENROLL_LOCK_FILE = os.path.join(SWITCHER_DIR, "enrolling.lock")
AUTOPILOT_PID_FILE = os.path.join(SWITCHER_DIR, "autopilot.pid")
LOG_FILE = os.path.join(SWITCHER_DIR, "autopilot.log")
DAEMON_SCRIPT = os.path.join(APP_DIR, "agy_daemon.py")

def get_antigravity_exe():
    candidates = [
        ANTIGRAV_EXE,
        os.path.join(LOCALAPPDATA, "Programs", "antigravity", "Antigravity.exe"),
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "Antigravity", "Antigravity.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    try:
        w = shutil.which("Antigravity") or shutil.which("antigravity")
        if w:
            return w
    except Exception:
        pass
    return ANTIGRAV_EXE

def ensure_dirs():
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)

# --- ANSI Formatting & Box Helpers ---
ANSI_REGEX = re.compile(r'\033\[[0-9;]*m')

def char_width(c):
    w = unicodedata.east_asian_width(c)
    return 2 if w in ('W', 'F') else 1

def visible_len(s):
    clean = ANSI_REGEX.sub('', s)
    return sum(char_width(c) for c in clean)

def pad_box_line(content, width=84):
    v_len = visible_len(content)
    pad = max(0, width - 4 - v_len)
    return f"\033[90m│\033[0m {content}{' ' * pad} \033[90m│\033[0m"

def make_box_top(title="", width=84):
    if title:
        prefix = f"╭─ {title} "
        v_len = visible_len(prefix)
        rem = max(0, width - v_len - 1)
        return f"\033[90m{prefix}{'─' * rem}╮\033[0m"
    return f"\033[90m╭{'─' * (width - 2)}╮\033[0m"

def make_box_bottom(width=84):
    return f"\033[90m╰{'─' * (width - 2)}╯\033[0m"

def format_bar(pct, width=10):
    pct_int = int(round(pct))
    pct_int = max(0, min(100, pct_int))
    filled = int(round(width * (pct_int / 100.0)))
    filled = max(0, min(width, filled))
    empty = width - filled
    if pct_int >= 70:
        col = "\033[92m" # Green
    elif pct_int >= 20:
        col = "\033[93m" # Yellow / Gold
    else:
        col = "\033[91m" # Red
    return f"{col}[{'█' * filled}{'░' * empty}] {pct_int:3d}%\033[0m"

def parse_reset_delta(reset_time_str):
    if not reset_time_str:
        return ""
    try:
        dt = datetime.fromisoformat(reset_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = dt - now
        total_seconds = int(diff.total_seconds())
        if total_seconds <= 0:
            return "Reset"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours >= 24:
            days = hours // 24
            rem_h = hours % 24
            return f"{days}h {rem_h}j"
        elif hours > 0:
            return f"{hours}j {minutes}m"
        else:
            return f"{minutes}m"
    except Exception:
        return ""

# --- Google API & Token Refresh ---
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
        
        # 1. Primary: Fast offline decode from id_token JWT (Modern Antigravity format)
        id_token = data.get("id_token")
        if id_token and isinstance(id_token, str):
            parts = id_token.split('.')
            if len(parts) >= 2:
                try:
                    payload_b64 = parts[1] + '=' * (-len(parts[1]) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode('utf-8'))
                    email = payload.get("email")
                    if email:
                        return email
                except Exception:
                    pass

        # 2. Secondary fallback: Refresh token and query Google UserInfo API (Legacy format)
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
    print("  \033[90m-> Menutup Antigravity...\033[0m")
    try:
        subprocess.run(["taskkill", "/F", "/T", "/IM", "Antigravity.exe"], capture_output=True, text=True)
    except Exception:
        pass
    for _ in range(10):
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Antigravity.exe"], capture_output=True, text=True).stdout
            if "Antigravity.exe" not in out:
                break
        except Exception:
            pass
        time.sleep(0.5)

def start_antigravity():
    print("  \033[90m-> Membuka Antigravity...\033[0m")
    exe = get_antigravity_exe()
    if os.path.exists(exe):
        subprocess.Popen([exe], shell=True)
    else:
        print(f"  \033[91mWarning: Tidak dapat menemukan {exe}\033[0m")

def clear_session_cache():
    # 1. Chromium network cookies & journal
    for cf in [COOKIES_FILE, COOKIES_JOURNAL]:
        if os.path.exists(cf):
            try:
                os.remove(cf)
            except Exception:
                pass

    # 2. Antigravity SQLite state.vscdb
    if os.path.exists(STATE_VSCDB_FILE):
        try:
            conn = sqlite3.connect(STATE_VSCDB_FILE)
            c = conn.cursor()
            c.execute("DELETE FROM ItemTable WHERE key IN ('antigravityOnboarding', 'antigravityUnifiedStateSync.onboarding', 'antigravityUnifiedStateSync.oauthToken', 'antigravityUnifiedStateSync.userStatus')")
            conn.commit()
            conn.close()
        except Exception:
            pass

    # 3. Antigravity app_storage.json (remove last login user memory)
    if os.path.exists(APP_STORAGE_JSON):
        try:
            with open(APP_STORAGE_JSON, "r", encoding="utf-8") as f:
                app_storage = json.load(f)
            modified = False
            for k in ["jetski.onboarding.lastLoginUsername", "jetski.onboarding.lastLoginIsGcpTos"]:
                if k in app_storage:
                    del app_storage[k]
                    modified = True
            if modified:
                with open(APP_STORAGE_JSON, "w", encoding="utf-8") as f:
                    json.dump(app_storage, f, indent=2)
        except Exception:
            pass

def switch_to_account(target_email):
    ensure_dirs()
    print(f"\n\033[36m[1/3]\033[0m Menyimpan sesi akun saat ini...")
    save_active_credential()
    
    acc_dir = os.path.join(ACCOUNTS_DIR, target_email)
    cred_file = os.path.join(acc_dir, "cred.bin")
    
    if not os.path.exists(cred_file):
        print(f"\033[91mError: Akun {target_email} tidak ditemukan!\033[0m")
        return False
        
    print(f"\033[36m[2/3]\033[0m Menyiapkan sesi akun \033[1;97m[{target_email}]\033[0m...")
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
        
    print(f"\033[36m[3/3]\033[0m \033[92mBerhasil beralih ke [{target_email}]!\033[0m")
    start_antigravity()
    return True

def setup_new_account():
    width = 84
    ensure_dirs()
    print(f"\n\033[36m[1/3]\033[0m Menyimpan sesi akun yang sedang aktif...")
    prev_email = save_active_credential()
    
    # Pasang enrollment lock agar background daemon tidak menginterupsi/auto-switch
    try:
        with open(ENROLL_LOCK_FILE, "w", encoding="utf-8") as f:
            f.write(str(int(time.time())))
    except Exception:
        pass
        
    print(f"\033[36m[2/3]\033[0m Membersihkan sesi untuk login akun baru...")
    stop_antigravity()
    delete_windows_credential(CRED_TARGET)
    clear_session_cache()
    
    if os.path.exists(ACTIVE_FILE):
        try:
            os.remove(ACTIVE_FILE)
        except Exception:
            pass
        
    start_antigravity()
    print(f"\033[36m[3/3]\033[0m Membuka jendela Antigravity...")
    
    print("\n" + make_box_top("\033[1;36m🔑 PENDAFTARAN AKUN BARU\033[0m", width))
    print(pad_box_line("1. Antigravity telah dibuka dengan sesi kosong.", width))
    print(pad_box_line("2. Silakan klik 'Sign In' di jendela Antigravity dengan akun Google barumu.", width))
    print(pad_box_line("", width))
    print(pad_box_line("\033[93m⏳ Menunggu Anda menyelesaikan login di Antigravity...\033[0m", width))
    print(pad_box_line("\033[90m   (Tekan Ctrl+C jika ingin membatalkan pendaftaran)\033[0m", width))
    print(make_box_bottom(width))
    
    new_email = None
    try:
        for _ in range(150): # Polling hingga 5 menit
            time.sleep(2)
            cred = read_windows_credential()
            if cred and cred.get("blob"):
                email = fetch_email_from_blob(cred["blob"])
                if email and email != "default_account" and email != prev_email:
                    new_email = email
                    save_active_credential()
                    break
    except KeyboardInterrupt:
        print("\n\033[93mPendaftaran dibatalkan oleh user.\033[0m")
    finally:
        if os.path.exists(ENROLL_LOCK_FILE):
            try:
                os.remove(ENROLL_LOCK_FILE)
            except Exception:
                pass
                
    if new_email:
        print(f"\n\033[1;92m🎉 Sukses! Akun baru [{new_email}] berhasil terdaftar dan aktif!\033[0m")
        time.sleep(2)
        return True
    else:
        if prev_email:
            print(f"\n\033[90mTidak ada login baru terdeteksi. Mengembalikan ke akun sebelumnya [{prev_email}]...\033[0m")
            switch_to_account(prev_email)
        return False

def remove_account_flow(accounts, current_email):
    width = 84
    print("\n" + make_box_top("\033[1;91m🗑️  HAPUS AKUN DARI SWITCHER\033[0m", width))
    for idx, acc in enumerate(accounts, 1):
        tag = " \033[92m● AKTIF\033[0m" if acc == current_email else ""
        print(pad_box_line(f"[\033[1;97m{idx}\033[0m] {acc}{tag}", width))
    print(pad_box_line("[\033[1;97m0\033[0m] \033[90mBatal\033[0m", width))
    print(make_box_bottom(width))
    
    choice = input("\033[1;36magy:hapus > \033[0m").strip()
    if choice == "0" or choice.lower() in ["batal", "cancel", "q", ""]:
        print("\033[90mPenghapusan dibatalkan.\033[0m\n")
        return
        
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(accounts):
            target = accounts[idx]
            confirm = input(f"\033[93mYakin ingin menghapus [{target}]? (y/n): \033[0m").strip().lower()
            if confirm == 'y':
                acc_dir = os.path.join(ACCOUNTS_DIR, target)
                if os.path.exists(acc_dir):
                    shutil.rmtree(acc_dir)
                print(f"\033[92m✅ Akun [{target}] berhasil dihapus!\033[0m\n")
                if target == current_email:
                    if os.path.exists(ACTIVE_FILE):
                        os.remove(ACTIVE_FILE)
                    print("\033[93m⚠️ Akun yang dihapus adalah akun yang sedang aktif.\033[0m")
                    print("   \033[90mSilakan pilih akun lain untuk diaktifkan.\033[0m\n")
            else:
                print("\033[90mBatal menghapus.\033[0m\n")
        else:
            print("\033[91mNomor akun tidak valid.\033[0m\n")
    else:
        print("\033[91mInput tidak valid.\033[0m\n")

# --- Auto-Pilot Daemon Management ---
def is_autopilot_running():
    if not os.path.exists(AUTOPILOT_PID_FILE):
        return False, None
    try:
        pid = int(open(AUTOPILOT_PID_FILE).read().strip())
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True, pid
    except Exception:
        pass
    return False, None

def toggle_autopilot():
    running, pid = is_autopilot_running()
    if running:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        except Exception:
            pass
        if os.path.exists(AUTOPILOT_PID_FILE):
            os.remove(AUTOPILOT_PID_FILE)
        print("\n\033[91m🛑 Auto-Pilot Overnight telah DIMATIKAN (OFF).\033[0m")
        print("   \033[90mDaemon latar belakang telah dinonaktifkan.\033[0m\n")
    else:
        if not os.path.exists(DAEMON_SCRIPT):
            print(f"\033[91mError: Script daemon tidak ditemukan di {DAEMON_SCRIPT}\033[0m")
            return
        DETACHED_FLAGS = 0x00000008 | 0x00000200 # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen([sys.executable, DAEMON_SCRIPT], creationflags=DETACHED_FLAGS, close_fds=True)
        with open(AUTOPILOT_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        print("\n\033[92m🚀 Auto-Pilot Overnight telah DIAKTIFKAN (ON)!\033[0m")
        print("   \033[97mDaemon aktif di latar belakang. Kamu bisa tinggal tidur.\033[0m")
        print("   \033[90mSaat kuota limit, akun otomatis switch round-robin & auto-resume tugas.\033[0m")
        print(f"   \033[90mLog: {LOG_FILE}\033[0m\n")

# --- Log Viewer ---
def view_autopilot_logs():
    width = 84
    print("\n" + make_box_top("\033[1;97m📜 RIWAYAT AUTO-PILOT (18 Aktivitas Terakhir)\033[0m", width))
    if not os.path.exists(LOG_FILE):
        print(pad_box_line("\033[90mBelum ada riwayat aktivitas tercatat.\033[0m", width))
    else:
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                lines = [l.strip() for l in f if l.strip()]
            if not lines:
                print(pad_box_line("\033[90mFile log kosong / belum ada catatan.\033[0m", width))
            else:
                recent = lines[-18:]
                for raw in recent:
                    styled = raw
                    styled = re.sub(r"^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\])", r"\033[90m\1\033[0m", styled)
                    if "LIMIT TERDETEKSI" in styled or "RESOURCE_EXHAUSTED" in styled:
                        styled = styled.replace("⚠️ LIMIT TERDETEKSI", "\033[1;91m⚠️ LIMIT TERDETEKSI\033[0m")
                    elif "Auto-Switch" in styled:
                        styled = styled.replace("🚀 Memulai Auto-Switch", "\033[1;96m🚀 Auto-Switch\033[0m")
                    elif "Selesai" in styled or "Berhasil" in styled:
                        styled = styled.replace("Selesai", "\033[92mSelesai\033[0m")
                    elif "Akun terbaik terpilih" in styled:
                        styled = styled.replace("Akun terbaik terpilih", "\033[93m★ Akun Terpilih\033[0m")
                    
                    clean_len = visible_len(styled)
                    max_content = width - 4
                    if clean_len > max_content:
                        styled = styled[:max_content - 3] + "..." + "\033[0m"
                    print(pad_box_line(styled, width))
        except Exception as e:
            print(pad_box_line(f"\033[91mGagal membaca log: {e}\033[0m", width))
            
    print(make_box_bottom(width))
    input("\033[90mTekan \033[1;97m[ENTER]\033[90m untuk kembali ke menu utama...\033[0m")

# --- Smart Recommendation Engine ---
def score_account(quota_data):
    if not quota_data or "error" in quota_data:
        return -999999
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

def render_account_card(idx, acc, current_email, quota, is_best, width=84):
    tags = []
    if acc == current_email:
        tags.append("\033[1;92m● AKTIF\033[0m")
    if is_best:
        tags.append("\033[1;93m★ REKOMENDASI\033[0m")
    tag_str = ("  " + " ".join(tags)) if tags else ""
    
    title = f"\033[1;97m[{idx}] {acc}\033[0m{tag_str}"
    lines = [make_box_top(title, width)]
    
    if not quota or "error" in quota:
        err_msg = quota.get("error") if (quota and "error" in quota) else "Offline"
        lines.append(pad_box_line(f"\033[91m⚠️ Quota Tidak Tersedia: {err_msg}\033[0m", width))
    else:
        gemini = quota.get("gemini", {})
        claude = quota.get("claude", {})
        
        def extract_bucket(container, key):
            b = container.get(key, {})
            if isinstance(b, dict):
                return b.get("remaining", 100.0), b.get("resetTime")
            return float(b), None
            
        g_5h_pct, g_5h_rt = extract_bucket(gemini, "5h")
        g_wk_pct, g_wk_rt = extract_bucket(gemini, "weekly")
        c_5h_pct, c_5h_rt = extract_bucket(claude, "5h")
        c_wk_pct, c_wk_rt = extract_bucket(claude, "weekly")
        
        # Countdown strings
        g_5h_cd = f"\033[90m(⏳ {parse_reset_delta(g_5h_rt)})\033[0m" if (g_5h_pct < 100.0 and g_5h_rt) else ""
        g_wk_cd = f"\033[90m(⏳ {parse_reset_delta(g_wk_rt)})\033[0m" if (g_wk_pct < 100.0 and g_wk_rt) else ""
        c_5h_cd = f"\033[90m(⏳ {parse_reset_delta(c_5h_rt)})\033[0m" if (c_5h_pct < 100.0 and c_5h_rt) else ""
        c_wk_cd = f"\033[90m(⏳ {parse_reset_delta(c_wk_rt)})\033[0m" if (c_wk_pct < 100.0 and c_wk_rt) else ""
        
        # Left and Right sections
        g_left = f"\033[36mGemini\033[0m  5h {format_bar(g_5h_pct)} {g_5h_cd}".strip()
        g_right = f"Mggu {format_bar(g_wk_pct)} {g_wk_cd}".strip()
        
        c_left = f"\033[36mClaude\033[0m  5h {format_bar(c_5h_pct)} {c_5h_cd}".strip()
        c_right = f"Mggu {format_bar(c_wk_pct)} {c_wk_cd}".strip()
        
        g_pad = max(1, 40 - visible_len(g_left))
        c_pad = max(1, 40 - visible_len(c_left))
        
        row_g = f"{g_left}{' ' * g_pad}\033[90m│\033[0m  {g_right}"
        row_c = f"{c_left}{' ' * c_pad}\033[90m│\033[0m  {c_right}"
        
        lines.append(pad_box_line(row_g, width))
        lines.append(pad_box_line(row_c, width))
        
    lines.append(make_box_bottom(width))
    return "\n".join(lines)

# --- Main Program Loop ---
def main():
    width = 84
    ensure_dirs()
    
    while True:
        current_email = save_active_credential()
        accounts = get_saved_accounts()
        autopilot_on, _ = is_autopilot_running()
        
        os.system("cls" if os.name == "nt" else "clear")
        
        # 1. Top Status Banner
        print(make_box_top("", width))
        header_title = "\033[1;36m⚡ ANTIGRAVITY (AGY)\033[0m \033[90m─\033[0m \033[1;97mMulti-Account & Quota Controller\033[0m"
        ap_badge = "\033[1;92m[● ON]\033[0m" if autopilot_on else "\033[90m[○ OFF]\033[0m"
        header_meta = f"Aktif: \033[1;97m{current_email or 'None'}\033[0m   \033[90m│\033[0m  Auto-Pilot: {ap_badge}  \033[90m│\033[0m  \033[97m{len(accounts)} Akun Terdaftar\033[0m"
        print(pad_box_line(header_title, width))
        print(pad_box_line(header_meta, width))
        print(make_box_bottom(width))
        
        # 2. Fetch Quotas concurrently
        print("\033[90m  Memperbarui sisa kuota real-time dari Google Cloud...\033[0m")
        quotas = {}
        with ThreadPoolExecutor(max_workers=min(len(accounts), 5) or 1) as executor:
            future_to_acc = {executor.submit(fetch_quota_summary, acc): acc for acc in accounts}
            for future in future_to_acc:
                acc = future_to_acc[future]
                try:
                    quotas[acc] = future.result()
                except Exception as e:
                    quotas[acc] = {"error": str(e)}
                    
        # 3. Score & Recommend
        ranked = sorted(accounts, key=lambda a: score_account(quotas.get(a)), reverse=True)
        best_acc = ranked[0] if ranked else None
        second_best = ranked[1] if len(ranked) > 1 else None
        enter_target = best_acc if best_acc != current_email else second_best
        
        # 4. Render Account Cards
        print()
        for idx, acc in enumerate(accounts, 1):
            is_best = (acc == best_acc)
            print(render_account_card(idx, acc, current_email, quotas.get(acc), is_best, width))
            
        # 5. Commands Action Box
        print(make_box_top("\033[1;97mCOMMANDS\033[0m", width))
        c_line1 = "[\033[1;97m1-" + str(len(accounts)) + "\033[0m] Ganti Akun                  [\033[1;97m+\033[0m] Tambah Akun Baru"
        toggle_label = "MATIKAN" if autopilot_on else "AKTIFKAN"
        c_line2 = f"[\033[1;97mA\033[0m]   Toggle Auto-Pilot ({toggle_label})  [\033[1;97m-\033[0m] Hapus Akun"
        c_line3 = "[\033[1;97mL\033[0m]   Lihat Log Auto-Pilot        [\033[1;97mR\033[0m] Refresh Kuota Real-Time"
        print(pad_box_line(c_line1, width))
        print(pad_box_line(c_line2, width))
        print(pad_box_line(c_line3, width))
        print(pad_box_line("", width))
        
        if enter_target:
            rec_note = f"\033[93m💡 Tekan [ENTER] langsung untuk beralih ke:\033[0m \033[1;97m{enter_target}\033[0m"
            print(pad_box_line(rec_note, width))
        else:
            print(pad_box_line("\033[90m💡 Masukkan nomor akun untuk beralih.\033[0m", width))
        print(make_box_bottom(width))
        
        # 6. Prompt Input
        choice = input("\033[1;36magy > \033[0m").strip()
        
        if choice == "":
            if enter_target:
                if enter_target == current_email:
                    print(f"\n\033[93mAkun [{enter_target}] sudah aktif saat ini.\033[0m")
                    time.sleep(1.5)
                else:
                    switch_to_account(enter_target)
                    break
            else:
                print("\033[90mTidak ada akun lain yang dapat dipilih.\033[0m")
                time.sleep(1)
        elif choice == "+":
            setup_new_account()
            break
        elif choice in ["-", "del", "rm", "remove"]:
            remove_account_flow(accounts, current_email)
            time.sleep(1.5)
        elif choice.lower() in ["a", "ap", "autopilot"]:
            toggle_autopilot()
            time.sleep(2)
        elif choice.lower() in ["l", "log", "logs"]:
            view_autopilot_logs()
        elif choice.lower() in ["r", "refresh"]:
            print("\033[90mMemperbarui data kuota...\033[0m")
            time.sleep(0.5)
            continue
        elif choice.lower() in ["q", "exit", "quit"]:
            print("\n\033[90mKeluar dari Antigravity Switcher. Sampai jumpa!\033[0m\n")
            break
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(accounts):
                target = accounts[idx]
                if target == current_email:
                    print(f"\n\033[93mAkun [{target}] sudah aktif saat ini.\033[0m")
                    time.sleep(1.5)
                else:
                    switch_to_account(target)
                    break
            else:
                print("\033[91mNomor akun tidak valid.\033[0m")
                time.sleep(1.5)
        else:
            print("\033[91mPerintah tidak dikenali.\033[0m")
            time.sleep(1)

if __name__ == "__main__":
    main()
