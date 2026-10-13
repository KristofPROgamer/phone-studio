# Phone Studio

A native Android front end for a private Colab image studio: one router, up to three image workers, prompt assistance, generation, editing and saved results.

**Status:** Preserved 0.3.2 source snapshot. The author reports it working; GPU/Colab and physical-phone verification were not repeated during publication.

**Publication test results:** 311 passed and 2 failed in the router suite; live GPU/phone behavior remains unverified.

## What is here

- `app/`: Kotlin/Jetpack Compose Android client.
- `router/`: orchestration, persistence and worker coordination.
- `PHONE_STUDIO_COLAB.ipynb`: image worker runtime.
- `PHONE_STUDIO_ROUTER_COLAB.ipynb`: router/assistant runtime.
- `tools/` and `tests/`: setup support and source checks.
- [VERSIONS.md](VERSIONS.md): preserved early versions and snapshot tags.

## Getting started

Follow [RECOVERY_STARTUP.md](RECOVERY_STARTUP.md) and [ROUTER_GUIDE.md](ROUTER_GUIDE.md): configure private Colab Secrets, start one worker, start the router, then pair the Android app. Supply your own model downloads and credentials.

To build the Android source, install a compatible JDK and Android SDK, configure your local SDK path, then run:

```powershell
.\gradlew.bat assembleDebug
```

See [the original 0.3.2 guide](README.original.md) for usage and runtime details.

## Current boundaries

The E: delivery was compared with the full E: workspace; their application source matched. Notebook output, local runtime state, credentials, APKs and build caches are excluded. Historical snapshots are imported now with honest current commit dates, not presented as recovered original Git commits. Some early snapshots contain notebooks and delivery notes rather than a complete Android source tree.

## Preservation and checks

This repository preserves a development snapshot, including incomplete work. See [PUBLICATION.md](PUBLICATION.md) for what was retained or excluded and [VALIDATION.md](VALIDATION.md) for the checks actually run. Original copyright and license notices take precedence over the repository’s display name.
