# NNN: <Spec title>

**Status:** idea | draft | ready | in progress | done | superseded by <spec> | dropped

<!--
How to use this template:
- Copy to specs/NNN-short-name.md (next free number). One goal per spec.
- Core sections are always filled. Optional sections are deleted when they don't apply.
- One line per item. Prose only where a line isn't enough.
- Delete these guidance comments when drafting.
-->

## Goal

<!-- Core. One goal, no "and". What changes and why it matters. -->

## Scope

<!-- Optional: when the boundary isn't obvious. -->
- In: ...
- Out: ...

## Requirements

<!-- Core. Each requirement has acceptance criteria as behavior scenarios. -->
- R1: ...
  - R1.AC1: Given ..., when ..., then ...

## Design

<!-- Optional: when there are decisions to record. Each decision with its reason. -->

## Assumptions

<!-- Optional: when there are any. Never hidden. -->
- A1: ... Status: confirmed by <who> | unconfirmed (validate how, when, by whom) | accepted risk

## Open questions

<!-- Optional: when there are any. Resolved questions stay. The spec is not ready while one is open. -->
- Q1: ... -> decided ... because ...

## Verification

<!-- Core. Built right: does it do what the spec says? Each test case names the acceptance criterion it checks. -->
- TC1 (R1.AC1): ...

## Validation

<!-- Optional: when it computes values someone relies on. Right result: is it correct, independent of our
assumptions? E.g. hand-worked example, reconciliation with a source of truth, invariants, domain sign-off. -->
- ...

## Tasks

<!-- Core. Each task names the requirements it implements. Commits carry `Spec: NNN` and `Task: T1` footers. -->
- [ ] T1 (R1): ...
