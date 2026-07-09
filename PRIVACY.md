# Privacy Policy - Grabline & Grabline Connect

*Last updated: 2026-07-08*

Grabline (the desktop app) and Grabline Connect (the browser extension) are
open-source software published under AGPL-3.0. Their privacy model is simple:

**Nothing you do is collected, stored remotely, or transmitted to us or to
any third party. There is no telemetry, no analytics, no accounts, and no
advertising - in any part of the project, ever.**

## What stays on your device

- Your download queue, history, and settings live in a local SQLite database
  under your user profile. Delete the folder and they are gone.
- URLs you hand off from the browser travel over Native Messaging (a local
  stdio pipe between your browser and the app) into that same local database.
  No network service, port, or server is involved.

## What touches the network - only at your request

- Downloading a URL contacts that URL's server (and, for Smart Engine sites,
  the pages yt-dlp needs to resolve it). This happens only when you start a
  download.
- FFmpeg, when you install it from Settings, is fetched over HTTPS from its
  official build hosts and verified against pinned SHA-256 checksums.
- The optional **"Use my browser session"** feature reads your own browser's
  cookies for a download, keeps them in memory only, and never writes or
  transmits them. It is off by default.

## The extension specifically

- The per-tab media list (what the page's own network traffic loaded) is kept
  in `storage.session` and is discarded when the tab closes. It never leaves
  the browser except as a URL you explicitly hand to your local app.
- The extension makes no requests of its own, injects no remote code, and
  talks to exactly one destination: the Grabline app on your machine.

## Questions

Open an issue: https://github.com/Gr33nOps/Grabline/issues
