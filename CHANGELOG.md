# Changelog

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