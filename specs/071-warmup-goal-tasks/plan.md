# Implementation Plan: Warm-Up Goal Tasks for Sessions

**Branch**: `071-warmup-goal-tasks` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/071-warmup-goal-tasks/spec.md`

## Summary

Add a new "Warm-Up Tasks" goal type to the sessions plugin. Users select a scale (from the same 24-scale list used in Train view), configure tempo via a slider, set iterations and minimum score, and specify how many existing scheduled sessions should receive the warm-up task prepended. The warm-up task launches the Train view with the scale and tempo pre-set when tapped. Goal auto-completes when all targeted warm-up tasks are marked done.

## Technical Context

**Language/Version**: TypeScript 5.x, React 18+  
**Primary Dependencies**: sessions plugin (`plugins-external/sessions-plugin/`), Train view plugin (`frontend/plugins/train-view/`), Plugin API v8 (`frontend/src/plugin-api/`)  
**Storage**: IndexedDB (`sessions` + `goals` stores via `openDB`) for full objects; localStorage (`graditone-sessions-index`, `graditone-goals-index`) for fast-list indexes  
**Testing**: vitest + React Testing Library (`@testing-library/react`); tests co-located in `plugins-external/sessions-plugin/`  
**Target Platform**: PWA — tablet devices (iPad, Surface, Android tablets); offline-first  
**Project Type**: Web application (monorepo `frontend/` + `plugins-external/sessions-plugin/`)  
**Performance Goals**: Offline-capable; all storage operations <100ms; form interaction at 60fps  
**Constraints**: Touch targets ≥44×44px; max 50 sessions in storage (`MAX_SESSIONS`); no network requests; backward-compatible storage migrations required  
**Scale/Scope**: Single user, offline; up to 50 concurrent sessions

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Domain-Driven Design | ✅ PASS | `WarmUpScalesGoal` and `WarmUpScaleTask` introduced as first-class domain entities. Terminology aligns with music domain (scale, tempo, iterations). |
| II. Hexagonal Architecture | ✅ PASS | Pure functions (`createWarmUpGoal`, `insertWarmUpTaskIntoSessions`) handle domain logic; side effects isolated in `GoalsView.tsx`. No direct DB calls in engine layer. |
| III. PWA Architecture | ✅ PASS | Same offline-first IndexedDB + localStorage pattern as existing goals. No network calls introduced. |
| IV. Precision & Fidelity | ✅ PASS (N/A) | No changes to the music timeline or tick-level timing. |
| V. Test-First Development | ⚠️ REQUIRED | All new pure functions in `goalEngine.ts`, new types, and new form component must have tests written before implementation. |
| VI. Layout Engine Authority | ✅ PASS (N/A) | No layout calculations added to the frontend. |
| VII. Regression Prevention | ✅ PASS | No existing bugs addressed; section is empty in spec. Any issue found during implementation must follow the test-first regression pattern. |

**Gate result**: PASS — no violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/071-warmup-goal-tasks/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
plugins-external/sessions-plugin/
├── goalTypes.ts              # MODIFY — extend GoalType, Goal, add WarmUpGoal fields
├── sessionTypes.ts           # MODIFY — extend ScoreRef type union with 'warmup-scale'
├── goalEngine.ts             # MODIFY — add createWarmUpGoal(), insertWarmUpTaskIntoSessions()
├── goalStorage.ts            # NO CHANGE — generic Goal storage reused as-is
├── GoalsView.tsx             # MODIFY — add goal-type selector, branch to new form
├── GoalCreationForm.tsx      # MODIFY — minor: add goalType prop / or keep separate
├── WarmUpGoalCreationForm.tsx  # NEW — warm-up goal creation form component
├── TaskRow.tsx               # MODIFY — handle 'warmup-scale' scoreRef type for launch
├── goalEngine.test.ts        # MODIFY — add tests for new engine functions
├── GoalCreationForm.test.tsx # MODIFY — regression guard for existing form
└── WarmUpGoalCreationForm.test.tsx  # NEW — unit tests for new form
```

**Structure Decision**: Web application, modifications confined to `plugins-external/sessions-plugin/`. No changes needed to `frontend/` other than potential train-view navigation data contract extension.

---

## Phase 0: Research

*All unknowns from Technical Context resolved. See [research.md](research.md) for full details.*

| # | Question | Decision |
|---|----------|----------|
| RQ-1 | How does train-view receive navigation data from sessions-plugin? | `context.openPlugin('train-view', payload)` → train-view reads via `context.getNavigationData()` on mount. Plugin API v8 supports this already. |
| RQ-2 | How to inject task into existing sessions without the `distributeTasks` / `findFreeDays` flow? | Load all sessions from IndexedDB, sort by `targetDate` ascending, filter for `availableTime - usedTime >= 300`, prepend task at index 0, save. |
| RQ-3 | Can `checkGoalCompletionAcrossSessions` be reused for warm-up goals? | Yes — it is goal-type agnostic (queries tasks by `goalId` across session.tasks arrays). No modification needed. |
| RQ-4 | What ScoreRef shape should warm-up tasks use? | Extend `ScoreRef.type` with `'warmup-scale'`; `id` = scaleId (string). Existing availability check `task.scoreRef.type === 'preloaded'` evaluates false — warm-up tasks are always available, which is correct. |
| RQ-5 | What optional fields to add to `Goal` for warm-up metadata? | `warmUpScaleId?: string`, `warmUpSessionCount?: number`. Reuse `scoreRef`, `scoreTitle`, `startMeasure`/`endMeasure` (set to 0 as sentinel). |
| RQ-6 | How does `GoalsView` currently manage goal creation and which parts must change? | `processScoreSelection → distributeTasks + findFreeDays` path is for learn-score-phrase only. Warm-up path replaces this with `createWarmUpGoal + insertWarmUpTaskIntoSessions`. Selector added at top of creation flow to branch the two types. |

**Phase 0 gate**: All NEEDS CLARIFICATION resolved. Proceed to Phase 1.

---

## Phase 1: Design

### Data Model

See [data-model.md](data-model.md) for full entity definitions.

**Summary of changes**:

| Entity | Change | Rationale |
|--------|--------|-----------|
| `ScoreRef.type` | +`'warmup-scale'` | Identifies warm-up tasks without adding a new task type; reuses existing `SessionTask` shape |
| `GoalType` | +`'warm-up-scales'` | Discriminates goal type for form selection and engine dispatch |
| `Goal` | +`warmUpScaleId?`, +`warmUpSessionCount?` | Carries warm-up-specific metadata for display and history |
| `WarmUpGoalCreationFormParams` | NEW | Typed input for the warm-up creation form |
| `WarmUpTaskConfig` | NEW (nav payload) | Cross-plugin contract passed via `openPlugin('train-view', ...)` |

**Backward compatibility**: All additions are optional fields on existing interfaces. IndexedDB `goals` store schema requires no migration — existing goal objects without the new fields will continue to deserialize correctly.

### Contracts

See [contracts/warm-up-task-launch-v1.md](contracts/warm-up-task-launch-v1.md) for the full protocol.

**Two-leg contract**:
1. **sessions-plugin → train-view**: `openPlugin('train-view', { warmUpTaskConfig })` — passes scale, tempo, loopCount, minResult, taskId, sessionId
2. **train-view → sessions-plugin**: `openPlugin('sessions-plugin', { completedWarmUpTask })` — passes taskId, sessionId, result, completedAt

Both legs are opt-in (absent key = existing behaviour remains). The train-view plugin reads via `getNavigationData()` on mount.

### Implementation Quickstart

See [quickstart.md](quickstart.md) for step-by-step TDD implementation guide.

**8-step order** (short-to-long dependency chain):
1. Extend types (`sessionTypes.ts`, `goalTypes.ts`)
2. Add `createWarmUpGoal()` — TDD, ~5 tests
3. Add `insertWarmUpTaskIntoSessions()` — TDD, ~6 tests
4. Create `WarmUpGoalCreationForm.tsx` — TDD with RTL, ~4 tests
5. Update `GoalsView.tsx` — goal-type selector + warm-up branch, ~4 tests
6. Update `TaskRow.tsx` — warm-up launch branch, ~2 tests
7. Update `train-view` — read `warmUpTaskConfig` from nav data, ~2 tests
8. Handle completion callback in sessions-plugin — ~2 tests

**Total estimated new tests**: ~25

### Agent Context Update

*Run after design artifacts are stable, before implementation.*

```bash
cd /path/to/graditone
.specify/scripts/bash/update-agent-context.sh copilot
```

This updates `.github/copilot-instructions.md` with the new technology context introduced in this plan:
- `WarmUpScalesGoal` domain entity
- `WarmUpTaskConfig` cross-plugin contract
- `insertWarmUpTaskIntoSessions()` pure function pattern
- `'warmup-scale'` ScoreRef type extension

### Constitution Check (Post-Design)

Re-evaluated against the completed design:

| Principle | Status | Notes |
|-----------|--------|-------|
| I. DDD | ✅ PASS | All new domain logic in `goalEngine.ts`; terminology (WarmUpScalesGoal, WarmUpScaleTask) is music-domain native |
| II. Hexagonal | ✅ PASS | `createWarmUpGoal` + `insertWarmUpTaskIntoSessions` are pure with no side effects; UI layer handles persistence |
| III. PWA | ✅ PASS | IndexedDB + localStorage two-tier pattern extended consistently; no network calls |
| IV. PPQ | ✅ PASS (N/A) | No timing/audio engine changes |
| V. TDD | ✅ PASS | quickstart.md mandates test-first; estimated 25 new tests across 8 steps |
| VI. Layout Engine | ✅ PASS (N/A) | No layout engine involvement |
| VII. Regression | ✅ PASS | `GoalCreationForm.test.tsx` regression guard added in step 5; `TaskRow.test.tsx` regression guard in step 6 |

**Post-design gate**: PASS — design complete, ready for `/speckit.tasks`.
