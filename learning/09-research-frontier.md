# 09 — Research Frontier

Where the field is in 2026 and what Atlas could become. Each item: the idea,
why it matters, what it would take in Atlas.

## 1. Long context vs RAG

Models now take 200k–1M tokens. Why retrieve at all? Because: cost scales
with tokens on every call, latency too, "lost in the middle" degrades
accuracy as context grows, and you still cannot fit a real corpus. The
research consensus is *both*: retrieve a generous candidate set, let the
model read more of it. For Atlas: raise `RerankerConfig.top_k` from 5 to
~15 and measure faithfulness vs cost.

## 2. Structured knowledge: GraphRAG

Extract entities and relations into a graph; summarise communities; answer
"global" questions ("what are the main themes?") that chunk retrieval cannot.
Expensive to build (LLM call per chunk), powerful for corpus-level questions.
Atlas fit: a third retriever behind the same interface; a `global` route
class.

## 3. Hierarchical retrieval: RAPTOR

Recursive clustering + summarisation into a tree; retrieve across levels.
Cheaper than GraphRAG, targets the same "needs the whole doc" gap. Fits
Atlas's ingestion as an extra pass.

## 4. Better first-stage retrieval

- **Learned sparse (SPLADE)** in Qdrant sparse vectors — replaces the O(N)
  BM25 loop, adds term expansion.
- **ColBERT / multi-vector** — late interaction at first stage; Qdrant
  supports it. Storage ×30–100.
- **Query rewriting**: HyDE, multi-query (generate 3 paraphrases, union
  results), step-back prompting (ask the general question first). All are
  one prompt + one loop in `retrieval/`.
- **Fine-tuned embeddings** on your corpus's (query, chunk) pairs — usually
  the largest single gain on domain data; needs a few thousand pairs, which
  the eval dataset and synthetic generation can bootstrap.

## 5. Ingestion quality

Contextual retrieval (LLM-written chunk context), late chunking, proposition
chunking, layout-aware PDF parsing (docling, marker), table extraction. Most
production RAG failures are here, not in the model.

## 6. Adaptive computation

Route by difficulty (Adaptive-RAG), skip the grader for easy questions, use a
smaller model for routing than for generation, early-exit when the top
rerank score is very high. Directly attacks Atlas's 3–5-call latency.

## 7. Verification and trust

Chain-of-Verification, self-consistency (sample N answers, keep claims that
agree), citation *precision* (does the cited chunk actually support that
sentence?) as a first-class metric, attribution at the span level rather
than the answer level. Atlas's claim-level checker and dashed unsourced spans
are the foundation.

## 8. Agents with tools

Beyond a fixed DAG: the model can call `search`, `read_document`,
`run_sql`, loop until satisfied, under a step and cost budget. MCP is the
emerging protocol for exposing those tools. Sextant (the sibling project) is
the MCP-native exploration; Atlas stays the disciplined pipeline. Knowing
where each shines is the research question.

## 9. Evaluation at scale

Synthetic dataset generation with diversity constraints, LLM judges
calibrated against human labels, online eval (thumbs, re-asks, citation
clicks) feeding back into the offline set, regression suites on every
commit. Atlas's harness is the offline half.

## 10. Multimodal

Images, diagrams, tables as retrievable units (ColPali embeds page images
directly). For a docs corpus with screenshots this is not exotic.

## Reading list — the canon

Foundational
- Lewis et al., RAG (2020) arXiv:2005.11401
- Karpukhin et al., DPR (2020) arXiv:2004.04906
- Izacard & Grave, Fusion-in-Decoder (2020) arXiv:2007.01282
- Izacard et al., Contriever (2021) arXiv:2112.09118

Retrieval
- Khattab & Zaharia, ColBERT (2020) arXiv:2004.12832
- Formal et al., SPLADE (2021) arXiv:2107.05663
- Gao et al., HyDE (2022) arXiv:2212.10496
- Thakur et al., BEIR (2021) arXiv:2104.08663

Agentic
- Yao et al., ReAct (2022) arXiv:2210.03629
- Asai et al., Self-RAG (2023) arXiv:2310.11511
- Jiang et al., FLARE (2023) arXiv:2305.06983
- Yan et al., CRAG (2024) arXiv:2401.15884
- Jeong et al., Adaptive-RAG (2024) arXiv:2403.14403

Structure
- Sarthi et al., RAPTOR (2024) arXiv:2401.18059
- Edge et al., GraphRAG (2024) arXiv:2404.16130
- Günther et al., Late Chunking (2024) arXiv:2409.04701

Evaluation & trust
- Es et al., RAGAS (2023) arXiv:2309.15217
- Min et al., FActScore (2023) arXiv:2305.14251
- Liu et al., Lost in the Middle (2023) arXiv:2307.03172
- Dhuliawala et al., Chain-of-Verification (2023) arXiv:2309.11495
- Barnett et al., Seven Failure Points (2024) arXiv:2401.05856

Surveys (read one, skim the other)
- Gao et al., *Retrieval-Augmented Generation for Large Language Models: A
  Survey* (2023) arXiv:2312.10997 — the naive/advanced/modular taxonomy.
- Fan et al., *A Survey on RAG Meeting LLMs* (2024) arXiv:2405.06211.

## How to read a paper for this project

Abstract → the one figure that shows the method → main results table (find
the BM25 or naive-RAG baseline row) → limitations. Then ask: what would this
change in Atlas, which file, and how would `make eval-compare` show it
worked? If you cannot answer the last question, the paper is not actionable
yet.
