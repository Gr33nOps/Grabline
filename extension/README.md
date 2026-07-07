# Grabline Connect

The thin browser extension (MV3, one codebase for Firefox/Chrome/Edge).
Arrives in Phase 2 (v1.0) — see the roadmap. Planned layout:

- `content/` — element sniffer + hover ⬇ overlays; `sites/youtube/` isolated module
- `background/` — network sniffer, download interception, Native Messaging client
- `popup/` — per-tab media list
