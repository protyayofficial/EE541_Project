# Production experiment results

The production run completed on November 20, 2026. The
[completion record](completion_verification.json) describes the 900 main
policy runs, 240 supplementary runs, 90 offline references and 12 solver
checks. Each main and supplementary episode uses 1,000 slots.

| Location | Contents |
| --- | --- |
| [Production tables and plots](production) | Run matrices, settings, per-run metrics, paired comparisons, solver checks and saved audits |
| [Report evidence](report_figures/INDEX.md) | Figures in PDF and PNG, plotted data, captions, summary tables and a compact input directory for replotting |
| [Report findings](report_figures/FINDINGS.md) | Main numerical comparisons and interpretation limits |

The repository contains a compact export rather than the full slot, packet
and offline-plan ledgers. Regenerate those records with the
[full experiment launcher](../README.md#reproduce-the-experiments). The saved
production and figure validation records describe the original audit inputs.
Machine-specific path prefixes and log formatting were cleaned for this
submission. The historical production hash manifests refer to the original
run directory, which included its raw ledgers.
