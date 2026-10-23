# ORION --- Master Technical Project Documentation

**Project:** ORION, a general-purpose autonomous computer-use agent\
**Academic context:** Final-year CSE / AIML major project\
**Primary platform:** Windows desktop\
**Core budget target:** ₹0, using suitable open-source tools and local
execution where feasible\
**Status:** Proposed design specification; all capabilities and results
must be validated before being claimed.

## 1. Executive summary

ORION is a general-purpose AI computer-use agent that accepts high-level
user goals and coordinates actions across real desktop applications,
browser environments, local files, operating-system interfaces, and
supported digital tools. It is not defined by voice interaction: voice,
text, keyboard shortcuts, and compatible alternative input devices are
simply possible ways to interact with it.

The intended user experience is outcome-oriented. The user delegates a
result; ORION interprets the goal, builds a plan, chooses tools,
observes the current environment, performs permitted actions, checks the
resulting state, recovers from failures where safe, and reports what was
actually achieved. It must never treat an issued command as proof that
the task succeeded.

The proposed technical contribution is to investigate whether learned
visual grounding and action-outcome prediction can improve the
reliability of computer-use agents on unfamiliar or changing interfaces.
The complete product combines: - Agent orchestration and
dependency-aware planning. - Hybrid computer perception using UI
metadata, browser DOM, OCR, and visual evidence. - A typed tool registry
for Windows, browsers, files, documents, and configured services. -
Persistent task state, checkpoints, and resumable workflows. -
Preconditions, postconditions, failure detection, recovery, and
replanning. - Machine-learning training and evaluation pipelines. -
Permission-aware execution, privacy controls, audit logs, and
cancellation. - Reproducible benchmarks against deterministic and
pretrained-model baselines.

This is a proposed design, not a claim that every capability already
exists. All feature, hardware, and performance claims must be supported
by actual implementation and testing.

## 2. Vision, objectives, and boundaries

### 2.1 Vision

Build an extensible digital operator that can pursue a wide range of
user-defined computer tasks, coordinate multiple applications, adapt to
changing application states, and verify outcomes while respecting user
authority.

### 2.2 Objectives

1.  Interpret high-level goals and constraints.
2.  Convert goals into executable plans with dependencies and completion
    criteria.
3.  Select supported tools dynamically through a typed registry.
4.  Observe the real environment before and after actions.
5.  Execute tasks through documented Windows, browser, and application
    interfaces.
6.  Detect unexpected states and failed actions.
7.  Recover or replan when safe; ask for help when uncertain.
8.  Persist progress and resume interrupted tasks only after
    revalidating the environment.
9.  Provide an optional ML research contribution with a dataset,
    baseline, experiments, and measurable results.
10. Ship a testable Windows application with documentation and
    reproducible evaluation.

### 2.3 What ORION is

A general-purpose, goal-oriented computer-use agent. It may combine
language models, vision models, traditional ML, deterministic
automation, APIs, and explicit policies. It should support
cross-application workflows rather than only predefined commands.

### 2.4 What ORION is not

-   Merely a voice assistant or chatbot.
-   A fixed list of hardcoded commands.
-   An assurance of perfect or unrestricted autonomy.
-   A system that bypasses Windows security, UAC, authentication, or
    privacy controls.
-   A claim that every USB device can be controlled without a compatible
    driver or documented API.
-   A research contribution established merely by calling a pretrained
    model.
-   A system that treats model confidence as proof.
-   A product that silently performs consequential actions without the
    required authorization.

### 2.5 Design principles

**Outcome-oriented:** verify the result, not just the action.

**Hybrid intelligence:** use deterministic methods where precision is
available and ML where perception or prediction benefits from learning.

**Tool-agnostic:** expose capabilities through interchangeable, typed
interfaces.

**Local-first:** prefer local processing and storage where practical;
make external services explicit and configurable.

**Permission-aware:** enforce policy outside the language model.

**Transparent:** show task progress, active operations, failures, and
data use.

**Incremental:** implement and verify staged milestones.

**Evidence-driven:** report actual results, limitations, and failures.

## 3. Scope and use cases

### 3.1 Core scope

-   Windows desktop application shell.
-   Text input and task monitoring.
-   Optional speech input/output as modular features.
-   Structured intent representation and task planning.
-   Typed tool registry and safe execution runtime.
-   Windows UI Automation and browser automation.
-   Bounded file and document operations.
-   Persistent task state and logs.
-   Verification, error handling, cancellation, and recovery.
-   Model configuration and repeatable tests.

### 3.2 Advanced scope

-   Screenshot-based visual grounding and OCR.
-   Learned action-outcome prediction.
-   Model adaptation or fine-tuning if compute and licensing allow.
-   Demonstration-based workflow learning.
-   Local language-model integration.
-   Optional webcam-based head-pose or gesture input.
-   Specific assistive or USB device integrations through documented
    APIs.
-   Packaged Windows release and a research report.

### 3.3 Non-goals for the first release

-   Training a large vision-language model from scratch.
-   Universal compatibility with all applications.
-   Unattended purchases, messages, submissions, or important deletions.
-   Covert microphone or webcam recording.
-   Claiming ordinary webcam gaze tracking is equivalent to dedicated
    eye-tracking hardware.
-   Building a cloud service before the local prototype proves useful.
-   Presenting unimplemented features as working.

### 3.4 Representative scenarios

**Cross-application research:** search approved sources, compare
options, create a spreadsheet, prepare a report, verify outputs, and
list sources.

**Document workflow:** locate a source file, extract data, update a
review copy, preserve the original, and reopen the result to verify
content.

**Browser form preparation:** identify fields, fill only known or
user-approved information, detect validation errors, and stop before
submission when requested.

**Development workflow:** inspect a project, run tests, capture logs,
make authorized changes, rerun tests, and report the exact result.

**Unexpected UI state:** detect a dialog or layout change, reacquire the
target, replan, or stop if the next action is unsafe.

**Long-running workflow:** persist checkpoints, resume after
interruption only after re-observing the environment, and avoid
repeating uncertain external actions.

## 4. System architecture

ORION should be modular. The main subsystems are:

1.  **Interaction layer:** text, optional speech, keyboard, and
    supported alternative inputs.
2.  **Intent/context engine:** structured goal, constraints, missing
    information, and context.
3.  **Planner/orchestrator:** task graph, dependencies, checkpoints, and
    replanning.
4.  **Perception:** UI metadata, DOM, OCR, screenshots, and
    application-specific state.
5.  **Tool registry:** tool schemas, permissions, side effects, and
    result contracts.
6.  **Execution runtime:** invokes tools, enforces timeouts, handles
    cancellation, and records results.
7.  **Verification engine:** checks preconditions, postconditions, and
    goal completion.
8.  **Recovery engine:** classifies errors and chooses safe recovery or
    escalation.
9.  **State/memory store:** task records, checkpoints, user-approved
    preferences, and logs.
10. **Policy engine:** independent authorization and confirmation
    checks.
11. **Observability:** structured logs, traces, metrics, and
    user-visible progress.
12. **ML experiment pipeline:** data, annotation, training, model
    versioning, and evaluation.

### 4.1 Observe--plan--act--verify loop

1.  Receive the user's request.
2.  Convert it into a structured goal.
3.  Validate constraints, permissions, and missing information.
4.  Generate and validate a task graph.
5.  Select an eligible step.
6.  Observe the current relevant environment.
7.  Select and validate an action.
8.  Apply policy and permission checks.
9.  Execute the action through the selected tool.
10. Observe the resulting environment.
11. Evaluate postconditions.
12. Mark the step complete, recover, replan, ask the user, or stop
    safely.
13. Persist the checkpoint and update the user.
14. Continue until the goal is verified, blocked, cancelled, or safely
    stopped.

### 4.2 Illustrative control loop

``` python
async def run_task(task_id):
    task = await state_store.load_task(task_id)

    while not task.is_terminal:
        if task.cancel_requested:
            await executor.stop_interruptible_work(task)
            await state_store.mark_cancelled(task.id)
            break

        await policy.validate_task(task)
        step = planner.next_eligible_step(task)

        if step is None:
            await verifier.evaluate_goal_completion(task)
            break

        before = await perception.observe(step.context)
        decision = await planner.select_action(task, step, before)
        await policy.authorize_or_raise(decision)

        result = await executor.execute(decision)
        after = await perception.observe(step.context)
        check = await verifier.check(step, result, after)

        await state_store.record_result(task, step, result, check)

        if check.confirmed:
            planner.mark_complete(task, step)
        else:
            recovery = await recovery_engine.propose(
                task, step, result, after
            )
            await policy.validate_recovery(recovery)
            await planner.apply_recovery_or_replan(task, recovery)

        await state_store.save_checkpoint(task)

    return await state_store.load_task(task_id)
```

This is pseudocode, not a production implementation. A real
implementation must handle exceptions, cancellation races, timeouts,
concurrent tasks, durable writes, stale observations, and side effects.

## 5. Intent representation and task planning

### 5.1 Structured goal

A goal should include: - Unique task ID. - User's objective. -
Constraints and exclusions. - Required deliverables. - Authorized output
locations. - Completion conditions. - Risk and confirmation
requirements. - Missing information. - User-approved context. - Current
status and evidence.

Illustrative JSON:

``` json
{
  "goal_id": "example-task",
  "objective": "Prepare a comparison report",
  "constraints": {
    "preserve_source_files": true,
    "external_submission_allowed": false
  },
  "deliverables": ["comparison.xlsx", "summary.docx"],
  "completion_checks": [
    "both files exist",
    "required spreadsheet columns exist",
    "report contains summary and source references"
  ]
}
```

Actual paths, accounts, and values must come from the user or a verified
environment; they must not be invented.

### 5.2 Task graph

Represent tasks as a dependency graph. Use explicit branch and loop
nodes when the workflow is conditional.

Each step should include: - ID and description. - Dependencies. -
Input/output schemas. - Required tool capability. - Preconditions and
postconditions. - Risk classification. - Timeout and retry policy. -
Idempotency classification. - Status. - Evidence references. - Error and
recovery metadata.

Suggested statuses: `pending`, `ready`, `running`, `waiting_for_user`,
`blocked`, `succeeded`, `failed`, `cancelled`, `skipped`,
`needs_review`.

### 5.3 Planner responsibilities

The planner may propose a plan, but it must not execute unchecked model
output. Validate schemas, dependencies, tool existence, permissions, and
required inputs first.

The planner should: - Detect contradictory or impossible steps. -
Identify missing prerequisites. - Prefer reversible actions before
irreversible ones. - Minimize unnecessary actions. - Run independent
tasks in parallel only when safe. - Insert checkpoints before
consequential actions. - Replan after verified failures or changed user
instructions. - Never invent tool capabilities.

### 5.4 Hierarchical planning

Separate: - **Goal planner:** milestones and deliverables. - **Step
planner:** next action and required evidence. - **Tool executor:**
validated concrete tool invocation. - **Verifier:** checks action and
goal conditions. - **Policy engine:** authorizes or blocks actions
independently.

Possible metrics: plan validation rate, invalid tool-call rate,
unnecessary actions, replan frequency, task completion rate,
user-intervention rate, and end-to-end latency.

## 6. Computer perception and visual grounding

### 6.1 Hybrid perception

Prefer the most reliable source available: 1. Documented semantic UI or
application API. 2. Browser DOM or accessibility metadata. 3. OCR and
layout analysis. 4. Screenshot-based visual grounding. 5. Re-observation
and verification before acting.

Screenshots alone can be brittle; semantic APIs alone can be incomplete.
The hybrid approach allows fallback while preserving explicit confidence
and evidence.

### 6.2 Structured UI data

Windows UI Automation, application accessibility trees, browser DOM, and
application APIs may expose roles, labels, states, and hierarchy.

Limitations include incomplete metadata, custom-rendered controls, stale
element references, duplicate labels, and controls whose visible label
does not establish task relevance. Reacquire observations after
meaningful navigation or state changes.

### 6.3 Visual grounding

Visual grounding maps a natural-language target to an element in an
image. For example, the input could be a screenshot and "the Export
button in the report toolbar." The output may include a bounding box,
predicted element class, target text, confidence, and evidence.

The output must be validated. A high confidence score is not a guarantee
of correctness. Ambiguous or missing targets should trigger abstention,
further observation, or user clarification.

### 6.4 Dataset design

A dataset may contain: - Screenshot ID and provenance. - Application
family/version where known. - Window size, display scaling, and theme. -
Target instruction and target element class. - Bounding box and visible
text. - Semantic metadata where available. - Ambiguity and
annotation-quality flags. - Split assignment.

Use only permitted data. Avoid collecting personal messages,
credentials, financial details, health information, or unrelated private
content. Prefer synthetic or sanitized interfaces.

### 6.5 Annotation protocol

Define how to annotate nested controls, duplicate labels, disabled
elements, hidden elements, missing targets, and ambiguous instructions.
Double-annotate a subset and resolve disagreements. Split by application
or layout family when possible so that test results measure
generalization rather than near-duplicate memorization.

### 6.6 Baselines and metrics

Baselines: - Accessibility metadata lookup. - OCR plus exact/fuzzy text
matching. - Simple visual matching. - Pretrained model without
adaptation. - Proposed adapted or hybrid method.

Metrics: - Correct target-selection rate. - IoU for bounding boxes where
applicable. - Precision/recall. - Performance on unseen layouts. -
Inference latency and memory. - Quality of abstention when a target
cannot safely be identified.

## 7. Machine-learning research plan

The ML contribution must be explicit. A pretrained model integration can
be valuable engineering, but is not by itself evidence of original
research.

### 7.1 Primary candidate: visual grounding

**Research question:** Can a hybrid or adapted visual-grounding approach
improve UI target selection on unfamiliar layouts compared with simple
baselines?

Workflow: 1. Define the target-selection task and success criteria. 2.
Review candidate models, licenses, compute requirements, and runtimes.
3. Collect or select permitted data. 4. Freeze train/validation/test
splits. 5. Implement simple baselines. 6. Choose a model that fits the
real hardware. 7. Adapt or fine-tune only when justified. 8. Evaluate on
held-out layouts or applications. 9. Analyze errors by control type,
theme, scaling, and ambiguity. 10. Measure latency and memory. 11. Run
ablations. 12. Document failures, limitations, and reproducibility
details.

### 7.2 Secondary candidate: action-outcome prediction

**Research question:** Can a model trained on execution outcomes improve
failure detection and recovery?

Possible features: - Tool and action type. - Target discovery method. -
Model confidence. - Control enabled/disabled state. - Expected versus
observed transition. - Timeout or exception class. - Number of previous
attempts. - UI-state change indicators. - Verification result.

Labels may include verified success, confirmed failure, unexpected
transition, and inconclusive outcome.

Start with logistic regression or a decision tree, then evaluate random
forests or gradient-boosted models if the dataset supports them. Compare
against explicit rules. A classifier must not replace postcondition
verification or authorize consequential actions.

### 7.3 Optional: demonstration-based learning

Record permissioned demonstrations in a controlled environment as
sequences of observations, actions, outcomes, and task context.
Investigate next-action prediction, retrieval of similar trajectories,
or generalization to changed layouts. Start offline; do not allow
experimental policies to freely perform destructive actions on the live
desktop.

### 7.4 Avoiding data leakage

-   Split by task, application, and layout where appropriate.
-   Keep near-identical screenshots out of both training and test sets.
-   Freeze the test set before tuning.
-   Record versions and class balance.
-   Report sample counts and uncertainty.
-   Document exclusions and failed experiments.

### 7.5 Model governance

For each model record its name/version, source, license, intended use,
data provenance, training method, hardware, dependencies, metrics,
limitations, privacy implications, and abstention conditions.

## 8. Tool registry and execution runtime

### 8.1 Tool contract

Each tool must declare: - Tool ID and version. - Description and
capability boundaries. - Input and output schema. - Required
permissions. - Side-effect category. - Timeout and retry rules. -
Idempotency behavior. - Cancellation support. - Verification method. -
Logging requirements.

### 8.2 Side-effect categories

**Read-only:** inspect a file, read page text, inspect UI metadata.

**Reversible local change:** create a new file or edit a draft with a
recoverable backup.

**Consequential action:** send a message, submit a form, publish
content, purchase an item, or delete important data.

Consequential actions require policy checks and appropriate
confirmation. A model cannot relabel an action as harmless to avoid
approval.

### 8.3 Idempotency and duplicate prevention

Repeating some actions is harmless; repeating a form submission or
message send may create duplicates. For non-idempotent operations: -
Record an action ID. - Inspect current state before retrying. - Use
application-provided idempotency mechanisms where available. - Require
confirmation if a consequential result is uncertain. - Never repeat
solely because the response was delayed.

### 8.4 Error taxonomy

Use structured errors: invalid input, unsupported capability, permission
denied, target not found, stale state, timeout, application unavailable,
verification failed, confirmation required, cancelled, or unknown
failure.

## 9. Verification and recovery

Every action should specify: - Preconditions. - Intended effect. -
Expected state transition. - Postconditions. - Recovery strategy. -
Retry safety.

Example: when saving a report, verify that the file exists, can be
reopened, and contains required sections. If verification fails,
investigate the cause and choose an approved recovery or report the
failure.

Recovery sequence: 1. Stop dependent steps. 2. Capture error and current
state. 3. Assess whether the prior action may have had side effects. 4.
Revalidate preconditions. 5. Select a safe recovery. 6. Apply policy
checks. 7. Execute within bounded retry limits. 8. Verify the result. 9.
Replan or ask for assistance if unresolved.

Possible outcomes: - **Verified complete:** all completion conditions
passed. - **Partially complete:** some outputs succeeded. - **Blocked:**
missing permission, input, or capability. - **Failed:** goal not
achieved. - **Cancelled:** execution stopped by the user or policy. -
**Unverified:** success is plausible but evidence is insufficient.

Never conflate "command issued" with "task completed."

## 10. Persistence and memory

Keep distinct: - **Execution state:** plan, statuses, outputs,
checkpoints. - **Working context:** information needed during the
current task. - **User-approved preferences:** non-sensitive defaults. -
**History:** action records subject to retention controls. - **Learned
experience:** generalized patterns from permissioned data.

Save state after important transitions. Use transactional writes where
appropriate. Re-observe the environment before resuming. Do not assume
an interrupted external action succeeded or failed without checking.
Keep secrets out of logs. Provide user controls for inspecting and
deleting task history and preferences.

Illustrative task record:

``` json
{
  "task_id": "stable-unique-id",
  "goal": "User-approved task description",
  "status": "running",
  "created_at": "ISO-8601 timestamp",
  "updated_at": "ISO-8601 timestamp",
  "steps": [],
  "checkpoint": {},
  "completion_evidence": [],
  "pending_user_decisions": [],
  "error_summary": null
}
```

## 11. Security, privacy, and safety

### 11.1 Threat model

Threats include prompt injection in webpages/documents, incorrect target
selection, accidental deletion, duplicate submissions, unauthorized file
access, credential leakage, untrusted scripts, excessive permissions,
false claims of success, and unsafe resumption after interruption.

### 11.2 Untrusted content

Webpage and document content is data, not authority. Embedded
instructions must not override the user's request or the policy layer.
Separate user instructions, trusted metadata, untrusted content, tool
output, and policy decisions. Use allowlisted tools and validated
schemas instead of unrestricted model-generated shell commands.

### 11.3 Permissions

-   Request only necessary permissions.
-   Never bypass UAC or security controls.
-   Do not store passwords in plaintext.
-   Use documented authentication and secure credential storage.
-   Avoid administrator privileges unless genuinely required and
    explicitly approved.
-   Treat external APIs and remote execution as separate trust
    boundaries.

### 11.4 Confirmation requirements

Require confirmation before sending messages, submitting consequential
forms, making purchases, publishing, deleting important data, changing
security/account settings, installing software, or executing untrusted
code.

Explain the action, destination/account, and consequence. Approval for
one action does not grant unlimited future approval.

### 11.5 Camera, microphone, and logs

Make recording status visible. Prefer push-to-talk initially. Provide
immediate disable controls. Avoid hidden capture. Process locally where
feasible. Keep screenshots opt-in and avoid capturing unrelated private
content. Redact credentials and sensitive values from logs; retain only
what is necessary for debugging and audit.

### 11.6 Emergency stop

Cancellation should prevent new actions, stop interruptible work, and
preserve a recoverable state where possible. Communicate if an operation
cannot be interrupted immediately.

## 12. Recommended technology stack

Finalize choices only after auditing the actual computer.

  -----------------------------------------------------------------------
  Area                    Candidate               Purpose
  ----------------------- ----------------------- -----------------------
  Main language           Python                  ML and automation
                                                  ecosystem

  Desktop UI              PySide6                 Windows application
                                                  shell

  Schemas                 Pydantic or equivalent  Typed validation

  Async work              asyncio                 Concurrent I/O and
                                                  long-running tasks

  Persistence             SQLite                  Task state and logs

  ML                      scikit-learn, PyTorch   Baselines, training,
                                                  evaluation

  Vision                  OpenCV and suitable     Visual perception
                          pretrained models       

  Windows control         Windows UI Automation,  Semantic desktop
                          pywinauto               interaction

  Browser                 Playwright              DOM-based automation

  OCR                     Suitable local OCR      Text extraction
                          library                 

  Speech                  Suitable local ASR/TTS  Optional speech
                          libraries               modality

  Tests                   pytest                  Unit and integration
                                                  tests

  Packaging               PyInstaller             Candidate Windows
                                                  packaging
  -----------------------------------------------------------------------

Selection criteria: license, Windows support, RAM/VRAM requirements,
latency, offline operation, API stability, security, and packaging
complexity. Avoid choosing tools simply because they are fashionable.

The ₹0 core target means using free/open-source software and local
execution wherever feasible; it does not guarantee that every advanced
model will run efficiently on every computer. Audit CPU, RAM, GPU/VRAM,
storage, and workload before selecting model size. Keep paid APIs and
cloud infrastructure optional.

## 13. Suggested repository structure

``` text
orion/
├── README.md
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── architecture.md
│   ├── safety-and-privacy.md
│   ├── model-card-template.md
│   ├── dataset-card-template.md
│   ├── evaluation-protocol.md
│   └── release-checklist.md
├── src/orion/
│   ├── app/
│   ├── interaction/
│   ├── intent/
│   ├── planner/
│   ├── orchestration/
│   ├── perception/
│   ├── grounding/
│   ├── tools/windows/
│   ├── tools/browser/
│   ├── tools/files/
│   ├── tools/documents/
│   ├── execution/
│   ├── verification/
│   ├── recovery/
│   ├── policy/
│   ├── memory/
│   ├── observability/
│   ├── models/
│   └── config/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── safety/
│   ├── fixtures/
│   └── end_to_end/
├── research/
│   ├── data_collection/
│   ├── annotations/
│   ├── baselines/
│   ├── training/
│   ├── evaluation/
│   └── reports/
├── scripts/
└── artifacts/
```

Do not commit credentials, private screenshots, user data, or model
weights without checking licensing and repository size.

## 14. Testing strategy

### 14.1 Unit tests

Test schema validation, dependency resolution, state transitions, tool
argument validation, permission checks, retry limits, cancellation,
persistence, completion checks, and error classification.

### 14.2 Integration tests

Test planner-to-tool integration, Windows executor behavior,
browser-to-verifier flow, persistence/resumption, model predictions
behind policy checks, and recovery-to-planner behavior.

### 14.3 End-to-end tests

Use controlled applications and fixtures to: - Open an application and
verify its window. - Create and reopen a file. - Extract data from a
test page. - Fill a test form and stop before submission. - Create a
spreadsheet from fixture data. - Handle a deliberately introduced
dialog. - Resume after a controlled interruption. - Cancel a running
task.

### 14.4 Safety tests

Verify that the model cannot bypass policy; webpage prompt injection
does not override the user; consequential actions require approval;
duplicate submissions are prevented where detectable; cancellation
prevents subsequent actions; missing permissions cause a safe stop; logs
redact credentials; uncertain targets do not trigger high-impact
actions; and unsupported hardware is reported honestly.

### 14.5 Honest test status

Use `passed`, `failed`, `blocked`, `skipped` with reason, and
`inconclusive`. An unexecuted test is not passed. Mock tests do not
establish real hardware or application compatibility.

## 15. Experimental design and benchmarking

### 15.1 Task categories

Build a repeatable task set containing: - Direct tasks. - Multi-step
tasks. - Cross-application workflows. - Layout and scaling variations. -
Failure and recovery scenarios. - Interruption/resumption cases. -
Ambiguous requests requiring clarification. - Safety cases that must be
blocked or require approval.

Each benchmark task needs a known initial state, expected result,
difficulty label, scoring rule, and environment record.

### 15.2 Baselines

Compare: 1. Deterministic automation using known APIs and rules. 2. An
agent using existing pretrained models without the proposed learned
component. 3. ORION with the proposed ML component enabled.

Keep task distributions, environments, permissions, and success criteria
comparable.

### 15.3 Metrics

**Task success rate:** tasks completed and verified / eligible tasks.

**Intervention rate:** tasks requiring user assistance / total tasks.

**Recovery success rate:** eligible failure cases recovered successfully
/ eligible failures.

**Grounding accuracy:** target selections correct under the annotation
protocol / evaluated selections.

**Failure detection precision and recall:** false alarms and missed
failures.

**Latency:** end-to-end time and model inference time.

**Resources:** peak RAM, GPU memory if applicable, CPU, and model disk
size.

**Safety violations:** unauthorized consequential actions, policy
bypasses, or prohibited tool invocations. Target: zero.

### 15.4 Ablations

Disable one experimental component at a time in a controlled test
harness: visual model, semantic metadata, outcome predictor, or recovery
logic. Compare outcomes to determine which components add value. Never
disable safety controls on the real desktop to create an experiment.

### 15.5 Reporting

Report trial counts, task/environment composition, model versions, data
splits, hardware, metrics, uncertainty, failures, exclusions, and
threats to validity. Do not invent performance figures. A negative
result is valid evidence and should be reported honestly.

## 16. Development roadmap and acceptance gates

### Stage 0 --- Environment audit

Inspect Windows version, Python, RAM, GPU/VRAM, storage, permissions,
installed applications, and repository state. Review model licenses and
compute requirements. Define one representative end-to-end task.

**Gate:** environment report and realistic plan exist; no unsupported
hardware claims.

### Stage 1 --- Desktop shell

Build the UI, task input, progress display, event log, configuration,
and cancel control.

**Gate:** app launches on the target machine; UI remains responsive;
errors and cancellation are visible.

### Stage 2 --- Safe tool contracts

Add bounded file operations and application launching with schemas,
permissions, timeouts, and structured errors.

**Gate:** invalid arguments and denied permissions fail safely;
cancellation is tested.

### Stage 3 --- Planning and persistence

Implement goal/task schemas, dependency graphs, checkpoints, plan
validation, and clarification handling.

**Gate:** multi-step state is correct; resumption does not blindly
repeat completed or uncertain actions.

### Stage 4 --- Real Windows and browser control

Integrate supported Windows UI Automation and Playwright. Add
observations and postcondition checks.

**Gate:** controlled end-to-end tests run on actual local applications;
real actions are distinguished from mocks.

### Stage 5 --- Recovery

Add error categories, bounded retries, safe replanning, duplicate-action
prevention, and interruption testing.

**Gate:** injected failures are classified; unresolved consequential
states stop safely.

### Stage 6 --- Visual-grounding research

Create annotation guidelines and dataset; implement baselines;
select/adapt a model; evaluate held-out layouts and run ablations.

**Gate:** data provenance and splits are documented; results are
reproducible; model outputs remain subject to policy and verification.

### Stage 7 --- Outcome prediction

Collect permissioned outcome records, train baseline classifiers,
calibrate, and evaluate effect on recovery.

**Gate:** model is compared with rules on held-out data; false positives
and negatives are documented.

### Stage 8 --- Broader workflows and modalities

Expand tools and optional voice/webcam modules. Keep each modality
independently disableable.

**Gate:** input methods share a common task interface; real-device
testing is distinguished from mocks.

### Stage 9 --- Benchmark and release

Run regressions, safety tests, benchmark and ablations; package the app;
prepare setup, limitations, and project report.

**Gate:** clean setup is documented, release is tested on the target
machine, and claims match evidence.

## 17. Risk register

  -------------------------------------------------------------------------
  Risk                    Consequence             Mitigation
  ----------------------- ----------------------- -------------------------
  Scope too large         No finished system      Stage gates; build an
                                                  end-to-end task early

  Limited compute         Slow or unusable models Audit hardware; start
                                                  with smaller models and
                                                  baselines

  Noisy dataset           Misleading metrics      Annotation protocol and
                                                  quality checks

  Data leakage            Inflated results        Split by
                                                  task/application/layout

  UI changes              Incorrect actions       Re-observe, reacquire
                                                  targets, verify
                                                  postconditions

  Duplicate actions       Repeated side effects   Idempotency, state
                                                  inspection, confirmation

  Prompt injection        Unauthorized behavior   Treat external content as
                                                  untrusted; independent
                                                  policy

  Excess permissions      Privacy/security risk   Least privilege and
                                                  explicit scopes

  Model overconfidence    Unsafe action           Calibration, abstention,
                                                  deterministic
                                                  verification

  Weak testing            Unsupported claims      Automated and manual
                                                  acceptance suites

  Packaging problems      Developer-only success  Clean-environment release
                                                  testing

  Privacy leakage         Sensitive data exposed  Local-first processing,
                                                  redaction, retention
                                                  controls

  License/API changes     Broken build or use     Pin dependencies and
                          restrictions            review licenses
  -------------------------------------------------------------------------

## 18. Budget and hardware strategy

The ₹0 core budget is a target, not a guarantee that every model will
run on every laptop.

Use free/open-source libraries, local Windows automation, SQLite,
Playwright, scikit-learn, and suitable pretrained models with compatible
licenses. Create sanitized datasets from permitted interfaces. Keep paid
APIs and cloud services optional.

Avoid training large vision-language models from scratch. Measure actual
latency and memory. Select model size after auditing CPU, RAM, GPU/VRAM,
and expected workload. Webcam input should remain optional and dependent
on real hardware validation.

## 19. Documentation and research artifacts

The final repository should include: - Product/architecture
documentation. - Installation and configuration guide. - Tool registry
and permission reference. - Safety and privacy policy. - Dataset card
and annotation guide. - Model cards. - Training and evaluation
scripts. - Baseline implementations. - Benchmark protocol. - Experiment
logs and results. - Known limitations. - Reproducibility instructions. -
User guide. - Release checklist. - Final report and presentation.

Every reported result should be traceable to a code version, dataset
version, model version, configuration, and evaluation run.

## 20. Definition of done

ORION is ready to be presented as a credible major project when: 1. It
runs as a usable Windows desktop application. 2. It performs
representative tasks on the real target machine. 3. It supports
multi-step plans and dependencies. 4. It distinguishes real integrations
from mocks. 5. It persists state and resumes safely where supported. 6.
It verifies outcomes rather than assuming success. 7. It handles common
failures and stops on unresolved ambiguity. 8. It enforces permissions
independently of model output. 9. At least one clearly specified ML
contribution is implemented and evaluated if included in the research
claim. 10. The ML component is compared with an appropriate baseline.
11. Dataset provenance, splits, model versions, and metrics are
documented. 12. Benchmark tasks include failures, not only successful
demos. 13. Automated and manual test suites are documented. 14. Privacy,
cancellation, logs, and permissions are explained. 15. Packaging has
been tested or its limitations are stated. 16. Implemented,
experimental, and planned capabilities are clearly distinguished. 17.
Every quantitative claim is supported by measurement.

## 21. Presentation and interview strategy

Present ORION as an agent-engineering and AIML research project, not a
list of integrations.

Suggested presentation: 1. Explain why fixed scripts are brittle for
open-ended computer tasks. 2. Show the architecture and separation of
planning, perception, execution, verification, and safety. 3.
Demonstrate a multi-step task across real applications. 4. Introduce a
controlled failure and show recovery. 5. Explain the ML research
question and dataset. 6. Compare the learned component against a
baseline. 7. Show error analysis and limitations. 8. Explain your
individual contribution. 9. Present benchmark results and
reproducibility artifacts. 10. Close with next steps supported by
observed limitations.

Prepare to answer: - What did you implement yourself? - Why this model
and baseline? - How was the dataset collected and split? - How did you
prevent data leakage? - What happens when the model is wrong? - How is
success verified? - How are duplicate submissions prevented? - How is
prompt injection handled? - What evidence shows ML improved
performance? - Which parts are deterministic, pretrained, trained by
you, or experimental? - What are the hardware and runtime limits?

## 22. Proposed project abstract

**ORION: A General-Purpose Autonomous Computer-Use Agent with Adaptive
Perception and Reliable Task Execution**

ORION is a desktop AI agent designed to translate high-level user goals
into coordinated actions across computer applications, operating-system
interfaces, browser environments, and supported digital tools. It
combines task planning, tool orchestration, hybrid computer perception,
persistent execution state, outcome verification, and failure recovery
to pursue multi-step objectives in changing environments.

The project investigates whether learned visual grounding and
action-outcome prediction can improve the reliability of computer-use
agents. The system combines ML components with deterministic automation,
explicit permissions, and postcondition verification. Its evaluation
compares the proposed approach against deterministic and
pretrained-model baselines using repeatable tasks, held-out layouts,
recovery scenarios, and metrics including task completion, grounding
accuracy, failure detection, latency, and resource use.

Expected deliverables include a Windows desktop application, an
extensible tool framework, trained or adapted ML components, a
documented evaluation protocol, reproducible experiments, and an honest
account of limitations. The project does not assume perfect autonomy or
universal application compatibility; every capability and performance
claim is subject to implementation and testing.

## 23. Final design position and immediate next step

ORION remains a broad general-purpose agent. It should not be reduced to
a voice interface or a single workflow. The engineering strategy is to
build a functioning agent foundation in stages, then use a focused ML
research contribution to investigate a difficult and measurable problem.

The recommended starting research direction is hybrid visual grounding,
followed by action-outcome prediction if the schedule and dataset
support it. The project's value will come from the working system, the
quality of its architecture, measurable contribution from ML, and the
honesty of its evaluation---not from the number of features claimed.

**Immediate next step:** audit the actual Windows development
environment, measure available compute, select a representative
end-to-end task, and produce the Stage 0 report before choosing specific
model architectures.
