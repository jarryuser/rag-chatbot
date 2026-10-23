# Conversational retrieval and missing information

The original 36-case dataset and documents are unchanged; the dataset SHA-256 in `after.json` matches `baseline.json`

## Original benchmark comparison

| Check | Before | After |
|---|---|---|
| Reranked evidence in first four passages | 28/28 | 28/28 |
| Reranked evidence ranked first | 18/28 | 21/28 |
| Reranked mean reciprocal rank | 0.771 | 0.845 |
| Expected answer aliases found | 28/28 | 28/28 |
| Correct missing-information handling, manual review | 7/8 | 8/8 |
| Provider errors | 0/36 | 0/36 |

For the four original follow-ups, the supporting passage moved from ranks 4, 3, 2, and 3 to ranks 1, 2, 1, and 1 respectively

The previous `q32` answer asserted that no clinical benefit was measured. The new answer says that the provided excerpts do not report a measured benefit, without claiming that none occurred

The automatic abstention marker rate remains 3/8. This unchanged diagnostic misses several valid formulations such as “not reported”; its scorer was deliberately preserved for comparison, and manual review is reported separately

## Additional scenarios

`followup-check.json` adds three short documents and 12 questions: six follow-ups, three topic changes, and three questions with missing information

| Retrieval method | Evidence in first four passages | Evidence ranked first | Mean reciprocal rank |
|---|---|---|---|
| Vector | 9/9 | 9/9 | 1.000 |
| Hybrid | 8/9 | 8/9 | 0.889 |
| Reranked | 9/9 | 8/9 | 0.917 |

All nine expected answers were found by alias checks, and each answer cited the passage containing the expected evidence. Manual review found correct handling of all three missing-information questions, including a false budget in assistant history

No provider errors occurred in the 12 new scenarios; automatic abstention markers detected none of the three valid refusals, again showing the limits of keyword scoring

The Slovak answer `h09` correctly distinguishes unreported results from an evaluation not happening, but adds unnecessary hypothetical explanations and refers to the rules; concise wording remains an improvement opportunity

## Scope and limitations

The search adds bounded recent user questions when a question appears referential; it excludes assistant assertions and does not make an extra provider request. Explicit standalone questions use their own text, while ambiguous references and conjunctions can still bring in an irrelevant previous topic

The answer prompt requires evidence and cautious treatment of missing information. This is an instruction to the model, not a deterministic answerability gate or a guarantee against unsupported claims

The new cases were authored separately after the implementation, but are not an independent external benchmark. Both corpora are small and synthetic; the results do not establish accuracy on long PDFs, scanned pages, or ambiguous real documents

The reranker remains unchanged and still ranks evidence below vector search on these corpora; hybrid retrieval also misses one new case in its first four passages, although reranking the wider candidate set recovers it

The case-level outputs are in `after.json` and `followup-results.json`; passages are stored as source references to avoid repeating fixture text, and full raw reports remain reproducible with `scripts/evaluate.py`
