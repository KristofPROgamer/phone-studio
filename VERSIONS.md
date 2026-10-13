# Preserved Phone Studio versions

The current branch contains the 2026-10-09 **audit fixes 0.3.2** source recovered from E:. It matches the source in the full E: workspace. The separate `small_phonecollabaiproj-ai-dev` folder and distinct delivered snapshots are available as Git tags.

These are sanitized snapshot imports, not recovered original development commits. Import timestamps reflect publication; labels record the source snapshot’s original name/date. Notebook outputs and credentials are absent from every snapshot.

| Tag | Original snapshot | Preserved scope |
|---|---|---|
| `snapshot/early-ai-dev` | Separate early app folder | Android source and original Colab notebook |
| `snapshot/2026-10-01` | October 1 delivery | Notebook and available delivery notes |
| `snapshot/2026-10-01-lint` | October 1 lint cleanup | Notebook and available delivery notes |
| `snapshot/2026-10-01-router` | October 1 router and editing | Available router/delivery source and notebooks |
| `snapshot/2026-10-09-qr` | October 9 app and QR setup | Android/router source and notebooks |
| `snapshot/0.3.1` | October 9 verified 0.3.1 | Android/router source and notebooks |
| `snapshot/0.3.2` | October 9 audit fixes 0.3.2 | Current source, with publication documentation |

The Android app, router and worker notebooks remain separate components in one repository. Source-only imports omit APKs and duplicate ZIPs. An earlier tag can be incomplete if the original delivery only contained an installable binary and notebook; no missing source has been fabricated.
