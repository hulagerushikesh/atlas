| Metric | correctness-first |
| --- | --- |
| context_precision | 0.4667 |
| context_recall | 0.9378 |
| faithfulness | 1.0000 |
| answer_relevance | 0.8276 |
| answer_correctness | 0.7440 |

*15 samples · 74.0s · 167,740 tokens*

| Model | Calls | Prompt | Completion | Est. cost |
| --- | ---: | ---: | ---: | ---: |
| gemini-3.1-flash-lite (chat) | 116 | 145,444 | 20,412 | $0.0670 |
| gemini-embedding-001 (embedding) | 44 | 1,884 | — | $0.0003 |
| **total** | **160** | **147,328** | **20,412** | **$0.0673** (~₹5.92) |

*estimated from list prices at 88 ₹/$; the ratio between two runs is the part to trust*

| Stage | p50 ms | p95 ms |
| --- | --- | --- |
| retrieval | 2539 | 4903 |
| faithfulness | 2348 | 3284 |
| generation | 1931 | 3936 |
| grading | 1737 | 6446 |
| decompose | 1394 | 1701 |
| routing | 1361 | 3659 |
| **total** | **10840** | **19419** |

*per-sample latency, 15 samples; the run's own 74.0s is concurrency-wide and not comparable*