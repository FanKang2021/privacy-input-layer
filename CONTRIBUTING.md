# Contributing

Thanks for helping make AI conversations private by default!

## Dev setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[image,dev]
pytest -q
```

CI runs on windows-latest; keep it green. The hypothesis property test
(`restore(mask(x)) == x`) is the engine's core invariant — new rules must not
break it.

## Adding an AI client to the curated list

1. Verify the **exact process image name** on a real install (Task Manager →
   Details, or `Get-Process | Select ProcessName`), including spaces/casing
   (matching is case-insensitive).
2. Add it to `ai_targets.processes` defaults in `src/pilayer/config.py` and to
   `config.example.yaml`, plus the README support matrix.
3. Prefer clients whose accessibility tree is sparse (Electron shells) — clients
   with good UIA exposure are already covered by zero-config signatures.
4. One client per PR with the verification output pasted in the description.

## Adding a detection rule

- Add regex + kind + priority in `src/pilayer/engine/rules.py`.
- Add **synthetic** test cases only (never real credentials) in `tests/`.
- Keep the over-masking direction: false positives are preferable to leaks.
- Update both READMEs' rule lists and `config.example.yaml`.

## Adding UI strings

All tray/notification strings live in `src/pilayer/i18n.py` — add **both** `en`
and `zh` entries.

## Style

- No comments unless the WHY is non-obvious; docstrings one line where possible.
- Windows-only APIs stay in `clipboard/` and `focus.py`; engine stays pure.