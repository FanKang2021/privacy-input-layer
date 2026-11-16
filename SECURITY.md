# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** via GitHub Security
Advisories ("Report a vulnerability" on the Security tab of this repository).
Do not open public issues for security problems.

Include: reproduction steps, affected version, and impact assessment. We aim to
acknowledge within 72 hours and to publish a fix + advisory for confirmed issues.

## Security model & guarantees

- **No network activity.** The tool makes zero network requests; OCR runs locally.
- **Originals stay on this machine.** Mapping originals are stored DPAPI-encrypted
  (current-user key) in `%APPDATA%/pilayer/mappings.db`; legacy plaintext rows are
  migrated on first start.
- **Clipboard never holds our plaintext** (default `paste_injection: true`): paste
  text is injected via SendInput; the clipboard only ever contains the user's own
  copies or masked placeholders. This closes Windows clipboard-history (Win+V) and
  cloud-clipboard sync exposure for restored values.
- **Logs contain no secrets**: only process names, signature kinds and counts.
- **No keylogging**: the keyboard hook inspects only paste key combinations.
- **Storage limitation**: mappings and masked copies purge after `store.ttl_days`.

## Known limitations (accepted trade-offs)

- Same-user threat model: DPAPI protects at rest against other users/offline disk
  access, not against malware running as the same user.
- Image masking is irreversible and line-granular; a sub-second image paste right
  after a window switch can race the OCR pass (text is covered by the paste hook).
- Unsigned binaries: Windows SmartScreen / corporate EDR may flag the keyboard-hook
  + clipboard-write behavior pattern. Code signing is on the roadmap; enterprise
  deployments should allowlist the executable.
- Menu/right-click paste outside AI clients yields placeholders by design
  (injection covers keyboard paste); `lazy_restore: false` restores old behavior.
- Placeholder reuse across sessions allows an AI to correlate conversations;
  purge resets linkage.

## Platform notes

- **macOS**: paste hook + injection require Accessibility permission (System
  Settings → Privacy & Security → Accessibility). Without it the guard degrades
  to clipboard-compensation on copy. Mapping originals use the same local
  encrypted store; Keychain integration is on the roadmap.
- **Linux Wayland**: global input injection and foreground queries are forbidden
  by the compositor security model; the guard degrades to clipboard-only
  always-on. X11 sessions get the full feature set.
- **Browser extension**: masks at DOM paste time; mappings live in
  `chrome.storage.local` (profile-local). The extension never sends data off
  device; it has no network permissions.

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x | yes |
| < 0.2 | no |