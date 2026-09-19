# Contributing to Antigravity Control Center

Thank you for your interest in contributing to **Antigravity Control Center**! We welcome bug fixes, performance optimizations, documentation improvements, and platform adapters.

---

## 1. Development Setup

### Prerequisites
- Python 3.10, 3.11, or 3.12 (64-bit recommended)
- Git
- Google Antigravity installed locally

### Clone & Virtual Environment
```bash
git clone https://github.com/demusraph/antigravity-control-center.git
cd antigravity-control-center

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### Running Locally
- **GUI Application**:
  ```bash
  python main.py
  # or
  python -m antigravity_switcher
  ```
- **Headless CLI**:
  ```bash
  python main.py --cli
  ```
- **Background Daemon**:
  ```bash
  python main.py --daemon
  ```

---

## 2. Project Architecture & Standards

- **Source Layout**: All application logic resides in `src/antigravity_switcher/`:
  - `app.py`: PyQt5 GUI window, QWebEngine quota radar, and system tray.
  - `daemon.py`: Autonomous rate-limit watchdog and CDP auto-resume agent.
  - `switcher.py`: Win32 Credential Manager API wrapper and CLI commands.
- **UI Design System**:
  - Dark Obsidian color palette (`#101010` base, `#191919` card, `#222222` border, `#2B7FFF` accent).
  - Strict **zero-emoji** rule for all native buttons and production headers (SVG icons only).
  - Micro-interactions and smooth hover states.
- **Security Discipline**:
  - Never commit raw tokens, test accounts, `.log`, or `.pid` files.
  - Keep credential strings obfuscated at runtime to prevent false-positive secret scans.

---

## 3. Pull Request Guidelines

1. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Ensure your changes run cleanly without unhandled exceptions.
3. Keep pull requests atomic and focused on a single capability or fix.
4. Follow conventional commit messages:
   - `feat: add macOS Keychain credential adapter`
   - `fix: handle edge case when DevTools port file is temporarily locked`
   - `docs: clarify SmartScreen unblock instructions`
5. Submit the PR using the provided PR template.
