# Grabline UI Redesign — Figma Design Brief

This is the complete inventory of every screen, dialog, menu, and state in
Grabline **v1.13.0**, written for a full visual redesign in Figma. Everything
listed here exists and works today; the redesign changes how it *looks and is
laid out*, not what it does. Hand this whole document to your Figma AI /
designer. When the frames come back, give them to me and I'll rebuild the Qt UI
and the extension to match.

---

## 0. What Grabline is (context in one paragraph)

Grabline is a free, open-source, cross-platform (Windows / macOS / Linux)
download manager — the modern answer to IDM. It's a **desktop app** (Python +
PySide6/Qt Widgets) plus a companion **MV3 browser extension "Grabline
Connect."** It downloads plain files (accelerated, multi-connection), video from
1000+ sites (yt-dlp), HLS/DASH streams, torrents (libtorrent), and from
clouds/servers (SFTP/FTP/S3/WebDAV + Drive/Dropbox/OneDrive/Nextcloud share
links). It has a queue manager, a scheduler, a security layer, a live dashboard,
and a network/proxy layer. **Brand values to express visually:** fast, honest,
private (no ads, no telemetry, no paid tier), and respectful — *it advises, it
never blocks or nags.*

---

## 1. HARD TECHNICAL CONSTRAINTS — read first, these shape everything

The desktop app is **Qt Widgets (PySide6)** — not HTML/CSS, not Qt Quick/QML.
Design within these limits or the redesign can't ship:

1. **Two themes, auto-following the OS.** Design every screen in **light AND
   dark**. There's a manual override (System / Light / Dark). Deliver both
   palettes.
2. **Native window chrome.** The OS draws the title bar + window buttons
   (traffic lights / min-max-close). Design the content area below it, not a
   custom title bar. An in-app top toolbar/header is fine.
3. **Standard widgets only.** Building blocks available: buttons, checkboxes,
   radios, text fields, dropdowns (combo box), number steppers (spin box),
   sliders, tabs, tables/lists/trees, progress bars, tooltips, menu bar +
   right-click context menus, modal dialogs, titled bordered sections (group
   box), a system-tray icon + menu, and toasts. **No bespoke animated
   components; no heavy shadows/blur/glass.** Flat cards, 1px borders, and one
   accent color are the palette.
4. **Custom-painted charts are allowed but must stay simple 2D.** We hand-paint
   a toolbar **sparkline** and dashboard **line/area graphs**. You can restyle
   them (colors, line weight, fill opacity, subtle gridlines) but keep them flat
   2D — no 3D, no GPU gradients.
5. **Density matters.** The main screen is a **table of downloads** that can hold
   hundreds of rows. Rows stay compact and legible — think "data grid," not "big
   media cards." A comfortable/compact density toggle is welcome.
6. **Icons:** deliver a consistent, monochrome-friendly **SVG icon set** (tints
   per theme). Needed: add-url, add-torrent, add-cloud, pause, resume, cancel,
   remove, open-file, open-folder, settings, dashboard, inspect, security,
   queue, search, copy, and **type icons** (video, audio, image, document,
   archive, program, game, torrent, cloud) + **status icons** (downloading,
   queued, paused, completed, failed, cancelled).
7. **One accent color.** Current app + marketing lean green (`~#2ea043`). Evolve
   it if you like, but pick ONE confident accent and give exact light+dark hex
   with AA contrast.
8. **Fonts:** default to the system UI sans (Segoe UI / SF / system). A custom
   font must be OFL/free (we bundle it). A **monospace** is used for hashes,
   HTTP headers, and reports — specify one.
9. **Responsive:** main window resizes from ~880×440 to maximized; tables/panels
   must reflow. Dialogs look right from ~460px wide upward.
10. **Everything ships in the binary** — no web fonts, no remote assets, no
    telemetry/analytics pixels.

**Deliverables I need back (see §7):** a design-token sheet, the icon set, frames
for every screen in §3–§4 in both themes, and the component states in §5.

---

## 2. DESIGN SYSTEM to define

- **Color tokens (light + dark):** window bg, surface/base bg, alternating-row
  bg, border, primary text, secondary/muted text, accent, accent-hover,
  accent-on (text on accent). **Status colors:** downloading, queued, paused,
  completed (success/green), failed (error/red), cancelled (muted). **Advisory
  levels** (security): OK green, Caution amber `#d29922`, Warning red `#cf222e`.
- **Graph series colors** (must read in both themes): download `#2ea043`, upload
  `#db6d28`, network-down `#388bfd`, network-up `#a371f7`, CPU `#db3c3c`, disk
  `#9e6a03`.
- **Type scale:** H1 (window/section title), H2 (dialog title), Body,
  Small/caption, Mono (hashes, headers). Sizes + weights.
- **Spacing** (8pt grid recommended), **corner radius** (button/input/card),
  **border weights**, **elevation** (kept subtle — borders over shadows).
- **Components to spec (with all states):** button (primary / secondary / ghost
  / destructive), input, dropdown, checkbox, radio, number-stepper, slider,
  tab bar / segmented control, **table row** (default / hover / selected /
  alternating), progress bar (determinate + indeterminate), **status pill**,
  **tag/label chip**, **stat tile** (big number + caption), **graph card**,
  tooltip, menu item, group box / titled section, empty-state, toast.

---

## 3. DESKTOP APP — every screen

### 3.1 Main window (home) — most important
- **Top toolbar/header:** primary actions — Add URL, Import Links, Pause,
  Resume, Cancel, Remove, Open Folder, Settings — plus a **search box**
  ("Search downloads…") and a **live speed sparkline** with a numeric readout
  ("3.2 MB/s"). Suggest grouping: add-actions left, search + global status right.
- **Menu (File bar or a hamburger/overflow — your choice, all must be
  reachable):** Add URL…, Add Torrent File…, Add Cloud Download…, Import Links…,
  Grab Site…, Create Torrent…, Search Torrents…, **Dashboard…**, **Inspect
  URL…**, **Queue Manager…**, Clear Completed, Find Duplicate Files…, Browser
  Setup…, Check for Updates…, Import List…, Export List…, Quit. (A command
  palette or left nav is a welcome modern take.)
- **Filter tabs / segmented control:** All · Active · Completed · Failed.
- **Downloads table** — the core surface. Columns today: **Name, Size, Progress
  (inline bar), Speed, Status.** Each row shows a **type icon** (video/audio/
  image/document/archive/program/game/torrent/cloud), name, size, an inline
  progress bar with %, current speed, and a **status pill** (Downloading /
  Queued / Paused / Completed / Failed / Cancelled). Multi-select (Ctrl/Shift) —
  design the selected/multi-selected row. We also have per-row **queue name,
  tags/labels, ETA** available (today mostly in menus) — a redesign could add
  columns or a **detail drawer**.
- **Empty state:** friendly first-run prompt ("Paste a link, drop a file, or
  install the browser button").
- **Row right-click context menu** (long — group with dividers): Open file, Open
  folder, Copy URL, **Copy magnet link** (torrents), Download again, Convert to
  GIF… (video), Limit speed…, Connections…, Copy SHA-256, Verify checksum…,
  **Security check…**, Inspect…, Extract here / Preview archive… (archives),
  **Move to ▸** (favorite folders), Tags & notes…, **Queue ▸** (Default + each
  named queue, checkable), Start after… (job dependency), Start at… (download
  later), Move in queue ▸ (Top/Up/Down/Bottom), Remove from list. Consider a
  per-row "⋯" overflow button as an alternative to right-click.
- **Status bar / toasts:** transient messages ("Extracting…", "Queued 3 files",
  "Downloaded to…"). Keep the bar or replace with a toast system.
- **Opportunity — detail drawer:** a right-side or bottom panel for the selected
  download: thumbnail, full name, URL, destination, all stats, tags/notes, a
  per-download mini speed graph, its queue. All data exists.

### 3.2 Add-URL flow
- A small input (paste a URL; also used for magnet + cloud URLs) — modal or an
  inline top bar. After resolving it branches to: Quality panel (3.3), Playlist
  panel (3.4), Gallery panel (3.5), Add-torrent (3.7), Add-cloud/folder (3.9),
  or just queues (plain files).
- **Advisory pre-download dialogs** (modal, Yes/No, calm "you decide" tone):
  duplicate ("already downloaded — again?"), insecure HTTP ("unencrypted —
  anyway?"), Safe Browsing hit ("flagged as MALWARE — anyway?").

### 3.3 Quality panel (video/audio)
- **Media header:** thumbnail 160×90, title, "uploader • duration."
- **Quality list** (radio/list): Best, 1080p, 720p, 360p (each with a size
  estimate "~84 MB"), plus audio-only **MP3 / M4A / FLAC**.
- **Subtitles row:** language dropdown + "Embed" checkbox.
- **Extras row:** checkboxes Save thumbnail, Save metadata, Chapters (default
  on), and a **SponsorBlock** dropdown (Off / Mark segments / Remove sponsor).
- **Clip (optional):** start + end time inputs ("1:20" / "2:45") with inline
  validation error text.
- Buttons: **Download** / Cancel.

### 3.4 Playlist panel
- Header (title, uploader); a **checkbox list** of entries (title + duration)
  with a preselect cap; select-all/none; one **quality dropdown** for the batch;
  Download selected / Cancel.

### 3.5 Gallery panel (page images)
- A **thumbnail grid** with per-image checkboxes; select-all/none; download
  checked.

### 3.6 Link panel (import links)
- A checkbox list/table of links (URL + type); select-all + filter; queue.

### 3.7 Torrent dialogs
- **Add Torrent:** display name; "Save to" folder (Browse); a **checkbox file
  tree** (path + size) to choose files; checkboxes "Sequential download
  (stream-friendly)" and "Fetch first & last pieces early." Download / Cancel.
  (Magnets show no file tree until metadata arrives — design that pre-metadata
  state, e.g. an indeterminate "resolving…".)
- **Create Torrent:** "Share" file/folder (File… / Folder… pickers); trackers
  text area; web-seeds text area; comment field; "Private" toggle. Create… /
  Cancel.

### 3.8 Queue Manager
- **List of named queues**, each with traits inline ("Movies (sequential,
  22:00-07:00, video, after 'Work')"). Buttons: Add… / Edit… / Up / Down
  (reorder = priority) / Delete / Close.
- **Queue editor** sub-dialog: name; "Downloads at once" stepper (0 = global,
  1 = sequential, N = parallel); "Paused" checkbox; schedule row ("Only between
  HH:MM and HH:MM"); Category dropdown (auto-assign new downloads of that type);
  "Wait for queue" dropdown (dependency; cycles are refused). OK / Cancel.

### 3.9 Cloud dialogs
- **Cloud accounts manager:** intro ("Saved logins for SFTP/FTP/WebDAV/S3;
  secrets in the OS keychain"); a **list of accounts** ("[sftp] user@host");
  Add… / Remove / Close.
  - **Account editor:** Service dropdown (sftp/ftp/ftps/scp/webdav/s3), Host,
    Username, Port, Secret (password field), Key file (optional), Label.
- **Cloud folder picker:** header ("N files in <url>"); **checkbox file tree**
  (name + size); Download / Cancel.
- **Add-cloud prompt:** one input ("sftp:// ftp:// s3:// webdav://, or a
  Drive/Dropbox share link").

### 3.10 Dashboard — the data-viz showpiece
Live monitoring. Top→bottom today:
- **Speed stat tiles** (big number + caption): Current, Average, Peak, ETA,
  Active (count).
- **Total tiles:** Downloaded today, This week, This month, Lifetime, Files.
- **Grid of 5 graphs** (~1 min scrolling history): Download, Upload, Network
  (system: two series down+up), CPU (0–100%), Disk (system).
- **VPN status line** ("🔒 VPN active on wg0" / "VPN: not detected").
- **Two tables side by side:** Per-server (host, downloaded, files) and
  Per-category (category, downloaded, files).
→ Biggest opportunity for a beautiful, implementable data-viz treatment (tiles,
2D charts, tables).

### 3.11 Inspector
- A live URL probe shown as a **report in sections**: Overview (URL, final URL,
  status, response time, MIME, size); Server & location (IP, reverse DNS, CDN,
  server — with the note "no geo lookup; the address never leaves your
  machine"); TLS/SSL (protocol, cipher, subject, issuer, validity); Redirect
  chain; Mirrors; Checksum (SHA-256); Cookies; HTTP headers. **Copy** button.
  Today it's a monospace text blob — redesign into labeled key-value sections /
  accordions.

### 3.12 Security dialog
- **Verdict banner** (color + label): "Looks OK" green / "Caution" amber /
  "Warning" red.
- **Advisory note:** "This is advice, not a verdict — a flagged file is kept and
  stays usable. Antivirus false positives are common."
- **Findings list** (bullets); a **VirusTotal** line ("3 malicious / 1
  suspicious of 70 engines" + link); a **checksums block** (MD5, SHA-1, SHA-256,
  SHA-512, CRC32). Copy button.

### 3.13 Archive dialogs
- **Preview archive:** header ("N files, total size"); **checkbox file list**
  (name + size); Extract / Cancel.
- **Password prompt:** a password field (encrypted archives).
- **Scan-advisory prompt:** "X flagged this archive. Antivirus false positives
  are common. Extract it anyway?" Yes / No.
- **Duplicate finder:** sets of byte-identical files grouped, extras pre-checked
  for deletion (one kept). Delete-checked / Cancel.

### 3.14 GIF dialog
- Compact form: start / end / fps / width / quality + Convert (video→GIF).

### 3.15 Settings — tabbed (10 tabs)
Design a clean tabbed OR left-nav settings surface with section headers + help
text (a settings search is welcome). Keep every control; improve grouping.
- **General:** Download folder (Browse), "Sort into categories," Theme dropdown,
  Proxy field (http/https/socks5/socks4), clipboard-watch, autostart,
  update-check.
- **Files:** Favorite folders (multiline), Rename rules (multiline
  "find -> replace").
- **Downloads:** Simultaneous downloads (stepper), Connections per download
  (1–128), Speed limit (KB/s, "Unlimited" at 0), Speed schedule (full-speed
  window HH:MM–HH:MM), Download-times window, Reconnect/auto-retry (checkbox +
  "N times / Forever"), Days-of-week checkboxes (Mon–Sun), "Pause on battery,"
  "Wait for internet."
- **Network:** proxy note, **VPN status line**, **Automatic throttle** group
  (checkbox + "slow down to KB/s" + "when others use over KB/s"), **Per-host
  speed limits** (multiline "host = KB/s").
- **When finished:** notify, open-folder, auto-extract archives, virus-scan-
  before-extract, archive passwords (multiline), "when queue empties" dropdown
  (nothing/quit/sleep/hibernate/shutdown/lock), completion sound (checkbox +
  file + Browse), run-command field.
- **Torrents:** listen port, DHT/UPnP/NAT-PMP checkboxes, seeding (checkbox +
  ratio), upload limit, default sequential, torrent save folder, search URL
  template, RSS feeds (multiline), RSS interval.
- **Cloud:** intro, "Manage saved logins…" button, keychain note, unsupported
  note (Mega/Proton/iCloud).
- **Security:** advisory note, "Security-check every download," "Warn on
  unencrypted HTTP," VirusTotal API key (password), Safe Browsing API key
  (password), "TLS always validated" note.
- **Browser & YouTube:** browser-session group (checkbox + browser dropdown +
  an honest consent paragraph), a "Browser extension" pairing group.
- **Tools:** FFmpeg status + "Install FFmpeg" button.

### 3.16 Setup / browser-pairing wizard
- First-run stepped wizard to install + pair the extension, covering the 7
  browsers: Chrome, Firefox, Edge, Brave, Vivaldi, Opera, Arc.

### 3.17 System tray
- A **monochrome-friendly tray icon** + right-click menu (Show, quick actions,
  Quit) + **toast notifications** ("Download complete", "Download with
  Grabline?"). Design the icon and the notification look.

### 3.18 App icon + branding
- New **app icon** (16–256px, must read at 16px in tray/taskbar) + a small
  in-app logo/wordmark for the header/about.

---

## 4. BROWSER EXTENSION — "Grabline Connect"

MV3 for Chrome/Firefox/Edge/Brave/Vivaldi/Opera/Arc.

### 4.1 Toolbar popup (`popup.html`, ~320–400px)
- Connection status ("Connected to Grabline" / "App not running — open
  Grabline"); quick actions (Download this page's media / links / images); a
  short list of media sniffed on the current tab; a link to open the app. Both
  themes.

### 4.2 In-page hover ⬇ button (injected)
- A small **download button** on hover over videos/thumbnails (YouTube, YT
  Music, SoundCloud, Vimeo, X). Click can open a tiny **quality menu** (Best /
  1080p / 720p / 480p / MP3 / M4A / FLAC / "More options…"). Design idle/hover
  button + the mini popover. Unobtrusive; must not clash with host sites.

### 4.3 In-page progress pill
- A floating **pill stack** (bottom corner) tracking downloads started from the
  page: name + % + speed, live. States: in-progress / done / failed.

### 4.4 Right-click menu entries
- Native browser items (browser-styled — just confirm labels + an optional 16px
  icon): "Download with Grabline", "Download all links/images/videos with
  Grabline", "Download selected links & media with Grabline".

### 4.5 Gallery / link in-page overlays
- Selection overlays for grab-all-images (thumbnail grid) / grab-all-links
  (list), with checkboxes.

### 4.6 Extension icon
- Toolbar icon (16/32/48/128) on-brand, with an "active / has media" badge
  state.

---

## 5. STATES to cover across everything

For each interactive component: **default, hover, pressed/active, focused
(keyboard), disabled, error.** Specifically:
- **Download row:** queued, downloading, paused, completed, failed, cancelled,
  selected, multi-selected.
- **Progress bars:** determinate (with %) and indeterminate (magnet resolving /
  metadata loading).
- **Buttons:** primary / secondary / ghost / destructive.
- **Inputs:** normal / focused / error / disabled / placeholder.
- **Advisory dialogs:** amber/red but **never alarming red-alert**; always offer
  "do it anyway." Core value: **Grabline advises, never blocks or nags.**
- **Empty states:** no downloads, no queues, no search results, no VPN, empty
  dashboard (no history yet).
- **Loading states:** resolving a URL, hashing, scanning, probing.

---

## 6. BRAND & TONE

- **Honest, calm, fast.** No dark patterns, no fake urgency, no "PRO" upsells
  (there is no paid tier). Warnings inform, they don't scare.
- **Private & open-source:** the UI can quietly signal "no telemetry" (e.g. in
  the inspector/security copy) without over-badging.
- **Cross-platform native feel:** at home on Windows, macOS, and Linux — modern-
  neutral, not iOS- or Windows-specific.
- One confident accent (currently green).

---

## 7. WHAT TO HAND BACK TO ME

1. **Design tokens** (JSON or a Figma variables sheet): all colors (light +
   dark), spacing, radii, type scale, borders — I'll translate to a Qt palette/
   stylesheet.
2. **Icon set** as tintable SVGs.
3. **Frames** for every screen in §3 (app) and §4 (extension), in **both
   themes**, with the states in §5.
4. **A components page** (buttons, inputs, table row, tabs, dialog shell, status
   pill, tag chip, stat tile, graph card, menu, empty-state, toast).
5. **App icon + extension icon** in the required sizes.

When you send frames, I'll map each to its Qt widget/dialog (and the extension's
HTML/CSS) and reimplement styling + layout to match, keeping all behavior wired.
Anything not doable in Qt Widgets I'll flag, and we'll pick the closest faithful
equivalent together.

---

## Appendix A — full screen checklist (miss none)

**Desktop:** main window (+ empty state, + row context menu, + optional detail
drawer) · Add-URL prompt · Quality panel · Playlist panel · Gallery panel · Link
panel · Add-Torrent dialog · Create-Torrent dialog · Queue Manager + Queue
editor · Cloud accounts + Account editor + Cloud folder picker + Add-cloud
prompt · Dashboard · Inspector · Security dialog · Archive preview + Password
prompt + Scan-advisory prompt + Duplicate finder · GIF dialog · Settings (10
tabs) · Setup wizard · Tray icon + menu + toast · App icon.

**Extension:** toolbar popup · in-page hover ⬇ button + mini quality menu ·
progress pill · right-click menu entries (labels) · gallery/link in-page
overlays · toolbar icon (+ badge).

## Appendix B — current palette (evolve, needn't keep)

- Accent green `~#2ea043`. Security: OK `#2ea043`, Caution `#d29922`, Warning
  `#cf222e`. Graphs: download `#2ea043`, upload `#db6d28`, net-down `#388bfd`,
  net-up `#a371f7`, cpu `#db3c3c`, disk `#9e6a03`.
- Two themes required (light + dark), OS-following with a manual override
  (System / Light / Dark).

## Appendix C — for the Figma AI: recommended frame set

Make an **8pt grid**, a **variables/tokens** collection (light + dark modes),
then these artboards (all in both themes): `App / Main — populated`, `App /
Main — empty`, `App / Main — row menu open`, `App / Add URL`, `App / Quality`,
`App / Playlist`, `App / Gallery`, `App / Links`, `App / Add Torrent`,
`App / Create Torrent`, `App / Queues`, `App / Queue Editor`, `App / Cloud
Accounts`, `App / Cloud Folder`, `App / Dashboard`, `App / Inspector`,
`App / Security`, `App / Archive Preview`, `App / Duplicates`, `App / GIF`,
`App / Settings — General` (+ one frame per tab, or one frame with the tab rail
and 2–3 representative tabs), `App / Setup Wizard`, `App / Tray + Toast`,
`Ext / Popup`, `Ext / Hover Button + Quality`, `Ext / Progress Pill`,
`Ext / Gallery Overlay`. Plus `System / Tokens`, `System / Components`,
`Brand / App Icon`, `Brand / Extension Icon`.
