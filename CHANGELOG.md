# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.4.0] - 2026-10-17

### Added
- **Headless 24/7 Launcher (`Launch-Daemon.bat`)**: Dedicated batch script to run the Auto-Pilot quota monitoring daemon on semi-headless Mini PCs and servers with zero GUI overhead and zero pip dependencies.
- **Interactive Enrollment Session**: CLI (`python main.py --cli` option `+`) now enters an active 5-minute polling loop with real-time feedback, automatically detecting Google OAuth completion and registering new accounts with graceful rollback.
- **Dynamic Enrollment Banner**: Web/Desktop GUI displays a live pulse status banner with instant cancellation (`/api/enroll/cancel`) while awaiting Antigravity sign-in.

### Fixed
- **Fast Offline JWT `id_token` Extraction**: Replaced fragile, blocking Google UserInfo HTTP API requests (5s timeout) with 0ms offline Base64URL JWT payload extraction directly from the modern `gemini:antigravity` credential blob.
- **Modern Session Cache Multi-Layer Wipe**: Cleans `jetski.onboarding.lastLoginUsername` from `app_storage.json`, resets onboarding sentinels in `state.vscdb`, and removes Chromium `Cookies` / `Cookies-journal` so Antigravity opens in a true clean-slate login state.
- **Process Lock Prevention**: Upgraded `stop_antigravity()` to use tree-kill (`taskkill /F /T`) and process polling to ensure all worker/GPU processes release file locks before deleting session cookies.
- **Auto-Pilot Daemon Enrollment Guard (`enrolling.lock`)**: Implemented mutual exclusion lockfile preventing the background daemon from erroneously triggering an auto-swap or killing the login session during account enrollment.

---

## [1.3.1] - 2026-09-10

### Added
- **Interactive 2D Top-Down Pixel Game "Agents Office" Headquarters**: Transformed Tab 2 into a high-craft 16-bit retro living simulation where AI agents physically inhabit the 4 architectural wings (Executive Suite, Engineering Bay, Intelligence Lounge, and SecOps Boardroom) on a 640x640 pixel floor plan.
- **Razor-Sharp Pixel Texture Rendering**: Integrated `/assets/office_floor_pixel.png` with CSS `image-rendering: pixelated; crisp-edges;` to ensure lossless visual fidelity on all display DPI scales.
- **Custom Pixel Character Sprites**: Vector-crisp pixel SVG character sprites with specialized uniforms and accessories for each department (navy suit & red tie for Executive; purple hoodie & headphones for Engineering; emerald vest & glasses for Intelligence; tactical vest & headset for SecOps).
- **Dynamic Activity Bubbles & Monitor Screen Glow**: Real-time activity bubbles above agents (`• [tool_name]` typing for working agents, `• Sync` for conference discussions, `☕ Break` for lounge standby, `❗ Blocked` for errors) plus atmospheric screen flicker desk glow.
- **Interactive Hover HUD & Employee Dossier**: Hovering over any desk character displays an elevated Obsidian tooltip; clicking opens the full Employee Dossier Modal with tool traces and prompt history.
- **Triple-View Switcher**: Instant 1-click toggling between `[ 🎮 Pixel Office ]`, `[ 🏢 Division Cards ]`, and `[ 🌲 DAG Tree ]` with zoom controls (`Fit`, `100%`) and optional CRT scanlines overlay.

---

## [1.2.2] - 2026-09-08

### Fixed
- **Anti-Wrapping Layout Hardening**: Enforced strict `whitespace-nowrap` and `shrink-0` across all Mission Control Toolbar items (Auto-Pilot toggle button, account count badge, quick recommendation action, and navigation tabs), completely eliminating ugly multi-line text wrapping on narrow viewports.
- **Responsive Active Email Truncation**: Added responsive CSS truncation (`truncate max-w-[170px] sm:max-w-[260px] md:max-w-[340px]`) with dynamic `title` tooltip so long email addresses never push neighboring control buttons into awkward line-breaks.
- **Window Geometry Optimization**: Expanded default window proportions from `680x780` to an ergonomic `840x800` (minimum `660x680`) with updated restore fallback geometry and fine-tuned Win32 `HTCAPTION` hit-test boundaries for flawless high-DPI Windows display scaling (125%-150%).

---

## [1.2.1] - 2026-09-08

### Fixed
- **Auto-Pilot Daemon Toggle Lifecycle**: Fixed `NameError` path resolution bug in `set_autopilot_state()` with dynamic entrypoint discovery (`main.py --daemon` / `daemon.py` / `-m antigravity_switcher.daemon`).
- **Realtime Win32 Process Validation**: Replaced naive PID file checks with `kernel32.GetExitCodeProcess == 259 (STILL_ACTIVE)` and automated stale PID cleanup.
- **Headless Stream Guard**: Added fallback redirection for `sys.stdout` and `sys.stderr` to `os.devnull` in `daemon.py` when executed via `pythonw.exe`.
- **Clean Typography & Effect Removal**: Removed ShinyText gradient shimmer animation from the topbar brand name, restoring solid crisp `#FFFFFF` white typography; purged ClickSpark canvas particle engine from the DOM.

---

## [1.2.0] - 2026-09-08

### Added
- **PyQt5 Window Physics Animations**: Implemented `QPropertyAnimation` easing for window maximize (`OutCubic`, 220ms), minimize opacity fade (`InQuad`, 140ms), and tray restore fade-in (`OutQuad`, 160ms) to eliminate abrupt jumping on Windows 11 frameless windows.
- **React Bits Micro-Interactions**: Integrated `SpotlightCard` cursor-following radial glow on account & DAG cards, `DecryptedText` cyber scramble on email initialization, `CountUp` smooth quota number animations, `ButtonSpring` tactile haptics, and `TabAnimatedEnter` view transitions.
- **1:1 Antigravity 2.0 Obsidian Window Frame**: Removed white frameless border artifact with DWM dark mode attribute synchronization (`DWMWA_USE_IMMERSIVE_DARK_MODE`, `DWMWA_WINDOW_CORNER_PREFERENCE`).

---

## [1.1.0] - 2026-09-08

### Added
- **Live Subagent DAG & Execution Trace (`subagent_tracker.py`)**: Real-time hierarchical visualization of active conversation threads: Parent Orchestrator $\rightarrow$ Child Subagents, step telemetry, active tool execution chips, and token burn estimation.
- **MCP Server Matrix & Health Supervisor (`mcp_supervisor.py`)**: Auto-discovery of active local Model Context Protocol (MCP) servers configured in `~/.gemini/config/mcp_config.json`.
- **1-Click MCP JSON-RPC Ping Probe**: Fast non-blocking handshake probe verifying stdio responsiveness and measuring latency in milliseconds.
- **1-Click MCP Process Self-Heal**: Safely resets broken pipes and zombie child processes to clean standby without restarting Antigravity.
- **Explicit Windows AppUserModelID**: Fixed Windows taskbar icon binding (`google.antigravity.controlcenter.pro.v1`) to prevent defaulting to Anaconda/Spyder host icons.

---

## [1.0.0] - 2026-09-08

### Added
- **Zero-Loss Hot Switching**: Swap Antigravity Google accounts in real time without closing the IDE or losing editor tabs and context.
- **Real-Time Quota Radar**: Dual-metric monitoring for Gemini Models (Flash/Pro) and Claude/GPT Models with live progress bars and reset deltas.
- **Autonomous Overnight Auto-Pilot**: Background watchdog daemon monitoring `language_server.log` for 429 / `RESOURCE_EXHAUSTED` events.
- **CDP Auto-Resume Protocol**: Automated task resumption via Chrome DevTools Protocol WebSocket evaluation upon account swap.
- **Native Obsidian Dark UI**: PyQt5 + QWebEngine interface with dark system tokens, zero-emoji SVG typography, and system tray integration.
- **Dual Execution Engine**: Supports interactive GUI, headless terminal CLI (`--cli`), and silent background daemon (`--daemon`).
- **Standalone Windows Distribution**: Pre-compiled standalone Windows x64 binary (`AntigravityControlCenter.exe`) requiring zero Python host installation.
- **GitHub Actions Automated CI/CD**: Automatic PyInstaller compilation and release packaging on tag push (`v*`).

---

## [Unreleased] - Planned for v1.1.0

### Planned
- Cross-platform macOS Keychain adapter (`/usr/bin/security`) for MacBook M-series / Intel support.
- Automated notification sound triggers for quota depletion events.
- Export / import encrypted backup of saved account configurations.
