# LLM Text-to-Query

Convert natural language to SQL queries using local LLMs.

## Interactive Shell

```bash
# Start all services
docker compose up -d

# Enter interactive REPL
docker compose exec app uv run text2query
```

## Benchmark

```bash
# Start benchmark
docker compose --profile benchmark up --build orchestrator
```

The automated TPC-H benchmark runs in three phases:

**Phase 1 — Setup & Validation**

1. Generates/Validates TPC-H test data using `tpchgen-cli`
2. Loads database schema, data, and indexes
3. Generates ground truth answer CSVs from reference queries

**Phase 2 — LLM Query Generation & Execution**

4. Prompts natural language questions to the LLM with the database schema
5. Executes LLM-generated SQL against the database

**Phase 3 — Analysis & Archiving**

6. Evaluates each query using similarity criteria
7. Generates the reports to `benchmark/results/YYYY-MM-DD_HH-MM-SS/`

### Evaluation Metrics

| Metric | Purpose |
|---|---|
| **Result F1** | Did the query produce the correct data? Primary correctness measure. |
| **AST Similarity** | How structurally close is the SQL to the reference? |
| **BLEU** | N-gram overlap between SQL token sequences. |
| **Token Jaccard** | Set-based keyword overlap between queries. |
| **Clause Scores** | Per-clause breakdown (SELECT, WHERE, etc.) to identify which parts failed. |
| **Error Category** | Classifies execution failures (SyntaxError, SchemaMismatch, RuntimeError, Timeout). |
| **Composite** | Weighted aggregate of F1 (45%), AST (25%), Embed (20%), BLEU (10%) for ranking. |
