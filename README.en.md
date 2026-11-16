# privacy-input-layer

**The privacy input layer for AI.** Mask sensitive text, images and files *before* they enter any AI client — platform-native models, web apps, desktop apps alike. Interception happens at the OS input boundary (clipboard / file upload), not at the network layer, so it works everywhere regardless of protocol.

100% local: regex rules + local OCR + local sqlite mapping. Your originals never leave your machine.

## Coverage

| Scenario | Behavior | User effort |
|---|---|---|
| Copy text → paste into any AI client | Auto-replaced with placeholders (CN phone / ID card / bank card / email / custom keywords) | none |
| Copy AI reply containing placeholders | Auto-restored to real values | none |
| Screenshot / copy image → paste | OCR locates sensitive text lines, pixels masked (irreversible) | none |
| Copy file → paste to upload | Clipboard file paths swapped to masked copies | none |
| Right-click file → Send to → masked copy | Generates `.masked` copy for upload | one step |
| Restore AI-produced files | `restore-file` swaps placeholders back | one command |

File formats: `txt / md / csv / json / log / docx / xlsx`.

## Quick start

```bash
pip install -e .[image]
pilayer run                # tray app, guarding starts
pilayer install-sendto     # optional: right-click "Send to -> masked copy"
```

CLI: `mask-text`, `restore-text`, `mask-file`, `restore-file`, `stats`.

Mappings live in `%APPDATA%/pilayer/mappings.db` (local sqlite). The same original reuses the same placeholder across turns, keeping AI context consistent.

## Limitations

Windows only for now. Image masking granularity is the OCR text line. Rewriting the clipboard strips rich-text formats (prevents clients reading originals from HTML clipboard data). Files read from disk after upload cannot be intercepted transparently in user mode — hence the masked-copy step. PDF and NER-based name detection are on the roadmap.

## Privacy

No network requests at all. OCR runs locally. Delete `%APPDATA%/pilayer` to erase everything.

## License

MIT