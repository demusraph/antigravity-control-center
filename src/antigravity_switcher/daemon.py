import os
import sys
import time
import json
import base64
import socket
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Base paths
APP_DIR = os.path.dirname(os.path.abspath(__file__))
USERPROFILE = os.environ.get("USERPROFILE", "")
APPDATA = os.environ.get("APPDATA", "")
SWITCHER_DIR = os.path.join(USERPROFILE, ".gemini", "antigravity-switcher")
LOG_FILE = os.path.join(SWITCHER_DIR, "autopilot.log")
DEVTOOLS_PORT_FILE = os.path.join(APPDATA, "Antigravity", "DevToolsActivePort")
LANG_SERVER_LOG = os.path.join(APPDATA, "Antigravity", "logs", "language_server.log")
ENROLL_LOCK_FILE = os.path.join(SWITCHER_DIR, "enrolling.lock")

# Import core switcher functions
try:
    from antigravity_switcher import switcher as agy_switcher
except ImportError:
    try:
        import switcher as agy_switcher
    except ImportError:
        sys.path.insert(0, APP_DIR)
        import switcher as agy_switcher

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{now}] {msg}"
    print(entry)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass

def show_toast(title, message):
    try:
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$xml = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>{title}</text>
            <text>{message}</text>
        </binding>
    </visual>
</toast>
"@

$doc = [Windows.Data.Xml.Dom.XmlDocument]::new()
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
$appId = 'Antigravity'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
"""
        encoded = base64.b64encode(ps_script.encode('utf-16le')).decode('ascii')
        DETACHED_FLAGS = 0x00000008 | 0x00000200
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            creationflags=DETACHED_FLAGS,
            close_fds=True
        )
    except Exception as e:
        log(f"Gagal mengirim notifikasi toast: {e}")

def is_antigravity_running():
    try:
        out = os.popen('tasklist /FI "IMAGENAME eq Antigravity.exe"').read()
        return "Antigravity.exe" in out
    except Exception:
        return False

def check_log_for_rate_limit(last_pos):
    if not os.path.exists(LANG_SERVER_LOG):
        return False, 0
    try:
        size = os.path.getsize(LANG_SERVER_LOG)
        if size < last_pos:
            last_pos = 0 # log rotated
        with open(LANG_SERVER_LOG, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(last_pos)
            new_lines = f.read()
            new_pos = f.tell()
            if "RESOURCE_EXHAUSTED" in new_lines or "429 Too Many Requests" in new_lines or "quota exceeded" in new_lines.lower():
                return True, new_pos
            return False, new_pos
    except Exception:
        return False, last_pos

def auto_resume_via_cdp():
    log("Mencoba auto-resume via Chrome DevTools Protocol (CDP)...")
    port = None
    for _ in range(12):
        if os.path.exists(DEVTOOLS_PORT_FILE):
            try:
                lines = open(DEVTOOLS_PORT_FILE).read().splitlines()
                if lines and lines[0].isdigit():
                    port = int(lines[0])
                    break
            except Exception:
                pass
        time.sleep(1)
        
    if not port:
        log("Gagal: DevToolsActivePort tidak ditemukan.")
        return False

    try:
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=4).read().decode("utf-8"))
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page:
            log("Gagal: Target chat page tidak ditemukan di CDP.")
            return False

        ws_url = page["webSocketDebuggerUrl"]
        path = ws_url.split(f":{port}")[1]

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect(("127.0.0.1", port))
        handshake = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        s.sendall(handshake.encode())
        s.recv(1024)

        js = """
        (() => {
            const allButtons = Array.from(document.querySelectorAll('button'));
            // 1. Try to find and click Retry button
            const retryBtn = allButtons.find(b => {
                const txt = (b.innerText || '').toLowerCase();
                const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                return txt.includes('retry') || txt.includes('coba lagi') || aria.includes('retry') || aria.includes('regenerate');
            });
            if (retryBtn) {
                retryBtn.click();
                return 'CLICKED_RETRY';
            }

            // 2. Try to send 'Lanjutkan' into input
            const input = document.querySelector('textarea, [contenteditable="true"]');
            if (input) {
                if (input.tagName === 'TEXTAREA') {
                    input.value = 'Lanjutkan tugas sebelumnya';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                } else {
                    input.innerText = 'Lanjutkan tugas sebelumnya';
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
                const sendBtn = allButtons.find(b => {
                    const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                    return aria.includes('send') || aria.includes('kirim') || aria.includes('submit');
                });
                if (sendBtn) {
                    sendBtn.click();
                    return 'CLICKED_SEND_BUTTON';
                } else {
                    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
                    return 'DISPATCHED_ENTER';
                }
            }
            return 'NO_TARGET_FOUND';
        })()
        """
        msg = json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": js}}).encode()
        frame = bytearray([0x81, 0x80 | 126, (len(msg) >> 8) & 0xff, len(msg) & 0xff, 0, 0, 0, 0]) + msg
        s.sendall(frame)
        res_raw = s.recv(4096)
        s.close()

        idx = 4 if res_raw[1] & 0x7f == 126 else 2
        payload = res_raw[idx:].decode(errors="ignore")
        log(f"Hasil eksekusi CDP Auto-Resume: {payload[:200]}")
        return True
    except Exception as e:
        log(f"Error CDP: {e}")
        return False

def select_best_account(current_email):
    accounts = agy_switcher.get_saved_accounts()
    candidates = [a for a in accounts if a != current_email]
    if not candidates:
        return None
        
    scored = []
    for acc in candidates:
        q = agy_switcher.fetch_quota_summary(acc)
        score = agy_switcher.score_account(q)
        if score > -90000:
            scored.append((score, acc))
                
    if not scored:
        return candidates[0]
        
    scored.sort(key=lambda x: x[0], reverse=True)
    best_acc = scored[0][1]
    log(f"Akun terbaik terpilih: [{best_acc}] (Score: {scored[0][0]:.0f})")
    return best_acc

def main_loop():
    log("=== AGY AUTO-PILOT OVERNIGHT DAEMON STARTED ===")
    log("Memantau kuota Antigravity setiap 20 detik...")
    show_toast("Antigravity Auto-Pilot", "Auto-Pilot Aktif! Memantau kuota di latar belakang.")
    
    last_log_pos = 0
    if os.path.exists(LANG_SERVER_LOG):
        last_log_pos = os.path.getsize(LANG_SERVER_LOG)

    while True:
        try:
            time.sleep(20)
            if not is_antigravity_running():
                continue

            # Jangan lakukan auto-switch jika user sedang mendaftarkan akun baru
            if os.path.exists(ENROLL_LOCK_FILE):
                log("Sesi enrollment akun baru sedang berlangsung. Auto-Pilot siaga...")
                continue

            current_email = None
            if os.path.exists(agy_switcher.ACTIVE_FILE):
                try:
                    with open(agy_switcher.ACTIVE_FILE, "r") as f:
                        current_email = f.read().strip()
                except Exception:
                    pass

            if not current_email:
                # Belum ada akun aktif terdaftar (misal sesi login baru belum selesai)
                continue

            # Check 1: Error in language_server.log
            is_exhausted_in_log, last_log_pos = check_log_for_rate_limit(last_log_pos)
            
            # Check 2: Quota summary API
            is_exhausted_in_quota = False
            if current_email:
                q = agy_switcher.fetch_quota_summary(current_email)
                if q and "error" not in q:
                    gemini_q = q.get("gemini", {})
                    h5_obj = gemini_q.get("5h", {})
                    h5 = h5_obj.get("remaining", 100.0) if isinstance(h5_obj, dict) else float(h5_obj)
                    wk_obj = gemini_q.get("weekly", {})
                    weekly = wk_obj.get("remaining", 100.0) if isinstance(wk_obj, dict) else float(wk_obj)
                    if h5 <= 1.0 or weekly <= 1.0:
                        is_exhausted_in_quota = True

            if is_exhausted_in_log or is_exhausted_in_quota:
                reason = "Error Log 429/Exhausted" if is_exhausted_in_log else "Quota 5h/Weekly Habis"
                log(f"⚠️ LIMIT TERDETEKSI ({reason}) pada [{current_email}]!")

                best_acc = select_best_account(current_email)
                if not best_acc:
                    log("Tidak ada akun alternatif dengan kuota tersisa. Menunggu 5 menit...")
                    show_toast("Antigravity Auto-Pilot", "⚠️ Semua akun telah mencapai batas kuota!")
                    time.sleep(300)
                    continue

                log(f"🚀 Memulai Auto-Switch ke [{best_acc}]...")
                show_toast("Antigravity Auto-Pilot", f"⚠️ Limit terdeteksi pada {current_email}.\n🚀 Otomatis beralih ke {best_acc}...")
                
                agy_switcher.switch_to_account(best_acc)

                log("Menunggu Antigravity siap (8 detik)...")
                time.sleep(8)

                # Trigger auto-resume
                resumed = auto_resume_via_cdp()
                if resumed:
                    show_toast("Antigravity Auto-Pilot", f"✅ Beralih ke {best_acc} sukses!\nTugas coding telah dilanjutkan otomatis.")
                
                # Update last log position
                if os.path.exists(LANG_SERVER_LOG):
                    last_log_pos = os.path.getsize(LANG_SERVER_LOG)

                # Cooldown 90 detik agar tidak double switch
                log("Selesai. Cooling down 90 detik...")
                time.sleep(90)

        except Exception as e:
            log(f"Error loop daemon: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main_loop()
