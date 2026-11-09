# Enterprise Multi-Tenant Agentic RAG Platform

An enterprise-grade, distributed, multi-tenant Agentic Retrieval-Augmented Generation (RAG) platform leveraging a hybrid **Java/Spring Boot** and **Python/FastAPI** architecture. This repository demonstrates production-ready solutions for data isolation, token rate-limiting, non-deterministic AI orchestration, and microsecond-level document permission validation.

---

## 📄 Project Abstract

Modern enterprise deployments of Large Language Models (LLMs) are severely constrained by strict data privacy mandates, complex role-based access controls (RBAC), and the non-deterministic nature of raw Retrieval-Augmented Generation (RAG). This platform implements a production-grade, distributed, multi-tenant Agentic RAG system leveraging a hybrid **Java/Spring** and **Python/FastAPI** ecosystem to deliver secure, deterministic, and context-aware enterprise knowledge retrieval. 

The architecture establishes a strict separation of concerns across the technology stack:
* **The Governance & Ingestion Layer (Java/Spring Boot):** Acts as the highly concurrent enterprise perimeter. It handles OAuth2/OIDC authentication, orchestrates multi-tenant isolation, manages rate-limiting via Redis Token Buckets to prevent cross-tenant token starvation, and routes asynchronous background document extraction jobs through **Apache Kafka**.
* **The Cognitive & Execution Layer (Python/FastAPI):** Powers the AI intelligence. It utilizes **LangGraph** to build stateful, self-correcting agentic loops that orchestrate advanced retrieval strategies (Query Rewriting, Self-RAG, and Document Grading). Data extraction pipelines leverage specialized Python libraries and embedding models to handle unstructured multi-modal formats (PDFs, Tables).
* **The Data & Storage Infrastructure:** Implements cross-tenant logical isolation within a **PostgreSQL (pgvector)** database. Tenants are isolated using strict database Row-Level Security (RLS) policies combined with dynamic metadata filtering payloads. This design guarantees zero cross-tenant data leakage while enforcing structural user-level document permissions.

---

## 🛠️ Requisites & Dependencies

### Runtimes & Infrastructure
* **Java Development Kit (JDK) 21+** (Utilizing Virtual Threads / Project Loom for high-concurrency token validation)
* **Python 3.11+** (Asyncio runtime optimization)
* **Docker & Docker Compose v2+**

### Backend Core Dependencies (Java Ecosystem)
* **Spring Boot 3.3.x** (Core application framework)
* **Spring Cloud Gateway** (Reverse-proxy routing and centralized tenant context discovery)
* **Spring Security OIDC / OAuth2 Resource Server** (JWT validation and RBAC management)
* **Spring Kafka** (Reactive event streaming client)
* **Lettuce / Spring Data Redis** (Low-latency cluster rate-limiting and session synchronization)

### AI Core Dependencies (Python Ecosystem)
* **FastAPI 0.111.x** (Asynchronous, high-performance API routing layer)
* **LangGraph 0.1.x** (Stateful, cyclic multi-agent orchestration)
* **LangChain Core & Community** (Vector store abstraction and LLM connector abstractions)
* **Celery 5.4.x** (Distributed asynchronous tasks worker pool)
* **PyMuPDF / LayoutLM / Unstructured** (Document extraction and semantic structural chunking)
* **Ragas 0.1.x** (Automated LLM-as-a-judge evaluation framework)

### Storage & Data Ecosystem
* **PostgreSQL 16+** (Relational metadata storage)
* **pgvector Extension 0.7.x** (Vector distance metric indexations)
* **Redis 7.2+** (Broker for Celery, caching tier, and distributed token-buckets)

---

## 📐 System Architecture & Data Flow

```
                       [ Enterprise Client Traffic ]
                                    │
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │     API Gateway & Security Proxy (Java / Spring)       │
       │  - OAuth2/OIDC Token Parsing      - Redis Rate Limiting │
       └────────────────────────────┬────────────────────────────┘
                                    │
                  ┌─────────────────┴─────────────────┐
                  ▼                                   ▼
┌───────────────────────────────────┐     ┌───────────────────────────────────┐
│   Ingestion Service (Java)        │     │    Orchestration Proxy (Java)     │
│ - Chunking Coordination           │     │ - Metadata Filter Injection       │
│ - Document Cryptography           │     │ - Audit Logging & Lineage         │
└─────────────────┬─────────────────┘     └─────────────────┬─────────────────┘
                  │ (Async Event)                           │ (gRPC / mTLS)
                  ▼                                         ▼
┌───────────────────────────────────┐     ┌───────────────────────────────────┐
│   Python Worker Cluster (Celery)  │     │   Python Agentic Core (FastAPI)   │
│ - Structural Layout Extraction    │     │ - LangGraph Routing Engine        │
│ - Embedding Pipeline Generation   │     │ - Guardrails (Llama-Guard)        │
└─────────────────┬─────────────────┘     └─────────────────┬─────────────────┘
                  │                                         │
                  └─────────────────┬───────────────────────┘
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │             Multi-Tenant Vector Infrastructure          │
       │   - PostgreSQL + pgvector (Row-Level Security)          │
       │   - Automated Runtime Payload Metadata Enforcement      │
       └─────────────────────────────────────────────────────────┘
```

### Component Strategy Cross-Mapping

| Component Layer | Java Ecosystem (The Muscle) | Python Ecosystem (The Brain) | Cloud & Data Infrastructure |
| :--- | :--- | :--- | :--- |
| **API & Ingestion** | **Spring Boot** (Multi-threading, strict typing) | **FastAPI** (Lean model-serving loops) | **AWS ALB / Cloud Gateway** |
| **Event Routing** | **Spring Cloud Stream** (Schema matching) | **Celery / Redis Queue** (Worker execution) | **Apache Kafka** (Immutable log) |
| **Storage & Vectors**| **JDBC / Spring Data** (Relational state) | **Vector Client Adapters** (Wrangling) | **PostgreSQL + pgvector** |
| **MLOps & Evaluation**| **Spring Batch** (Large-scale batching) | **Ragas / PyTorch** (Eval framework) | **MLflow / Databricks** |

---

## 🔬 Methodology

The platform processes information across two distinct execution loops designed to maximize enterprise throughput while completely enforcing tenant-level cryptographic and software-level safety perimeters.

### 1. Asynchronous Ingestion & Vector Mapping Pipeline
1. **Context Interception:** The Java Spring Security filter intercepts an incoming multi-part file upload. It extracts the encrypted `tenant_id` from the JWT claims and validates user permissions.
2. **Payload Staging:** The payload is saved to an S3 object store. A lightweight metadata manifest payload containing `{document_id, tenant_id, file_path}` is published to a partitioned Apache Kafka topic.
3. **Distributed Worker Extraction:** A Python Celery worker pulls the event payload. The document is split structurally via layout-aware models, stripped of PII via regex filters, and transformed into 1536-dimensional embeddings.
4. **Isolated DB Ingestion:** Chunks are written back to PostgreSQL. Data is isolated via logical constraints by automatically configuring database connection sessions with standard `SET Local app.current_tenant = 'tenant_id'`.

### 2. State-Driven Self-Correcting Agentic Retrieval
1. **Dynamic Tool Selection:** Upon query ingestion via the FastAPI layer, a compiled LangGraph engine checks query semantic safety via Llama-Guard.
2. **Deterministic Filter Injection:** The Graph injects an absolute conditional clause (`tenant_id == active_tenant`) directly into the database client connection wrapper, preventing algorithmic vector leaks.
3. **Self-Correction & Evaluation Loops:** If the vector database yields context blocks that fall below an acceptable cosine-similarity threshold score, the graph node invokes a sub-agent to automatically rewrite the query terms and re-execute retrieval up to three times.
4. **Final Guardrails Routing:** The assembled context packet is validated for leakage against systemic corporate blacklists prior to stream-delivery via Server-Sent Events (SSE).

---

## 🗺️ Project Roadmap

```
Phase 1: Architecture & Network Foundation (Week 1-2)
├── Design multi-tenant database schematics
├── Deploy Docker Compose stack (Kafka, Redis, PostgreSQL + pgvector)
└── Build Spring Cloud Gateway token-parsing filter architecture

Phase 2: Ingestion Pipelines & Event Orchestration (Week 3-4)
├── Implement Spring Boot Kafka document event producers
├── Configure Celery background Python extraction workers
└── Construct automated layout-aware chunking and embedding logic

Phase 3: Stateful Agent Development (Week 5-6)
├── Implement FastAPI server routes
├── Program LangGraph routing nodes (Intent, Retrieval, Re-ranking)
└── Enforce systemic filter injections in the vector access client

Phase 4: Evaluation, Hardening & Deployment (Week 7-8)
├── Set up Redis Token-Bucket rate limit configurations
├── Implement Ragas verification checks (Faithfulness & Context Metrics)
└── Export system metrics dashboards and final documentation
```

### Milestone Verification Matrix
* **Milestone 1:** Demonstrate a query executed by `Tenant_A` receiving a hardware-enforced empty array when searching items owned by `Tenant_B`.
* **Milestone 2:** Generate an automated Ragas quality test execution run showing a target Faithfulness rating $> 0.90$ across a sample 100-query batch.
* **Milestone 3:** Simulate high-concurrency API query tests via Locust/JMeter to prove the Redis Token-Bucket rate limiter blocks noisy-neighbor traffic patterns without impacting clean tenants.
