# Publishing Activity Rings

This repo is set up to support both:

- GitHub source distribution
- `.ankiaddon` packaging for local installs or AnkiWeb upload

## Before Publishing

1. Confirm the add-on works in a real Anki session.
2. Fully quit and reopen Anki after final code changes.
3. Check that no user-specific files are committed:
   - `meta.json`
   - `__pycache__/`
   - `.DS_Store`
4. Review:
   - `manifest.json`
   - `config.json`
   - `README.md`
   - `config.md`

## Build The Release Artifact

From the add-on root:

```bash
python3 scripts/build_ankiaddon.py
```

This creates:

```text
dist/activity-rings.ankiaddon
```

The build script:

- validates `manifest.json`
- validates `config.json`
- compiles the Python files
- excludes `meta.json`
- excludes `__pycache__`
- excludes `dist/`
- excludes `scripts/`
- writes the archive without the top-level folder wrapper

That final point is important because AnkiWeb expects the archive contents to start at files like:

```text
__init__.py
manifest.json
config.json
...
```

and not:

```text
activity_rings_dashboard/__init__.py
```

## GitHub Release

Suggested release assets:

- source snapshot of this repo
- `dist/activity-rings.ankiaddon`

Suggested release notes:

- supported Anki versions
- major features
- known limitations
- install instructions

## AnkiWeb Upload Checklist

Before uploading:

1. Build a fresh `.ankiaddon`.
2. Confirm the archive does not contain:
   - `meta.json`
   - `__pycache__`
   - top-level folder wrapping
3. Confirm the add-on still imports and runs in Anki.
4. Prepare the AnkiWeb description using the content in `README.md`.

## Notes

- `config.json` provides the shipped defaults.
- User-edited settings are stored by Anki in `meta.json` and should not be distributed.
- `manifest.json` is included for local `.ankiaddon` installs and external distribution.
