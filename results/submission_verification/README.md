# Current-model verification outputs

These outputs were generated from the merged continuous-channel, packet-level
implementation. The runs below check reproducibility at two scales.

| Check | Design | Evidence |
| --- | --- | --- |
| [Short workflow](smoke) | Four slots per episode. 180 main policy runs, 48 supplementary runs, 18 offline references and 12 short solver checks | [Stage completion](smoke/completion.json), [input and source hashes](smoke/preflight.json), [solver comparison](smoke/solver/solver_comparison.csv), [solar audit](smoke/solar/source_audit.json) |
| [1,000-slot comparison](normalized_1000) | Stationary mean-normalized synthetic channel, sigma 0.45, two harvest levels, two matched seeds and five policies | [Weighted cost](normalized_1000/realized_cost.png), [paired results](normalized_1000/paired_vs_nominal.csv), [audit](normalized_1000/audit.json) |

The short workflow includes per-slot and per-packet tables, source manifests,
run-level summaries, figures and audit records. The 1,000-slot comparison
includes the same synthetic outputs for a single volatility setting, with
20 policy runs. Its slot and packet ledgers are gzip-compressed. Decompress
them to `per_slot.csv` and `per_packet.csv` to rerun the synthetic audit.
The ten-seed and ten-window design is documented in the
[full experiment protocol](../../docs/experiments_1000.md).
