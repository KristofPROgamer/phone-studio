# Phone Studio — finished snapshot, 2026-10-01

This folder holds the matched deliverables for the completed speed/usability stage. Further feature work is awaiting your instructions.

- `PhoneStudio-2026-10-01-debug.apk`: installable Android debug app, version 0.1.0/code 1, Android 8.0+.
- `PHONE_STUDIO_COLAB.ipynb`: self-contained notebook with embedded helpers; open in Colab and run all cells with your Secrets.
- `PhoneStudio-2026-10-01-source.zip`: matching app/notebook source, Gradle wrapper, documentation and verification records. Local SDKs/caches, credentials and work-in-progress backups are excluded.
- `SHA256.json`: hashes identifying these finished files.

Implemented: two presets, enabled supported speed experiments, saved per-render Extra acceleration switch, preflight/catalog/output optimizations, timing logs, completion-read improvements, shared pinch/pan/reset viewer, corner **i** metadata, reachable controls and redundant saved drafts. Historical image metadata and existing Drive files are preserved.

Local checks passed: debug APK build/signature, 31 unit tests, lint with 0 errors/9 warnings, and 27 source checks. No notebook/GPU/phone run or measured speedup is claimed. Experimental defaults can change images; the phone switch leaves launch-time precision/compile settings in place.

Use the APK and notebook together for the switch. Install the APK manually on your phone; open the notebook in Colab, set Secrets and choose the available T4 GPU. Details, the full pipeline, ranked estimated impacts, rollback and later runtime verification are in README.md, PERFORMANCE.md, SPEED_MODES.md, GPU_ACCELERATION_RESEARCH.md and VERIFICATION.md inside the source archive.
