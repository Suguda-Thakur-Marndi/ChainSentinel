# RiskWise 2.0 — Phase 10 Step 1: AWS Bedrock + Claude Foundation

## Executive Summary

Phase 10 Step 1 establishes a production-safe, enterprise-grade LLM provider abstraction for AWS Bedrock Runtime and Anthropic Claude foundation models (`anthropic.claude-sonnet-4-6`).

> [!IMPORTANT]
> **Phase Boundary Enforcement**:
> **No Phase 9 agent behavior was replaced with Claude in Step 1.**
> Deterministic risk scoring, ML prediction boundaries, scenario generation, decision synthesis, human approvals, and operational actions remain 100% governed by Phase 1–9 logic. This step builds the internal provider abstraction, security boundary, error taxonomy, retry infrastructure, observability, and test mock foundation only.

---

## 1. Architecture

The system introduces a provider-neutral abstraction layer that decouples application services and future agent nodes from cloud provider SDKs:

```
Application (Internal Services / Future Agents)
      ↓
LLMProvider (Abstract Base Class)
      ↓
BedrockLLMProvider (AWS Bedrock Runtime Adapter)  |  DeterministicMockLLMProvider (Tests Only)
      ↓
boto3 bedrock-runtime client
      ↓
Anthropic Claude (anthropic.claude-sonnet-4-6 via Messages API)
```

- **Application Decoupling**: Business logic and agent graphs interact exclusively with the `LLMProvider` interface (`invoke()`, `stream()`) using strongly typed contracts (`LLMRequest`, `LLMResponse`).
- **boto3 Isolation**: `boto3` and `botocore` dependencies are strictly confined to the `BedrockLLMProvider` adapter. No agent node imports or interacts directly with AWS SDK clients.
- **Internal Service Boundary**: No public LLM API endpoint is exposed. The LLM provider is strictly an internal service; external API callers cannot directly select models, modify system prompts, or tune parameters.

---

## 2. AWS Credential Strategy

The provider architecture strictly enforces AWS standard SDK credential resolution:

```
EC2 / ECS IAM Task Role
      ↓
AWS SDK Credential Provider Chain
      ↓
boto3 bedrock-runtime client
      ↓
AWS Bedrock
```

- **Production**: Operates using the IAM role attached to the EC2 instance or ECS task definition.
- **Local Development**: Resolves via standard local AWS credential profiles (`~/.aws/credentials`) or standard environment variables (`AWS_PROFILE`, `AWS_REGION`).
- **Zero Secrets**:
  - No AWS access keys or secret keys in source code or version control.
  - No `BEDROCK_API_KEY` or `ANTHROPIC_API_KEY` introduced.
  - No credential printing or logging under any circumstance.

---

## 3. AWS Region & Claude Model Configuration

Configuration is managed centrally via `app.core.config.Settings`:

| Setting | Default Value | Description |
| :--- | :--- | :--- |
| `AWS_REGION` | `ap-southeast-2` | Primary AWS deployment region (Sydney) |
| `BEDROCK_REGION` | `None` (falls back to `AWS_REGION`) | Optional dedicated region override for Bedrock calls |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-6` | Primary Claude model identifier |
| `BEDROCK_ALLOWED_MODELS` | `["anthropic.claude-sonnet-4-6", "anthropic.claude-3-5-sonnet-20241022-v2:0", "anthropic.claude-3-5-haiku-20241022-v1:0"]` | Safe allowlist of approved foundation models |
| `BEDROCK_MAX_TOKENS` | `4096` | Upper bound for token generation |
| `BEDROCK_TIMEOUT_SECONDS` | `30.0` | Bounded execution timeout |
| `BEDROCK_MAX_RETRIES` | `3` | Maximum automatic retries for retryable failures |
| `BEDROCK_BACKOFF_BASE_SECONDS` | `0.5` | Exponential backoff base delay |
| `BEDROCK_BACKOFF_MAX_SECONDS` | `4.0` | Exponential backoff cap |
| `LLM_PROVIDER` | `bedrock` | Provider backend (`bedrock` or `mock`) |

Configuration startup validation verifies that `BEDROCK_MODEL_ID` is non-empty and present in `BEDROCK_ALLOWED_MODELS` without initiating network calls to AWS.

---

## 4. Model Allowlist Enforcement

To prevent arbitrary model invocation, model spoofing, or unexpected billing surges, the provider validates model IDs against the configured allowlist prior to any external network request:

```
Untrusted Request -> validate_model_allowed() -> Allowlist Checked -> Bedrock Runtime
                           ↓ (if unapproved)
                 LLMConfigurationError (Fails Closed)
```

Requests specifying an unapproved model ID immediately raise `LLMConfigurationError` and abort execution before contacting AWS.

---

## 5. Strongly Typed Request & Response Contracts

### `LLMRequest`
- `model_id: str`: Target foundation model.
- `messages: List[LLMMessage]`: Chronological conversational messages with roles `user` or `assistant`.
- `system_prompt: Optional[str]`: Bounded system prompt (maximum 64 KB).
- `temperature: Optional[float]`: Bounded in `[0.0, 1.0]`.
- `max_tokens: int`: Bounded between 1 and 8,192.
- `stop_sequences: Optional[List[str]]`: Bounded stop token list.
- `organization_id: Optional[str]`: Tenant attribution identifier.
- `request_id / correlation_id / trace_id`: Distributed tracing identifiers.
- `agent_run_id / execution_id`: Future agent execution tracing identifiers.
- `metadata: Dict[str, Any]`: Sanitized audit and attribution metadata.

### `LLMResponse`
- `provider: str`: Identifier (`bedrock` or `mock`).
- `model_id: str`: Identifier of the model fulfilling the request.
- `text: str`: Normalized text completion.
- `input_tokens: Optional[int]`: Verified prompt tokens (never estimated).
- `output_tokens: Optional[int]`: Verified completion tokens (never estimated).
- `total_tokens: Optional[int]`: Sum of input and output tokens.
- `stop_reason: Optional[str]`: Completion reason (`end_turn`, `max_tokens`, etc.).
- `latency_ms: float`: Roundtrip execution latency.
- `metadata: Dict[str, Any]`: Sanitized provider metadata.

### `LLMStreamChunk`
- `text: str`: Incremental text fragment.
- `index: int`: Zero-based chunk counter.
- `stop_reason: Optional[str]`: Provided on final chunk.
- `output_tokens: Optional[int]`: Incremental token usage if provided.

---

## 6. Error Taxonomy & Classification

Exceptions integrate with the RiskWise `AppError` framework and deterministic error classifications:

```
                  AppError (Base Application Exception)
                           ↓
                     LLMBaseError
     ┌─────────────────────┴─────────────────────┐
Non-Retryable (Fail-Closed)                 Retryable
├── LLMValidationError (400)               ├── LLMThrottlingError (429)
├── LLMAuthenticationError (401)           ├── LLMTimeoutError (504)
├── LLMAuthorizationError (403)            └── LLMTransientError (503)
├── LLMProviderError (502)
├── LLMResponseError (502)
└── LLMConfigurationError (500)
```

### Exception Mapping (`map_boto_exception`)
Raw `boto3` / `botocore` exceptions are deterministically mapped and sanitized:
- `ThrottlingException` / `RequestLimitExceeded` / HTTP 429 → `LLMThrottlingError`
- `AccessDeniedException` / HTTP 403 → `LLMAuthorizationError`
- `UnrecognizedClientException` / `NoCredentialsError` / HTTP 401 → `LLMAuthenticationError`
- `ValidationException` / `ParamValidationError` / HTTP 400 → `LLMValidationError`
- `ReadTimeoutError` / `ConnectTimeoutError` / HTTP 504 → `LLMTimeoutError`
- `EndpointConnectionError` / HTTP 503 → `LLMTransientError`
- All raw error strings are filtered through credential scrubbers before logging or serialization.

---

## 7. Retry Infrastructure & Timeout

Bedrock calls execute with bounded exponential backoff and jitter via `LLMRetryPolicy`:

$$\text{delay} = \min(\text{max\_delay}, \text{base\_delay} \times 2^{(\text{attempt} - 1)}) \times (0.5 + 0.5 \times \text{random}())$$

- **Retry Budget**: Maximum 3 retries (4 total attempts) by default.
- **Retry Eligibility**:
  - **Retryable**: Throttling (`429`), temporary network drops (`503`), gateway timeouts (`504`).
  - **Non-Retryable**: Authentication failures (`401`), authorization denials (`403`), validation errors (`400`), unapproved models (`500`).
- **Timeout Guarantees**: Calls enforce strict read/connect timeouts (`BEDROCK_TIMEOUT_SECONDS = 30.0s`).

---

## 8. Observability & Token Telemetry

Every Bedrock execution produces an `LLMTelemetryRecord`:
- **Attribution**: Organization ID, request ID, correlation ID, trace ID, agent run ID.
- **Performance**: Millisecond latency, attempt count, completion status (`SUCCESS` / `FAILED`).
- **Token Counts**: Real tokens reported by Bedrock Runtime (`input_tokens`, `output_tokens`, `total_tokens`). If usage is absent, fields remain `None` rather than fabricated.
- **Privacy & Redaction**:
  - Full prompt and response texts are never logged.
  - Safe 16-character SHA-256 fingerprints are logged for prompt structure (`safe_prompt_fingerprint`) and response content (`safe_response_fingerprint`).
- **Metrics**: Thread-safe `LLMMetricsCollector` aggregates invocation totals, successes, failures, throttles, timeouts, and latency distributions.

---

## 9. Security Boundaries & Input Sanitization

- **Prompt Injection Defense**: Evaluates inputs against adversarial jailbreak patterns (`ignore previous instructions`, `system prompt:`, `you are now unrestricted`, and structural delimiters `<system>`, `[INST]`, `<|im_start|>`).
- **Tenant Context Validation**: Confirms that `organization_id` does not contain cross-tenant delimiter injections.
- **Metadata Scrubbing**: Recursively redacts passwords, tokens, API keys, and session cookies from request metadata.
- **Error Redaction**: Strips AWS access keys, secret keys, session tokens, and bearer tokens from error strings.

---

## 10. Test Strategy & Mock Provider

To ensure isolated, zero-cost, and deterministic test execution:
- **`DeterministicMockLLMProvider`**:
  - Zero network or AWS credentials required.
  - Produces deterministic, reproducible text completions based on prompt hash.
  - Simulates rate limiting (`simulate_throttling`), timeouts (`simulate_timeout`), and injected exceptions (`inject_failure`).
  - Records requests for assertion verification (`recorded_requests`).
  - Supports incremental streaming chunk tests.
- **Boto3 Mocking**: Unit tests for `BedrockLLMProvider` inject mocked `bedrock-runtime` clients via dependency injection without live AWS calls.
- **Coverage**: 95 focused unit tests in `tests/test_phase10_step1_bedrock_foundation.py`.

---

## 11. Known Limitations

- **Streaming Architecture**: Provider-level streaming abstraction (`stream()`) is implemented. UI streaming consumers will be wired in future frontend integration phases.
- **Foundation Scope**: Claude is not connected to Phase 9 agents in this step.
- **Billing Calculation**: Token counts are captured; automated cost calculation tables/billing tiers belong to future commercial modules.
