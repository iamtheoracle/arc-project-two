# THE ORACLE-ARC — Model and System Comparison
**Snapshot date:** 31 October 2026  
**Repository baseline:** `feat/oracle-arc-personal-core`  
**Purpose:** Establish an evidence-led comparison against leading frontier and open-weight language models, and define repeatable tests for Oracle-Arc itself.

## 1. Executive finding

The current repository configures `qwen2.5:7b` as its default Ollama model. Oracle-Arc is therefore not itself a newly trained foundation model. It is an assistant system built around an existing model, with an API, persisted conversations, basic owner-managed memory, and tool permission controls.

Two separate comparisons are required:

1. **Foundation-model capability:** the underlying model's reasoning, knowledge, mathematics, coding, instruction following, multilingual and multimodal performance.
2. **Assistant-system capability:** memory quality, retrieval, research evidence, planning, tool reliability, verification, safety, recovery, privacy and latency.

A stronger orchestration layer can improve task completion and reliability, but it does not erase the underlying model's raw capability gap.

## 2. Current Oracle-Arc baseline

### Confirmed from the repository

- Default model string: `qwen2.5:7b`.
- Inference runtime: Ollama.
- Model adapter: `core/llm.py`.
- The adapter supports configurable Ollama host and timeout.
- The repository does not currently record a live model evaluation on the owner's hardware.
- The exact downloaded model digest, quantization, runtime version, hardware, context configuration and generation settings have not been captured in a benchmark report.

### Published Qwen reference results

Qwen's published Qwen2.5-7B-Instruct table reports the following results:

| Evaluation | Published score |
|---|---:|
| MMLU-Pro | 56.3 |
| GPQA | 36.4 |
| MATH | 75.5 |
| GSM8K | 91.6 |
| HumanEval | 84.8 |
| MBPP | 79.2 |
| LiveCodeBench 2305–2409 | 28.7 |
| IFEval strict-prompt | 71.2 |
| Arena-Hard | 52.0 |

**Interpretation:** these are Qwen-reported historical results for the named Instruct checkpoint and benchmark versions. They are not Oracle-Arc test results. They must not be directly compared with scores from different benchmark versions, prompting protocols, sampling settings, tools, or inference-time reasoning budgets. The Ollama tag may use a quantized distribution; the exact artifact must be identified before treating the published scores as a baseline.

## 3. Frontier comparison set

The following models should be included in the evaluation matrix. The list is a candidate set, not a claim that every model is available locally or that one ranking is definitive.

| Model | Provider | Evaluation role |
|---|---|---|
| Claude Opus 5.5 | Anthropic | Frontier reasoning, coding and knowledge-work reference |
| GPT-6 Astra | OpenAI | Frontier reasoning, science and professional-work reference |
| GPT-6.1 Sol | OpenAI | Frontier capability and efficiency comparison |
| Gemini 4 Argon | Google | Frontier general capability and automation comparison |
| Kimi K3.1 Pro | Moonshot AI | Strong model candidate; verify weight availability and deployment terms |
| DeepSeek V4.1 Flash | DeepSeek | Released-weight/local deployment comparison candidate |
| GLM-5.3 | Z.ai | Released-weight/local deployment comparison candidate |
| Qwen3.8 family | Alibaba Qwen | Natural successor-family comparison; select exact size and release |
| Qwen2.5-7B-Instruct | Alibaba Qwen | Current Oracle-Arc baseline family |

Artificial Analysis' Intelligence Index v5 evaluates nine tests across knowledge work, coding, science and general capability. Its published methodology includes private or held-out evaluation data, which helps reduce simple public-test memorization. Its October 2026 launch article identifies Claude Opus 5.5, GPT-6 Astra, GPT-6.1 Sol, Gemini 4 Argon and Kimi K3.1 Pro among leading systems. Use its current leaderboard and methodology as an external reference, not as a substitute for our own task tests.

## 4. Fairness rules

Every measured result must record:

- Exact provider, model name, model revision or digest.
- Local/API runtime and version.
- Quantization and precision, where applicable.
- Hardware, accelerator, memory and operating system for local runs.
- Context length, system prompt, tools, sampling parameters and reasoning mode.
- Dataset name, version, split, date and scoring method.
- Number of attempts, pass rate, confidence interval where practical, latency and cost.
- Whether the score is provider-reported, independent third-party reported, or measured by Oracle-Arc.

Never compare a quantized local 7B model's single-pass score with a frontier model's maximum-reasoning/tool-enabled score and call it a controlled head-to-head. Run both a constrained setting and each model's best supported setting, and label them separately.

## 5. Benchmark programme

### A. Raw model intelligence

1. General knowledge and multi-domain understanding.
2. Hard reasoning and multi-step problem solving.
3. Mathematics: exact arithmetic, algebra, proofs and word problems.
4. Science: factual recall, explanation, hypothesis testing and uncertainty.
5. Coding: code generation, bug fixing, repository-level changes and test repair.
6. Instruction following: exact constraints, format adherence and long instructions.
7. Multilingual performance, including English and Nigerian language use cases where test data is reliable.
8. Long-context retrieval and resistance to distractors.
9. Calibration: whether the model says "I don't know" when evidence is insufficient.
10. Multimodal tasks only for models that actually support the tested modality.

### B. Oracle-Arc system intelligence

1. Memory precision: does it recall only relevant, supported memories?
2. Memory recall: can it retrieve the right fact from a large personal knowledge base?
3. Correction and deletion: do corrected/deleted memories stay corrected/deleted?
4. Research quality: are sources current, credible and actually supportive of claims?
5. Planning: does it produce complete, ordered, feasible plans?
6. Tool use: correct tool selection, argument validity and bounded execution.
7. Prompt-injection resistance: malicious instructions in documents, web pages, memory and tool output must not override owner policy.
8. Verification: does it detect incorrect answers and incomplete actions?
9. Recovery: can it resume after timeout, crash or partial failure without duplicating side effects?
10. Privacy: does it avoid sending local private data to providers without explicit permission?
11. Latency and resource use: first-token latency, total completion time, memory use and tokens per second.
12. Cost and availability: per-task cost, rate limits, offline capability and failure behaviour.

### C. End-to-end task suites

Build a private, versioned Oracle-Arc test set with realistic tasks: understand a multi-document project, remember a user-approved decision, research a current question with citations, debug a small repository, plan a multi-step task, ask permission before a consequential action, recover after an interrupted action, and explain uncertainty honestly.

Each task needs a written rubric, deterministic checks where possible, expected evidence, risk level and pass/fail criteria. Keep a held-out set so the system cannot simply be tuned to public examples.

## 6. Reporting format

Every report must have three separate result tables:

- **Published external results:** copied with source, date and exact benchmark version.
- **Oracle-Arc measured results:** only tests actually run, with environment details.
- **Unmeasured / unavailable:** explicit gaps; never fill them with estimates.

Use per-category results rather than one blended "intelligence score". If an overall score is later created, publish its weights and show the category scores beside it.

## 7. Initial assessment

- **Raw-model position:** Qwen2.5-7B is a small, older-generation baseline. It is useful for local experimentation and privacy-oriented inference, but it should not be assumed to match the strongest current frontier models on difficult reasoning, coding, science or agentic work.
- **Oracle-Arc system position:** the architecture has promising foundations—local-first inference, owner authentication, persistent conversations, basic memory controls and tool-denial defaults—but the blueprint's advanced SPARK memory, independent verifier, durable execution, restricted worker and multimodal ORBITS are not yet implemented as complete capabilities.
- **No measured Oracle-Arc ranking exists yet:** no live benchmark run has been completed against the frontier set. We must not assign Oracle-Arc a numerical rank or claim it beats a named model.

## 8. Recommended next engineering steps

1. Identify the exact Ollama model artifact, digest, quantization, runtime and target hardware.
2. Add a reproducible benchmark runner with pinned datasets, prompts, scoring scripts and result manifests.
3. Run the same raw-model task suite against the current Qwen baseline and accessible frontier APIs.
4. Add a provider-neutral model gateway so Oracle-Arc can route tasks to local or optional remote models under explicit privacy rules.
5. Implement SPARK retrieval and the VERIFIER before claiming system-level superiority.
6. Publish a scorecard after each benchmark run, including failures and uncertainty—not just wins.

## Sources

- Qwen, Qwen2.5 model release and benchmark tables: https://qwen.ai/blog?id=qwen2.5-llm
- Qwen2.5 technical report and instruction-model evaluations: https://qwenlm.github.io/blog/qwen2.5-llm/
- Ollama Qwen2.5 model catalogue and available sizes: https://registry.ollama.com/library/qwen2.5
- Artificial Analysis Intelligence Index v5 announcement (27 October 2026): https://artificialanalysis.ai/articles/announcing-artificial-analysis-intelligence-index-v5
- Artificial Analysis Intelligence Index methodology: https://artificialanalysis.ai/methodology/intelligence-benchmarking
- OpenAI GPT-6 Astra release information: https://openai.com/index/gpt-6-astra/

**Status:** comparison framework created; no new benchmark scores have been generated by Oracle-Arc in this document.
