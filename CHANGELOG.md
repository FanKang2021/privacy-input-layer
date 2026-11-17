# Changelog

## 0.5.0

### Added
- Image file masking (png/jpg/jpeg/bmp/webp): local OCR pixel-mask masked copies
- PDF masking: pypdfium2 render -> OCR pixel-mask -> img2pdf reassemble
  (license-safe, avoids PyMuPDF AGPL); image-based output, text layer lost
- pptx masking/restoring (python-pptx, paragraphs + tables)
- OpenDocument odt/ods/odp masking/restoring (content.xml text nodes, format preserved)
- macOS clipboard image masking (NSPasteboard TIFF/PNG -> mask -> PNG writeback)

### Notes
- Legacy binary doc/xls/ppt unsupported with save-as guidance; image/PDF restore
  errors by design (irreversible); Linux clipboard images unsupported (roadmap)

## 0.4.14

### Fixed
- One-time config migration: pre-0.4.11 configs persisted the old
  paste_injection=true default (per-char restore); migrated to false with a
  _cfg_version marker; explicit later choices respected

## 0.4.13

### Fixed
- HTML-only clipboard sources (no CF_UNICODETEXT): hosts parsing CF_HTML lost
  line breaks (single-line Notepad paste). Guard now normalizes such clipboard
  to unicode plain text with block-level newlines on copy and before paste;
  html_to_text converts block tags to newlines

## 0.4.12

### Fixed
- Manual update check always gives tray feedback (bypasses silent mode) and
  distinguishes newer / current / error (previously error and current both
  silent); check result logged

## 0.4.11

### Changed
- Restore direction default flipped to one-shot clipboard paste (instant,
  original format — fixes slow per-char Notepad paste); privacy mode
  paste_injection=true kept as opt-in (clipboard-free, per-char)
- Injection newlines converted to CRLF so host format is preserved

### Added
- Update check: tray manual "Check for updates" + opt-in guard.update_check
  (default off, zero-network by default); compares GitHub releases, notifies and
  opens Releases page, never downloads

## 0.4.10

### Added
- Tray provenance: tooltip + menu header show version, build sha/time and
  binary/source; startup log records the same plus exe path (stale-build
  incidents now self-evident); CLI --version; release workflow embeds build sha

## 0.4.9

### Added
- Paste direction decision logging (direction/ai_focused/len/chunk size) to
  diagnose restore-vs-mask path selection under rapid focus switches

### Fixed
- Release build reliability: stop running guard before PyInstaller overwrite
  (locked exe caused silent stale-binary builds)

## 0.4.8

### Added
- Forensic logging for paste hook: swallow/orphan-keyup/resend events with
  physical modifier state, to diagnose residual host shortcut popups
- Documented relief switch: guard.paste_hook=false disables paste interception
  (masking still protected via copy/focus paths)

## 0.4.7

### Changed
- Mask-direction paste chunked (default 400 chars / 40ms): amortizes host
  rendering cost of one huge input event (console/Qoder/WorkBuddy stutter /
  truncation-then-complete). Blocks appear whole, not char-by-char.
  Config: guard.paste_chunk_size (0 = one-shot), guard.paste_chunk_delay_ms

## 0.4.6

### Fixed
- Adaptive paste-key resend: when physical Ctrl/Shift still held, resend only
  the main key (borrowing the physical modifier); full combo only when
  released. Prevents synthetic/physical modifier-down nesting that latched
  Ctrl in Electron hosts (post-paste shortcut popups)

## 0.4.5

### Fixed
- Extension paste interception now synchronous: config cached in memory
  (initial load + onChanged); preventDefault inside async storage callback
  missed the default-action window (extension appeared ineffective)
- allSites defaults to true: internal-scheme new-tab pages and unlisted hosts
  were skipped; masking only fires on secret detection (safe direction)

## 0.4.4

### Fixed
- Orphan paste-key KEYUP now swallowed together with the swallowed KEYDOWN:
  hosts (Electron apps) no longer see unbalanced modifier sequences that
  latched Ctrl and turned later keystrokes into shortcuts (search/settings
  popups after paste)
- Restore-direction injection waits for physical modifier release (<=3s);
  synthetic keyup removed (defeated by Ctrl auto-repeat keydown). If Ctrl is
  still held at deadline, falls back to clipboard path (rare, documented
  privacy trade-off)

### Notes
- Web chat sidebars on ordinary pages are not classifiable via UIA
  (contenteditable placeholders invisible); the MV3 extension is the designed
  layer for web chats (DOM paste masking, classification-free)
- Large one-shot paste stutter is host-app rendering, not guard behavior

## 0.4.3

### Changed
- Mask-direction paste now writes masked text to clipboard and re-sends the
  real Ctrl+V: one-shot paste (no char-by-char rendering), no shortcut
  pollution; clipboard holds only masked text (zero-plaintext guarantee kept)
- Restore-direction keeps injection (plaintext off clipboard) but synthesizes
  Ctrl/Shift/Alt keyup before injecting, eliminating stray shortcuts
  (e.g. WorkBuddy settings dialog opening on paste)

### Notes
- Restore-direction injection renders char-by-char in some apps: accepted
  privacy trade-off (plaintext never touches clipboard/history/cloud sync)

## 0.4.2

### Fixed
- Long-text paste漏掩: paste handling moved off the LL-hook callback into a
  worker thread (full clipboard-lock retries; hook timeout no longer truncates
  reads on large copies); untransformed pastes re-send the original combo with
  a magic marker (no hook self-loop)
- Stray shortcuts / search-popup on paste: injection now waits for physical
  Ctrl/Shift release before sending unicode (chars were arriving as
  Ctrl+<char> shortcuts, e.g. Ctrl+P opening quick-open)
- New-tab chat detection: window title matched by prefix before " - Browser"
  (full title carries suffix; address-bar UIA value may be placeholder text)

## 0.4.1

### Added
- Release binaries: pilayer-guard.exe (Windows), pilayer-guard-macos-arm64,
  pilayer-guard-linux-x86_64 (ubuntu-22.04 build for wider glibc compatibility).
  Intel macOS: no prebuilt (Intel runners retired; PyInstaller cannot
  cross-compile) — use `pip install -e .[image]` there.
- macOS Gatekeeper / Linux exec-permission notes in README/SECURITY

### Notes
- macOS binaries unsigned: right-click → Open once, or
  `xattr -d com.apple.quarantine pilayer-guard-macos-*`
- Linux binary needs xclip/xsel (+xdotool for injection) at runtime

## 0.4.0

### Added
- macOS backend: NSPasteboard polling, CGEventTap paste hook + Unicode injection
  (Accessibility permission), NSWorkspace focus + AX signature scan, tray app
- Linux X11 backend: clipboard I/O via xclip/xsel (robust C selection impl),
  polling change detection, XGrabKey paste hook, xdotool injection,
  _NET_ACTIVE_WINDOW focus, tray app
- Linux Wayland honest degradation: clipboard-only always-on (wl-clipboard)
- MV3 browser extension: DOM paste masking in web chat inputs (known AI hosts +
  all-sites toggle), JS port of core rules, popup stats/clear, node unit tests
- CI matrix: windows-latest / macos-latest / ubuntu-latest (Xvfb) + node job
- Platform support matrix in READMEs; SECURITY platform notes

### Notes
- Windows reference path untouched (risk isolation); mac/Linux share the engine
- macOS/Linux image OCR and Keychain/secret-service integration: roadmap
- Excluded by decision: NER (model supply chain unverifiable here), code signing
  (paid cert + identity), opt-in LLM review (niche + heavy) — remain on roadmap

## 0.3.0

### Added
- Trust UI: tray "Recent masks" audit submenu (no secrets), "Restore clipboard
  now", runtime focus/always mode toggle; `pilayer unmask` CLI
- Bank card BIN gate (known prefixes + UnionPay ranges) cuts order-number false
  positives; `rules.bankcard_bin` switch
- Windows single-file exe (`pilayer-guard.exe`, includes OCR) built by CI on tags
- Schematic demo GIF in README; docs/launch.md (Show HN / 掘金 / V2EX / Reddit copy)
- Injection delivery verified end-to-end at input-event level (deterministic
  foreground probe); first-char settle delay in drain

### Fixed
- Audit events now recorded on the injection path (not only clipboard-write path)
- x64 SendInput first-character loss mitigated (50 ms settle); tkinter probe
  insertion quirk documented as probe artifact

### Notes
- Apps with sparse accessibility trees (tkinter, some Electron shells) are not
  caught by UIA signatures; covered by curated list / self-learning / title rules
- Roadmap unchanged: NER async layer, opt-in local LLM review, browser extension,
  macOS/Linux, code signing / EDR allowlisting

## 0.2.0

### Added
- Focus-aware mode (default): mask only while an AI conversation client is foreground
- Zero-config auto-detection via UIA signatures: model picker controls (in-document),
  AI disclaimer labels, chat input signatures; works on web widgets and installed
  page-as-app windows
- Three-layer detection: curated desktop client list (international + China) +
  signatures + self-learning (copying >=2 placeholders from an unclassified app
  learns its process; removable in config)
- Paste hook (Ctrl+V / Shift+Insert) with **SendInput injection**: clipboard never
  holds our plaintext; UIPI failure falls back to clipboard write
- Lazy restore: leaving AI no longer writes plaintext back to the shared clipboard
- Tray: silent-notification toggle, English/Chinese toggle, Start-with-Windows toggle
- Security hardening: DPAPI-encrypted mapping originals (+ legacy migration),
  TTL purge (`store.ttl_days`, `pilayer purge`), log redaction, copies dir cleanup
- Rules: assignment-style secrets (whole-line bare values), URI userinfo passwords,
  PGP blocks, Stripe/Google/SendGrid/Mailgun/Azure tokens, opaque Bearer/Basic,
  IPv6, internal URLs (private-IP / templated / configured domains), optional
  high-entropy rule
- CF_HTML-only clipboard source fallback
- i18n (en/zh) for tray and notifications; English-first README + full Chinese mirror
- CI (windows-latest) + hypothesis roundtrip invariant tests; requirements.lock
- SECURITY.md / CONTRIBUTING.md

### Changed
- `start-guard.bat` replaces the Chinese-named launcher; SendTo entry "Masked copy"
- Clipboard rewrite strips rich-text formats (prevents alternate-format leaks)

### Fixed
- Bare secret truncation at `#`/space/comma (residue leak)
- URI userinfo passwords with spaces; internal-URI host parsing behind userinfo
- Templated URL truncation at `{{ }}` spaces; quoted Jinja refs no longer masked
- DPAPI migration index-before-column crash on legacy databases
- UIA scan depth cap missing deep controls; browser-chrome AI buttons false positives

## 0.1.0

- Initial release: clipboard guard (text/image/file paths), masked file copies
  (txt/md/csv/json/log/docx/xlsx), reversible placeholders, local sqlite mapping,
  tray app, CLI, MIT license