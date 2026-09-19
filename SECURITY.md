# Security Policy & Architecture

The security and privacy of user credentials is the core design tenet of **Antigravity Control Center**.

---

## 1. Supported Versions

Security fixes and hardening patches are applied to the latest release on `main`.

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## 2. Local-First Security Architecture

### Zero Remote Storage & Zero Telemetry
- **No Cloud Backend**: Antigravity Control Center does not maintain or connect to any remote server, database, or analytics collector.
- **No Telemetry**: No telemetry, tracking pings, or analytics are embedded in the binary or source code.
- **Local SQLite State**: Hot-swapped session profiles and account records are stored strictly on the local machine at:
  ```
  %USERPROFILE%\.gemini\antigravity-switcher\
  ```

### Windows DPAPI & Credential Manager
- Tokens for Antigravity are managed exclusively via the native Windows Credential Manager Win32 API (`advapi32.dll:CredWriteW` and `CredReadW`).
- Windows stores these blobs encrypted under your current Windows user logon credentials using **Data Protection API (DPAPI)**.
- Other Windows users on the same machine cannot decrypt or access your Antigravity tokens.

### Chrome DevTools Protocol (CDP) Isolation
- The Auto-Pilot daemon communicates with the local Antigravity IDE strictly over loopback (`127.0.0.1`) on a dynamic ephemeral port read directly from `%APPDATA%\Antigravity\DevToolsActivePort`.
- No remote DevTools interfaces are exposed to the external network.

---

## 3. Reporting a Vulnerability

If you discover a security vulnerability or credential handling flaw:

1. **Do NOT open a public issue.**
2. Report the vulnerability privately via **[GitHub Private Vulnerability Reporting](https://github.com/demusraph/antigravity-control-center/security/advisories/new)**.
3. Include detailed reproduction steps, target component (`core`, `daemon`, or `gui`), and potential impact.
4. You will receive an initial response within **48 hours**, followed by a timeline for a patch release.
