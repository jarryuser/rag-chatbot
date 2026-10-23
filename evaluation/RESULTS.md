# Initial benchmark results

This snapshot uses 36 synthetic questions and 12 short documents in English, Russian, and Slovak; 28 questions have supporting evidence and 8 do not

The full case-level snapshot, generated answers, and manual review notes are stored in `baseline.json`; document text and expected evidence are in `documents/` and `benchmark.json`

| Retrieval method | Expected evidence in first four passages | Expected evidence ranked first | Mean reciprocal rank |
|---|---|---|---|
| Vector | 28/28 | 22/28 | 0.881 |
| Hybrid | 28/28 | 21/28 | 0.851 |
| Reranked | 28/28 | 18/28 | 0.771 |

On this corpus reranking reduced the rank of the expected evidence; these results do not establish that reranking is generally worse, and no retrieval settings were changed to optimize this benchmark

## Generated answers

- Provider: Groq, model `qwen/qwen3.8-27b`
- Provider errors: 0 across 36 cases
- Expected answer aliases found: 28/28 answerable cases, including four follow-ups
- Automatic abstention markers found: 3/8 unanswerable cases
- Manual review: seven correct abstentions and one unsupported inference

The alias score is not semantic accuracy; follow-up success on a small corpus does not remove the known limitation that retrieval ignores conversation history

## Unsupported inference

For `q32` the model stated that no clinical benefit was measured for Project Delta, although the source only says that clinical outcomes are not recorded in the guide

A citation to the guide does not support that stronger claim; the expected answer is that the provided context does not report a measured clinical benefit

For `q26`, `q27`, `q28`, and `q29` the model correctly stated that information was missing, but its wording was not covered by the automatic marker list. The marker rate therefore understates correct abstention in this run

## Interpretation

This is a reproducible starting point, not a production quality claim. The corpus is small, explicitly labels missing information, and does not exercise long PDFs, OCR, or realistic document ambiguity

Next, expand held-out examples and evaluate stricter treatment of missing information and conversational query rewriting without tuning against these cases alone

## Subsequent changes

The snapshot above describes the initial implementation, where retrieval ignored history; the subsequent changes and comparison are documented in [IMPROVEMENTS.md](IMPROVEMENTS.md)
