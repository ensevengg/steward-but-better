# Provider research for continuous race monitoring

Reviewed September 20, 2026. Recommendation: evaluate **direct Groq and Cerebras**
first, using the same outcome-hidden incident cases. Choose on false penalties,
abstention quality and burst latency. No provider has passed a live quality
evaluation in this workspace; this is a shortlist, not a measured winner.

## Size the right workload

At an illustrative four samples per second, 20 cars produce 80 samples/second,
4,800/minute and 576,000 over two hours. With 24 cars, that becomes 691,200.
Those samples belong in local numerical processing and rolling buffers, not
individual LLM requests. The branch processes every native sample, throttles
display updates separately, and runs judging on a durable background queue.
Normal telemetry packets do not call a model. Telemetry anomalies cannot become
verified contact, overlap or fault merely by asking an LLM to explain them.

The desired model workload is a bounded evidence package per incident, with a
second review only when it can resolve a specific uncertainty. Multi-car event
grouping, evidence-version caching, token budgeting and provider-aware admission
control are still future work; current detector cooldowns are per driver.

## Options

| Provider | Relevant capacity and trade-off | Recommendation |
| --- | --- | --- |
| Direct Groq | GPT-OSS 120B lists Developer limits of 1,000 RPM / 250K TPM and $0.15 input / $0.60 output per million tokens. 20B lists $0.075 / $0.30. Account limits still apply. | First paid serverless candidate; compare both model sizes for missed exceptions and unsupported penalties. |
| Direct Cerebras | GPT-OSS 120B Developer lists 1,000 RPM, 1M uncached TPM and 3M total TPM. Output reservations can consume quota before actual generation. | Strong alternative for bursts; verify the actual account's access and pricing before selection. |
| Together dedicated endpoints | Dedicated GPU capacity, GPU-minute billing and no request limit beyond hardware capacity; provisioning and utilization become your responsibility. | Consider after measuring sustained demand or when reserved capacity is required. |
| Fireworks on-demand deployment | Dedicated model deployments with configurable GPU capacity and scaling. | Another reserved-capacity option; compare cold starts, minimum replicas and total race-day cost. |
| Self-hosted vLLM | OpenAI-compatible serving on your own compute; no external provider RPM quota, but memory, concurrent tokens and GPU throughput remain finite. | Useful with suitable existing GPUs or a privacy requirement; benchmark hardware before promising throughput. |
| Direct Gemini | Project/model/tier limits; a separate option when synchronized visual evidence becomes part of the workflow. | Evaluate multimodal evidence extraction separately from sanction policy. |

Primary sources: [Groq models and prices](https://console.groq.com/docs/models),
[Groq rate limits](https://console.groq.com/docs/rate-limits),
[Cerebras quotas](https://inference-docs.cerebras.ai/support/rate-limits),
[Together dedicated endpoints](https://docs.together.ai/docs/dedicated-endpoints/overview),
[Fireworks deployments](https://docs.fireworks.ai/guides/ondemand-deployments),
[vLLM serving](https://docs.vllm.ai/en/latest/serving/online_serving/),
[Gemini limits](https://ai.google.dev/gemini-api/docs/rate-limits).
Prices and advertised limits are not account-specific throughput guarantees.

OpenRouter is not inherently unable to support this workload. Its free-model
quotas and upstream capacity restrictions matter; a paid route is a different
capacity question. Going direct simplifies quota ownership and troubleshooting,
but does not remove limits. See [OpenRouter's limits](https://openrouter.ai/docs/api_reference/limits).

As an illustrative budget, 40 incidents with two calls each, 3,000 input tokens
and 600 billed output tokens per call cost about **$0.0648** at the listed Groq
120B rates. This is arithmetic, not measured usage: reasoning, retries, longer
evidence and visual processing can substantially increase it. Provider choice
should follow measured tokens and peak demand, not the number of driver cards.

## Reliability and accuracy gates before enabling a provider

1. Run outcome-hidden collision and clean-overtake cases, including ambiguous
   geometry, shared contribution, external causes and conflicting evidence.
   Report false penalties, missed incidents, abstention and sanction agreement
   separately. The existing 11-case reconstruction regression is insufficient.
2. Require supported JSON Schema output, then independently validate evidence IDs,
   rule applicability and exceptions. Both [Groq](https://console.groq.com/docs/structured-outputs)
   and [Cerebras](https://inference-docs.cerebras.ai/capabilities/structured-outputs)
   offer constrained output; valid JSON does not establish factual correctness.
3. Measure concurrent restart incidents, p95 end-to-end latency, schema failures,
   reasoning tokens, cost and 429 behavior. Use bounded concurrency, token budgets,
   Retry-After/backoff, idempotent evidence versions and an explicit pending state.
   A timeout must never imply either guilt or exoneration.
4. Keep numerical processing and the field display independent of provider health.
   The branch tests ingestion of 60 full-field packets while judging is blocked.
   A direct HTTP provider adapter should replace the coding-agent intermediary
   once a provider is selected; preserve the existing grounding and downgrade-only
   sanction boundary.

The existing optional OpenCode adapter remains disabled by default. The local
server was reachable, but tested provider authentication/access failed. Exposing
another port cannot grant upstream model access. No direct provider migration or
successful live LLM assessment is claimed by this UI/telemetry revision.
