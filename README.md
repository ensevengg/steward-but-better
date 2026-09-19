# Steward But Better

An evidence-review prototype for racing incidents. It preserves real telemetry,
checks explicit rule conditions, and recommends a sanction only when the supplied
reviewed evidence supports the implemented pattern. Missing facts remain unknown.
The original submission remains on `OG/hackathon-v1`.

**[Video proof](docs/proof/steward-demo.webm) · [Validation and findings](docs/validation.md)**

## What changed

- Native FastF1 samples reach detection before display downsampling. Positions use
  bounded backward joins and explicit units; estimated G cannot establish blame.
- Reviewed, event-dated rule bundles retain exceptions. Unknown seasons and
  unsupported responsibility patterns abstain instead of borrowing other rules.
- Penalty recommendations require verified observations for each necessary
  condition. Conflicts, external causes and shared contribution trigger review.
- Optional OpenCode structured model review checks evidence and alternatives. It
  can downgrade a recommendation, never invent evidence or increase a sanction.
  Configured-provider errors require review; without configuration the deterministic
  policy operates with model review visibly disabled.
- SQLite transactions persist the packet, case queue and audit trail. Leases,
  retries, idempotent IDs and version checks protect concurrent operations.
- A restrained responsive workspace shows the timeline, evidence provenance,
  rule conditions, source documents, uncertainty and durable case history.

## Run locally

Use Python 3.11–3.13, Node 20.11+ and uv. From the repository root:

```sh
uv sync --frozen --group dev
uv run --frozen uvicorn src.brain.server:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd src/ui
npm ci
npm run build
npm start -- --hostname 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000` and choose **Load São Paulo 2025 study**. This replays a
committed window of real FastF1 data and queues two distinct assessments. No model
key or fresh telemetry download is needed. A lap in the session title describes
the selected window; unavailable per-driver lap/rank/gap values remain unknown.

Environment names are in [.env.example](.env.example). Backend configuration can
be loaded with uvicorn's `--env-file .env`; Next.js reads `src/ui/.env.local` or the
launch environment. State defaults to `data/steward.sqlite3`, outside Git. Run one
backend process against persistent local storage. This is a local prototype;
shared public deployment needs authentication and operational storage planning.

## São Paulo result and its limits

For Piastri/Antonelli, lap 6, turn 1 on 9 November 2025:

| Input | Result |
| --- | --- |
| Reviewed reconstruction of FIA corrected document 68 | **10 seconds recommended**, matching the official time penalty |
| Same retrospectively selected window, public telemetry only | **Insufficient evidence**, no sanction |
| Native anomaly detector over the downloaded three-driver lap window | **0 candidates**; it missed this collision |

The reconstruction includes explicit reviewer assumptions about absent mitigating
or external factors. It tests rule application, **not independent historical
prediction or video perception**. Expected outcomes live in a separate evaluator
file and never enter the assessor or model payload. Two official penalty points
are recorded for comparison, but this prototype does not recommend points.

The reviewed runtime policy currently covers a narrow inside-overtake collision
pattern and selected track-excursion exceptions for **2025 races from May 14 through
December 31**. Other dates, sessions and responsibility patterns require review.
This deliberate scope is smaller than the legacy OCR corpus; broad automated
stewarding accuracy has not been established.

## Optional model review through OpenCode

Use a dedicated empty working directory for the OpenCode server, not this repo:

```sh
opencode serve --pure --hostname 127.0.0.1 --port 4096
```

Configure the backend's `STEWARD_OPENCODE_URL`, `STEWARD_MODEL_PROVIDER` and
`STEWARD_MODEL_ID` explicitly. Authenticate the selected provider in OpenCode.
If server authentication is enabled, pass `OPENCODE_SERVER_PASSWORD` to both
processes. No provider credential belongs in this repository or the browser.

The adapter uses `POST /session` and `POST /session/{id}/message`, JSON Schema
output, denied execution permissions and disabled tools. Each review has its own
session and is aborted/deleted afterward. The payload omits case identity,
source URLs, expected penalties and historical titles; driver codes are replaced
with neutral labels. Narrative evidence is still untrusted and may retain clues.
It is validated against actual evidence IDs and the applicable rule bundle.

```sh
uv run --frozen python -m scripts.provider_smoke --provider YOUR_PROVIDER --model YOUR_MODEL
```

**Live validation limitation:** the installed OpenCode 1.18.31 server was reachable,
but the tested free models returned a free-tier access error, including for a
minimal connectivity prompt. The available OpenAI environment credential was also
rejected. Successful live structured review is therefore not claimed. Mocked
protocol tests and live failure handling are covered; provider access must be
resolved before enabling model review for real decisions.

## Replay and API

To download/replay a fresh native window (requires network):

```sh
uv run --frozen python -m src.telemetry.live_simulator --year 2025 --gp "Sao Paulo" --start-lap 6 --drivers PIA ANT LEC --export data/sao-paulo-native.json
```

Use `--no-send` for acquisition only and `--pace 0` for an unpaced replay. Fresh
replays get unique session IDs. Ordered retries never report a failed delivery as
accepted. The detector is a candidate heuristic, not a collision recognizer.

FastAPI's `/docs` describes the new strict contracts. `POST /telemetry` persists
and queues atomically; `POST /cases` accepts a reviewed `CaseInput`; `GET /state`
and `/cases/{id}` expose live state and detailed history. `PATCH /cases/{id}` needs
`expected_version`. Evidence is immutable per case ID: corrections use a new ID.
`POST /verdict` assesses a typed case synchronously without persisting it.
`POST /studies/sao-paulo` launches the explicit historical study.

This is an API schema change from main: legacy flattened packets and free-text
judging input are rejected. The UI is a proxy; the backend owns all durable state.
Old FAISS/OCR tools are research utilities, installable with `uv sync --group indexing`;
they are not the runtime source of legal applicability or sanctions.

## Validation

```sh
uv run --frozen ruff check src tests scripts
uv run --frozen pytest -q
uv run --frozen python -m scripts.benchmark
cd src/ui
npm run typecheck
npm run lint
npm run build
```

With both production services running, from the repository root:

```sh
uv run --frozen playwright install ffmpeg
uv run --frozen python scripts/browser_check.py --channel msedge
```

On Linux/CI install Chromium with `playwright install --with-deps chromium` and
pass `--channel ""`. The script records the real workflow and a separately labelled
injected-outage check. Automated CI repeats Python, UI and browser checks; external
model access is an explicit opt-in smoke test, not a silently mocked CI success.
