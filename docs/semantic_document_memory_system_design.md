# Semantic Document Memory System

## Overview

This architecture is a structure-aware, incremental semantic retrieval system for Markdown and technical documents.

The system preserves:
- document topology
- semantic locality
- hierarchical context
- incremental update stability
- semantic relationships

Instead of flattening documents into arbitrary token chunks, the system builds a hybrid:

```text
Tree + Semantic Graph + Vector Index
```

This enables:
- high quality retrieval
- low token usage
- scalable indexing
- incremental updates
- context-grounded LLM responses

---

# Core Design Goals

| Goal | Strategy |
|---|---|
| Stable indexing | Deterministic parsing |
| Incremental updates | SHA per atomic node |
| Semantic retrieval | LLM-guided grouping |
| Context efficiency | Hierarchical summaries |
| Retrieval quality | Hybrid retrieval |
| Scalability | Multi-layer storage |
| Fidelity | Preserve original content |
| Multi-hop reasoning | Graph relationships |

---

# High-Level Architecture

```text
Markdown
  -> AST Parser
  -> Atomic Nodes
  -> Normalization
  -> Stable SHA Generation
  -> Structural Tree
  -> LLM Semantic Grouping
  -> Summary Generation
  -> Embedding Generation
  -> Graph Relationship Extraction
  -> Storage Layer
  -> Retrieval Pipeline
  -> Context Assembly
  -> LLM Response
```

---

# 1. Markdown Parsing Layer

## Purpose

Create a deterministic structural representation of the document.

## Requirements

- deterministic
- stable
- non-LLM
- syntax-preserving

## Recommended Parsers (Rust)

- `comrak`
- `pulldown-cmark`

## Output

```text
AST (Abstract Syntax Tree)
```

Example:

```md
# Kubernetes

## Pods
Pods are the smallest deployable units.
```

Becomes:

```text
Document
 └─ H1 Kubernetes
     └─ H2 Pods
         └─ Paragraph
```

---

# 2. Atomic Node Extraction

## Purpose

Convert AST into stable semantic primitives.

## Atomic Node Types

- heading
- paragraph
- list
- table
- code block
- quote
- image
- link

## Example

```json
[
  {
    "type": "heading",
    "text": "Pods"
  },
  {
    "type": "paragraph",
    "text": "Pods are the smallest deployable units."
  }
]
```

## Design Principle

Atomic nodes are:
- immutable
- deterministic
- independently hashable
- independently indexable

---

# 3. Content Normalization

## Purpose

Prevent unnecessary hash invalidation.

## Normalization Rules

- normalize line endings
- trim whitespace
- normalize indentation
- canonicalize markdown formatting
- normalize tables/lists where possible

## Important

Normalization must preserve semantic meaning.

---

# 4. Stable SHA Generation

## Purpose

Enable:
- incremental indexing
- deduplication
- caching
- subtree invalidation
- version tracking

## Hash Inputs

Include:
- normalized raw content
- node type
- structural path

Exclude:
- embeddings
- summaries
- LLM outputs
- timestamps

## Example

```json
{
  "sha": "abc123",
  "content": "Pods are the smallest deployable units."
}
```

---

# 5. Structural Tree Layer

## Purpose

Represent deterministic document topology.

## Example

```text
Document
 ├─ H1 Kubernetes
 │   ├─ H2 Pods
 │   │   ├─ paragraph
 │   │   ├─ code block
 │   ├─ H2 Services
```

## Important Constraint

The structural tree:
- is deterministic
- is parser-derived
- must never be rewritten by the LLM

This layer is used for:
- navigation
- locality
- context expansion
- hierarchy

---

# 6. LLM Semantic Grouping Layer

## Purpose

Infer semantic concepts beyond markdown structure.

## Motivation

Markdown structure is often presentation-oriented, not semantic.

Example:

```md
## Authentication
paragraph
OAuth
Token lifecycle
```

May semantically become:

```text
Authentication Concepts
 ├─ OAuth
 ├─ Token lifecycle
```

## LLM Responsibilities

Allowed:
- grouping adjacent nodes
- labeling semantic concepts
- linking related concepts
- detecting topic boundaries

Not allowed:
- mutating atomic content
- rewriting AST structure
- destroying deterministic topology

## Recommended Strategy

### Phase 1
Deterministic AST parse.

### Phase 2
Extract atomic nodes.

### Phase 3
LLM groups nearby nodes semantically.

This constrains non-determinism.

---

# 7. Semantic Node Model

Each semantic node stores:

```json
{
  "semantic_id": "...",
  "atomic_shas": [],
  "path": [
    "Kubernetes",
    "Pods"
  ],
  "title": "Pod Scheduling",
  "content": "...",
  "summary_short": "...",
  "summary_medium": "...",
  "embedding_local": [],
  "embedding_contextual": [],
  "parent": "...",
  "siblings": [],
  "children": [],
  "cross_links": []
}
```

---

# 8. Summary System

## Purpose

Provide multi-resolution retrieval context.

## Summary Types

| Type | Purpose |
|---|---|
| Short | retrieval grounding |
| Medium | contextual expansion |
| Detailed | optional compression |

## Important Rule

Never recursively summarize summaries.

Always derive summaries from:
- original content
- nearby semantic context

This prevents summary drift.

---

# 9. Embedding Strategy

## Local Embedding

Embeds only node content.

Example:

```text
pod scheduling constraints
```

Optimized for:
- precision
- local semantic matching

---

## Contextual Embedding

Embeds:
- path
- parent heading
- semantic labels
- local content

Example:

```text
Kubernetes > Pods > Scheduling
```

Optimized for:
- discoverability
- semantic grounding
- ambiguous terminology

---

# 10. Graph Relationship Layer

## Purpose

Represent non-hierarchical semantic relationships.

## Example

```text
OAuth -> Security
OAuth -> Session Lifecycle
OAuth -> API Gateway
```

## Why Graphs Matter

Knowledge is graph-shaped, not tree-shaped.

Trees are good for:
- locality
- navigation
- hierarchy

Graphs are good for:
- concept relationships
- multi-hop reasoning
- semantic traversal

## Design

The system becomes:

```text
Structural Tree + Semantic Graph
```

---

# Storage Architecture

# A. Document Store

Stores:
- raw nodes
- summaries
- metadata
- paths
- relationships

## Recommended Options

- SQLite
- PostgreSQL
- SurrealDB

---

# B. Vector Store

Stores:
- embeddings
- vector metadata

## Recommended Options

- Qdrant
- LanceDB
- pgvector

---

# C. Graph Storage

Initially optional.

Can begin with:

```json
cross_links: []
```

Later:
- Neo4j
- Kuzu
- graph tables

---

# Retrieval Pipeline

# Step 1 — Query Understanding

Input:

```text
How does pod scheduling work?
```

Generate:
- query embedding
- optional query decomposition
- keyword extraction

---

# Step 2 — Hybrid Retrieval

Retrieve using:
- vector similarity
- keyword/BM25
- structural metadata
- graph relationships
- semantic labels

## Important

Do not rely on pure vector retrieval.

Hybrid retrieval significantly improves relevance.

---

# Step 3 — Retrieve Semantic Nodes

Return:
- semantic concepts
- coherent topic units

Avoid returning:
- isolated arbitrary chunks

---

# Step 4 — Context Expansion

Attach nearby context.

## Always Include

- parent summary
- structural path

## Optionally Include

- nearby siblings
- child previews
- semantic cross-links

## Important

Limit expansion aggressively.

Recommended retrieval depth:
- 2 to 4 levels maximum

---

# Step 5 — Reranking

Rerank using:
- semantic similarity
- graph proximity
- path relevance
- heading importance
- recency
- keyword overlap

Optional:
- cross-encoder reranker

---

# Step 6 — Context Assembly

Construct grounded retrieval context.

Example:

```text
[Kubernetes > Pods > Scheduling]

Parent Summary:
Pods are deployable workload units.

Sibling Topics:
- Lifecycle
- Networking

Current Topic:
Scheduling constraints determine pod placement.
```

---

# Step 7 — LLM Generation

The final LLM receives:
- semantically coherent context
- structurally grounded context
- low-noise retrieval results
- neighboring semantic orientation

This improves:
- factual grounding
- answer coherence
- multi-hop reasoning
- token efficiency

---

# Incremental Update Pipeline

## Purpose

Avoid full re-indexing.

## Flow

### 1. Reparse Markdown

```text
Markdown -> AST
```

### 2. Recompute Atomic SHAs

Compare against existing hashes.

### 3. Detect Changed Subtrees

Only affected regions are invalidated.

### 4. Regenerate Only Changed Data

Recompute:
- summaries
- embeddings
- semantic groups
- graph edges

This enables scalable indexing.

---

# Depth Strategy

| Layer | Recommended Depth |
|---|---|
| Structural storage | unlimited |
| Retrieval expansion | 2–4 |
| Summary propagation | 1–2 |
| Semantic grouping | local neighborhood only |

## Important

Deep recursive retrieval often harms retrieval quality.

Local contextual grounding is usually more effective.

---

# Core Design Principles

## 1. Deterministic Foundation

Parsing and hashing must remain stable.

---

## 2. AI Augments Structure

AI enriches structure.

AI does not own the base representation.

---

## 3. Preserve Original Content

Never rely solely on:
- summaries
- embeddings
- compressed representations

Always preserve raw nodes.

---

## 4. Trees For Locality

Trees are optimized for:
- navigation
- hierarchy
- contextual expansion

---

## 5. Graphs For Meaning

Graphs are optimized for:
- semantic relationships
- multi-hop reasoning
- conceptual traversal

---

## 6. Retrieval Must Be Hybrid

Best retrieval systems combine:
- vectors
- keywords
- structure
- graph relationships
- metadata

---

# Final System Identity

This system is not a traditional RAG pipeline.

It is closer to:

```text
Semantic Document Operating System
```

or:

```text
Incremental Semantic Memory Architecture
```

The defining characteristic is:

```text
Preservation of document topology and semantic locality.
```

Rather than flattening knowledge into disconnected chunks, the system preserves:
- structure
- relationships
- context
- locality
- semantic continuity
- incremental stability

This architecture is especially well-suited for:
- technical documentation
- codebases
- API docs
- books
- accessibility documentation
- research notes
- personal knowledge systems
- long-lived AI memory systems

