# Evidence-first rebuild: findings and validation

This branch reduces the opportunity for unsupported judgments by demanding
reviewed facts, retaining exceptions and separating incident discovery from fault.
It does not establish a measured reduction in real-world false-positive rates.
That needs a larger independently annotated evaluation set.

## Full-field correction

The primary screen now keeps all 20 driver cards visible at 1440×900 and
1366×768, with independently scrolling reports on the right. Mobile has field
and report tabs. Opening a case leaves native sample counts advancing.

The default native replay covers the entire race and all entrants. A fresh
São Paulo full-race processor run handled **421,220 native samples**, yielding
**4,933 display packets** across **20 drivers**. It produced **zero candidates**;
this demonstrates processing coverage, not successful incident detection.
All 4,933 packets subsequently passed through the Next.js proxy and backend;
SQLite retained sequence 4,932 / FINISHED with all 421,220 samples accounted for
([result](proof/full-race.json)). This run exposed an invalid native gear value of
17; invalid gear/RPM/DRS now stay unknown instead of rejecting the whole packet.
The bundled demo is a separate 61-second excerpt with 91 display packets.

The live bridge consumes a growing FastF1 recorder file, including compressed
car/position messages and timing deltas. Tests cover partial writes, stale cars,
missing/invalid channels, causal position matching, 24-driver processing and a
late incident, plus continuous full-field ingestion while the judge is blocked.
Real authenticated live-race connectivity remains unverified. Provider selection
and remaining capacity work are detailed in [provider research](providers.md).

## Changes that matter for accuracy

| Previous weakness | Implemented response | Remaining limit |
| --- | --- | --- |
| G-force, proximity and braking estimates treated as legal evidence | Telemetry produces anomaly candidates; spatial predicates require reviewed non-telemetry evidence | No independent contact/overlap perception |
| Sampling before detection could miss short events | Every native sample reaches detection; display packets are throttled separately | Public feed is sparse and normalized |
| Future interpolation and fabricated missing values | Backward joins bounded to 0.3 seconds; missing values stay unknown; causal derivatives | G remains an estimate, not a crash sensor |
| Fixed-frequency distance fallback | Integrate actual timestamps; holes invalidate subsequent distance | Distance origins cannot align different cars |
| Broad retrieval could mix seasons and omit exceptions | Small reviewed bundle selected by event date/type, with all relevant exceptions retained | Runtime coverage deliberately limited to a 2025 subset |
| LLM could provide plausible wording without improving evidence checks | Structured per-condition review, grounded IDs, alternative explanation, no power to promote guilt | Successful live model response remains unverified here |
| Delayed results could replace newer UI state | Durable queue, fenced leases and distinct session/case state | Replay production itself is not resumable after shutdown |
| Flashes, forced movement and weak mobile layout | Restrained styling, sequential polling, stable scroll, mobile tabs, explicit source/uncertainty panels | Keyboard and screen-reader usability need broader user testing |

## São Paulo 2025

The official corrected decision is [FIA document 68](https://www.fia.com/system/files/decision-document/2025_sao_paulo_grand_prix_-_corrected_race_-_infringement_-_car_81_-_causing_a_collision_with_car_12_in_turn_1.pdf).
It records Piastri's collision with Antonelli at turn 1 on lap 6, the inside
attempt, insufficient overlap and braking lock-up. The official time penalty was
10 seconds, with two penalty points. The reconstruction reproduces the **10-second
time recommendation**; penalty points are deliberately left for separate review.

Input observations do not include the expected penalty. However, they come from
the published decision, with four explicitly labelled reviewer assumptions about
negative context. This is answer-informed reconstruction, not a blind prediction.
Removing any of the nine required observations prevents a penalty recommendation.
The corresponding telemetry-only case has no qualifying spatial facts and returns
**INSUFFICIENT_EVIDENCE**.

FastF1 3.8.3 loaded **1,797 native samples** (599 each for PIA, ANT and LEC) from
the selected lap window. A fresh replay delivered **141 ordered packets** through
the Next.js proxy to SQLite and ended at sequence 140 / FINISHED. The heuristic
detector produced **zero candidates**: it missed the known collision. The study's
incident window is therefore explicitly selected retrospectively, not presented
as an automatic discovery. Its committed subset contains 576 native samples and
45 display packets, with acquisition provenance and source-export hash.

The applicable guidance is the [2025 Driving Standards](https://www.fia.com/sites/default/files/f1_driving_standards_guidelines_version_4.1_feb_20_2025.pdf)
and [May 2025 Penalty Guidelines](https://www.fia.com/sites/default/files/2025_f1_guidelines_penalty_points_overview_-_14_may_clean_0.pdf).
The runtime contains authored synopses, source links and a bundle hash; it does
not claim the guidance is an exhaustive automatic substitute for the regulations
or stewards' discretion. Applicability is limited to May 14–December 31, 2025.

## Validation record

Local environment: Windows, Python 3.13.15, locked uv dependencies, Next.js 16.1.6,
production UI build, headless Microsoft Edge driven by Playwright.

| Check | Result |
| --- | --- |
| `uv sync --frozen --group dev` in repository `.venv` | Passed after Windows access was cleared |
| Python regression suite | **106 passed** |
| Ruff over `src`, `tests`, `scripts` | Passed |
| TypeScript, ESLint, Next.js production build | Passed |
| Reconstruction and missing-evidence benchmark | **11/11 regression expectations passed**; not an accuracy score |
| Fresh native telemetry through UI proxy/backend | 1,797 samples processed, 141 packets delivered, FINISHED persisted |
| Production browser workflow | Seven checks, five viewport widths; [machine-readable results](proof/browser-results.json) |
| Actual provider calls through local OpenCode port 4096 | Requests reached server; provider-side access errors, no successful review claimed |

Tests cover causal physics, missing channels, timestamp/unit validation,
candidate retention before downsampling, exceptions, disputed evidence, identity
swaps, inappropriate seasons/sessions, citation grounding, invalid model output,
timeouts, retries, durable restart, duplicate/out-of-order packets, transaction
rollback, concurrent claims, lease fencing, version conflicts and case history.
Older chunking/index-integrity regression checks remain. This is not exhaustive
coverage of every external FastF1 path or the legacy OCR/index creation tools.
Third-party pandas/NumPy and Starlette test-client deprecation warnings remain;
they do not fail the tests.

The [recorded browser proof](proof/steward-demo.webm) exercises the actual UI,
proxy, backend worker, SQLite and assessor. It shows all 20 drivers, advancing telemetry during sidebar review, rules,
close/reopen persistence, telemetry-only abstention and mobile layouts. The two
judging cases are explicitly submitted test inputs, not automatically detected
incidents. Only the final outage segment injects an HTTP 503 to verify the
visible warning, retained case and recovery. It is not race footage or proof of
video perception. The browser script is committed and CI records its own artifact.

OpenCode 1.18.31 was started with the documented server command in an empty
directory. `opencode/mimo-v2.5-free` and `opencode/big-pickle` returned a free-tier
access error. A minimal prompt without our custom system/schema also failed.
The available OpenAI environment credential was rejected. No key or provider
error payload is committed. The optional adapter remains disabled by default;
when configured, errors explicitly downgrade a proposed penalty to review. A
working authenticated or local provider is required to complete live validation.
The adapter follows the [OpenCode server API](https://opencode.ai/docs/server/)
and validates structured output rather than trusting JSON-shaped text. Schema
compliance alone is not factual correctness; see the [OpenAI structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## What should come next

1. Build an independently reviewed, outcome-hidden set of collisions, clean
   overtakes, forced-off incidents and ambiguous cases across circuits. Track
   false penalties, missed incidents, abstention and sanction agreement separately.
2. Add synchronized onboard/broadcast evidence with human-reviewed contact,
   overlap, control and alternative-cause annotations. Public position feeds
   cannot substitute for this; [FastF1's maintainer explanation](https://github.com/theOehrly/Fast-F1/discussions/491)
   describes the normalized position data.
3. Improve candidate recall using independently labelled windows. The São Paulo
   miss must remain a regression target, not be hidden with an event-specific trigger.
4. Expand reviewed rule coverage with primary regulations, versions, event notes
   and sanction context. Unknown applicability should continue to abstain.
5. Compare authenticated providers on that held-out set before choosing one.
   Measure errors and latency, not persuasive wording. Keep evidence validation
   and the final sanction boundary independent of the model.

## Branch and compatibility

Work starts from main `b8f567c` on `accuracy/evidence-first-stewarding`. Main's
scoped, explanatory commit style is retained. `OG/hackathon-v1` is not modified.
The typed telemetry/case API replaces the old flattened packet contract; external
clients must migrate. Existing JSON dashboard state is not imported into SQLite.
