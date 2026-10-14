# Telemetry retention and durable-event promotion

> **Status:** public design note; not an enforcement milestone
> **Data rule:** synthetic structure and function only; no real household content, credentials, production measurements, or HOUSE payloads
> **Scope:** household domain inside this repository
> **Related:** [`AGENT_INTERACTION_CONTRACTS.md`](AGENT_INTERACTION_CONTRACTS.md), [`ROADMAP.md`](ROADMAP.md), [`PROGRAM-ROLE.md`](../PROGRAM-ROLE.md), [issue #11](https://github.com/jryski/Household-OS/issues/11)

## Purpose

This note specifies how Household OS keeps raw telemetry from flooding durable knowledge. It covers what remains short-lived operational state, which transitions become durable events, retention expectations, staleness behavior, and how repeated failures become trusted troubleshooting history.

A sample, heartbeat, or failed attempt is operational until a named promotion rule accepts it. Promotion attaches provenance. A later reader can correct or supersede the promoted event. The prior statement stays addressable.

The exact household entity, observation, event, capability, and provenance model is a separate design ([issue #8](https://github.com/jryski/Household-OS/issues/8), domain design owner claude-warden). This note names functions those future records must support. It does not define that model, and it does not choose schema fields.

## Explicit non-goals

- This note does not define the household entity, observation, event, capability, or provenance schema. Those fields belong to issue #8.
- This note does not add a retention worker, a migration, a storage layout, or executable tests.
- Landing this note does not complete roadmap milestone HOS-2 or HOS-3.
- This note does not depend on Home Assistant or any other vendor telemetry bus. `device-demo-1` is a synthetic subject label. Issue #8 decides what kind of household subject that label may denote.
- Calendar intake already promotes dated artifacts into canonical household events under [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md). Chat becomes coordination only after promotion into a planning record under [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md) and [`AGENT_INTERACTION_CONTRACTS.md`](AGENT_INTERACTION_CONTRACTS.md). Those paths keep their own rules. This note covers operational telemetry and the durable events promoted from it.
- An action receipt in the agent-interaction note records one attempt. This note does not turn every receipt into durable knowledge.
- No production measurements, real HOUSE payloads, credentials, or private topology appear here. Examples use synthetic identifiers such as `device-demo-1`, `obs-demo-1`, `event-demo-1`, `agent-1`, and `person-1`.

## Vocabulary

| Term | Function |
|---|---|
| Raw telemetry | A point-in-time sample, heartbeat, or connector health tick about a subject. |
| Operational state | The short-lived current view: latest sample, in-flight retry, last-seen. It expires. |
| Promotion | The decision that a transition meets a named rule and may be written as one durable event. |
| Durable event | The retained account of one significant transition, with provenance. |
| Durable knowledge | The set of durable events a later reader treats as household history. |
| Provenance | The function of citing supporting observations, the rule or principal, and the decision time. The field layout is issue #8. |
| Staleness | A mark that operational state or a promoted event is no longer current. The mark is not deletion. |
| Correction | An authorized amendment that records the fix and keeps the prior statement addressable. |
| Supersession | A later durable event becomes the current transition. The earlier event stays readable. |
| Troubleshooting history | One promoted event that accounts for a repeated failure pattern. It is trusted because the repetition rule and provenance are present. |
| Promotion rule | A named policy function, such as `rule-demo-service-due` or `rule-demo-repeat-failure`. Issue #8 may later relate rules to capabilities. This note does not define capability fields. |

`calendar-demo` is a synthetic provider surface already used in this repository. `agent-3` is the synthetic school/calendar synchronization agent from the interaction contracts. They are labels in this note, not a claim that those rows exist in a deployment.

## Functions future records must support

Issue #8 chooses the fields. Whatever shape those records take, household telemetry policy needs them to do the following:

1. Hold a short-lived observation and expire or compact it without writing durable knowledge.
2. Evaluate a candidate transition against one named promotion rule.
3. Refuse promotion when provenance is incomplete.
4. Attach provenance: the supporting observations or their compact, the rule or confirming principal, and the time of the decision.
5. Record one durable event for one significant transition, and treat a later sample of the same still-current transition as operational freshness rather than a second event.
6. Mark operational state or a promoted event stale without erasing history.
7. Correct a promoted event while the original statement remains addressable.
8. Supersede a promoted event with a later one while the earlier event remains readable.
9. Collapse a repeated failure pattern into one troubleshooting-history event that cites the attempts.
10. Leave root-cause language unpromoted until a separate rule or an authorized principal accepts that claim.

## What stays short-lived operational state

Operational state answers what the household systems saw recently. It is not the household's retained account of what changed.

The following stay operational for `device-demo-1` and for connector paths such as `calendar-demo`:

- a single sample, including a reading that has not changed class;
- a heartbeat or last-seen tick;
- a duplicate of a condition already reflected in the current operational view;
- one retryable failure, one rate-limit response, or one missed report;
- an in-flight retry count that has not crossed a promotion rule;
- a compacted summary of samples that no rule has promoted.

`obs-demo-1` is one synthetic sample for `device-demo-1`. Recording it updates operational state. It does not create `event-demo-1`.

A single failed delivery attempt toward `calendar-demo` may still produce an action receipt, as the interaction contracts require for an attempt. That receipt says the attempt happened. It does not, by itself, become trusted troubleshooting history.

## What becomes a durable event

A transition is promoted only when every promotion criterion below holds. The result is one durable event with provenance. Repeat samples of a transition that is already current do not append more events.

| Criterion | Function | Synthetic illustration |
|---|---|---|
| Significance | The change matches a named class: a state-class change, a threshold the rule marks durable, a repeated-failure pattern, or an explicit human confirmation. | `device-demo-1` moves from within its service window to service due under `rule-demo-service-due`. |
| Stable subject | The candidate points at one stable subject so later samples attach to that subject. | Samples for `device-demo-1` share that subject label. The subject's fields are issue #8. |
| Provenance | The decision cites supporting observations or a compact of them, the rule or principal, and the decision time. | `promotion-demo-1` cites `obs-demo-3` and `rule-demo-service-due`. |
| Non-flood | A still-current transition of the same class is not promoted again. | A later sample in the same class refreshes operational freshness for `device-demo-1`. |
| Authority | Automated promotion uses a pre-declared rule. When the rule requires confirmation, an authorized principal records it. | `person-1` may confirm an ambiguous candidate. `agent-1` may propose one. A chat sentence is not confirmation. |

If any criterion fails, the candidate stays operational or is dropped when its retention window ends. The refusal is not a second durable fact.

Significant transitions this policy expects to promote, when their rules fire:

- a subject changes class in a way the rule names as durable, such as `device-demo-1` becoming service due;
- access or delivery for `calendar-demo` changes class in a way the rule names as durable, such as revoked access or a repeated failure pattern;
- an authorized principal confirms a candidate the rules left ambiguous.

The following do not promote:

- one missed heartbeat;
- one retryable failure below the repetition rule;
- an unchanged reading taken again;
- an agent inference that names no observation and no rule;
- a compacted operational summary that no rule accepted.

### Worked transition

```text
obs-demo-1 shows device-demo-1 still inside its service window
        → operational state only
obs-demo-2 shows the same class again
        → refresh freshness; no durable event
obs-demo-3 crosses rule-demo-service-due
        → promotion-demo-1
        → event-demo-1, one durable transition, provenance attached
later samples still in the service-due class
        → operational freshness only; event-demo-1 stays the current event
```

## Provenance on a promoted event

Provenance is a function, not a field list from issue #8. A promotion that cannot perform the function does not write a durable event.

For `event-demo-1`, provenance must let a later reader answer:

- which observations or compact supported the transition (`obs-demo-3`, and further `obs-demo-*` ids when more than one sample was required);
- which rule or principal decided (`rule-demo-service-due` or `person-1`);
- when that decision was made;
- which subject the event is about (`device-demo-1`).

`agent-1` may propose `promotion-demo-1`. When the rule requires confirmation, `event-demo-1` exists only after `person-1` confirms. `agent-1` does not confirm its own proposal. A line of chat that says the transition is accepted leaves the candidate unpromoted.

## Retention expectations

Retention below is policy expectation. A deployment chooses exact durations. Those durations are not a schema, not a migration, and not a claim that a worker already enforces them. The expectation is that raw telemetry is short-lived relative to household history, and that expiry never writes a durable event.

| Material | Expectation |
|---|---|
| High-frequency samples | Keep the latest sample per subject and a short rolling window, on the order of hours. Then drop the raw sample or compact it. |
| Operational attempts below a repetition rule | Keep them long enough to evaluate the rule and to support one action receipt. Then compact them. |
| Compacted operational summaries | Remain operational. Compaction is not promotion. |
| Promoted durable events | Remain with household history. They leave the current view through correction or supersession, not through the telemetry window. |
| Superseded and corrected events | Stay addressable so a later reader can see what was recorded and what replaced it. |
| Refused candidates | Stay operational audit for the short window. A refusal does not become durable knowledge unless a separate promotion rule accepts that refusal pattern. |

`obs-demo-1` ages out of the operational window without creating `event-demo-1`. A daily compact of samples for `device-demo-1` is still operational state.

## Staleness

Staleness marks that a view is no longer current. It does not delete a record, and it does not assert the opposite condition.

- A newer sample for `device-demo-1` makes the previous operational sample stale.
- When the expected reporting interval passes with no sample, operational state for `device-demo-1` is marked stale. `event-demo-1` remains. Silence is not evidence that the subject returned to an earlier class.
- A promoted event is marked stale when a later observation shows its condition no longer holds, or when the validity window named by its promotion rule has elapsed. The event stays readable. A successor event is created only when the new transition itself meets the promotion criteria.
- Prolonged silence may be its own significant transition when a rule says so. `rule-demo-reporting-gap` may promote a separate reporting-gap event with its own provenance. That event does not rewrite `event-demo-1` into a healthy class.
- Provider version drift on `calendar-demo` stays operational reconciliation state until a documented authority rule promotes a conflict, cancellation, or revocation. Intake and delivery reconciliation rules remain in [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md). This note does not replace them.

## Repeated failures and trusted troubleshooting history

One failure is operational. A repeated failure pattern becomes trusted troubleshooting history only as a single promoted event.

Trusted here means the entry cites a named repetition rule and the attempts that satisfied it, and a later reader can correct or supersede it. Trusted does not mean an inferred root cause is accepted. `agent-1` does not promote a cause, a vendor fault, or a household conclusion from a cluster of failures unless a separate rule or `person-1` accepts that claim.

```text
receipt-demo-1  delivery toward calendar-demo failed
receipt-demo-2  same failure class, still below the rule
        → operational attempts and receipts only
receipt-demo-3  rule-demo-repeat-failure is satisfied
        → promotion-demo-2
        → event-demo-2, one troubleshooting-history event
           provenance cites receipt-demo-1, receipt-demo-2, receipt-demo-3
           and rule-demo-repeat-failure
        → no root-cause sentence is added by the promotion
```

A later successful attempt may promote `event-demo-3` as the recovered condition. `event-demo-3` supersedes `event-demo-2` as the current condition. `event-demo-2` remains the troubleshooting history of the pattern, with superseded status. The raw attempts are not copied again into durable knowledge.

The same shape applies to `device-demo-1`. Three operational faults below `rule-demo-repeat-failure` do not create three durable events. Crossing the rule creates one history event for that subject.

## Correction and supersession

Promoted events stay amendable. Amendment appends a decision. It does not erase the earlier statement.

### Correction

`person-1` may correct `event-demo-1` when the class, subject, or cited evidence is wrong. The correction records who corrected it, what the corrected reading is, and which event it amends. `event-demo-1` remains addressable with a corrected status. `agent-1` does not apply that correction on its own authority.

A correction that changes the transition into a different claim still carries provenance. If the corrected claim lacks observations and a rule or principal, the correction is refused and the prior event stays as it was.

### Supersession

`event-demo-3` supersedes `event-demo-2` when a later transition meets the promotion criteria and the rule says it replaces the current condition. Readers who want the current condition follow `event-demo-3`. Readers who want history still open `event-demo-2`.

Supersession has its own provenance. A chat line, a deleted sample, or a stale operational flag does not supersede a durable event.

### What amendment does not do

- It does not drop raw telemetry into durable knowledge in order to "fix" history.
- It does not renumber or duplicate the subject. `device-demo-1` stays the subject; the event chain is what changes.
- It does not complete HOS-2. Executable conformance that these functions hold is still a planned milestone.

## Interaction vocabulary

The names below are vocabulary for reviewers and for later synthetic fixtures. They are not a storage schema, not a migration, not a HOUSE API payload, and not the issue #8 model. Issue #8 may use different fields. If a name here conflicts with that model, issue #8 wins.

The sample block illustrates `obs-demo-1`, which stays operational. The promotion block illustrates the later decision that cites `obs-demo-3` and writes `event-demo-1`.

### Operational sample

```text
id                 obs-demo-1
subject_ref        device-demo-1
reading            structure-only class label
freshness          current | stale
disposition        retain_operational | drop_after_window | candidate
```

`reading` is a class label such as `within_service_window` or `delivery_failed`. It is not a private measurement narrative, a schedule, or a household payload.

### Promotion decision

```text
id                 promotion-demo-1
candidate_refs     obs-demo-3
subject_ref        device-demo-1
rule_or_principal  rule-demo-service-due | person-1
decision           promote | hold_operational | reject
```

`promotion-demo-1` with decision `promote` is what allows `event-demo-1` to exist. `hold_operational` and `reject` leave durable knowledge unchanged.

### Durable event

```text
id                 event-demo-1
subject_ref        device-demo-1
transition         structure-only from-class → to-class
provenance_ref     promotion-demo-1
status             current | stale | corrected | superseded
supersedes         none | an earlier event-demo id
superseded_by      none | a later event-demo id
```

`event-demo-2` uses the same vocabulary when the transition is a repeated-failure history entry and `provenance_ref` cites `promotion-demo-2`.

Creating these labels in a fixture does not contact a provider, does not write a calendar object, and does not mark a work item done.

## Boundaries with neighboring notes

- [`AGENT_INTERACTION_CONTRACTS.md`](AGENT_INTERACTION_CONTRACTS.md) — proposals, approvals, and action receipts. A receipt can be evidence a promotion rule cites. The receipt is not itself the durable event.
- [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md) — canonical dated events and provider reconciliation. Provider staleness there follows that note's authority rules.
- [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md) — work items and the rule that chat is not the source of truth. A telemetry promotion does not create Kanban work unless an event-to-work rule already says so.
- SMP and Core — custody, evidence, and what makes a claim known. This note does not redefine those semantics. Promoting `event-demo-1` is a household policy decision about operational transitions. It does not bypass SMP evidence rules for a claim about a person.
- Issue #8 — entity, observation, event, capability, and provenance fields. This note stops at functions.

Private VAULT annotations stay in the principal's private trust domain. Connector secrets stay in deployment custody. Neither appears in a promotion example.

## Synthetic acceptance reading

The checks below are the acceptance reading of this policy for [issue #11](https://github.com/jryski/Household-OS/issues/11). They use fabricated identifiers only. They are not executable tests, and this note does not add any. HOS-2 remains the milestone that must demonstrate connector conformance, including troubleshooting fixtures, against fabricated adapters.

1. **Raw telemetry does not flood durable knowledge.** `obs-demo-1` is one sample for `device-demo-1`. No durable event is written. After the operational window the sample is dropped or compacted, and the compact is still not `event-demo-1`.
2. **An unchanged repeat is freshness, not a new event.** A later sample in the same class updates operational freshness for `device-demo-1`. Durable knowledge gains no second event.
3. **One failure stays operational.** `receipt-demo-1`, a single failed delivery toward `calendar-demo`, is an attempt record. It does not create troubleshooting history.
4. **A significant transition has explicit criteria and provenance.** `obs-demo-3` crosses `rule-demo-service-due` for `device-demo-1`. Promotion writes one `event-demo-1`. Provenance cites the supporting observations, `rule-demo-service-due`, and the decision time. Missing any of those blocks the write.
5. **Agent text is not promotion.** A statement by `agent-1` that `device-demo-1` is service due leaves durable knowledge unchanged until `promotion-demo-1` exists under a rule or under confirmation by `person-1`.
6. **Repeated failures become one trusted history entry.** `receipt-demo-1`, `receipt-demo-2`, and `receipt-demo-3` share a failure class and satisfy `rule-demo-repeat-failure`. One `event-demo-2` is promoted. It cites those attempts and the rule. It does not store every raw sample, and it does not add a root-cause claim.
7. **Recovery supersedes the current condition and keeps the history.** A later success promotes `event-demo-3`, which supersedes `event-demo-2` as the current condition. `event-demo-2` remains readable.
8. **Staleness is not deletion and not the opposite fact.** No further sample arrives for `device-demo-1`. Operational state is marked stale. `event-demo-1` is not deleted. Silence does not record the subject as healthy.
9. **A reporting gap is its own candidate.** When `rule-demo-reporting-gap` says prolonged silence is significant, that rule may promote a separate event with its own provenance. The new event does not rewrite `event-demo-1`.
10. **Correction preserves the original.** `person-1` corrects `event-demo-1`. The original statement stays addressable. The correction names `person-1`. `agent-1` cannot correct the event on its own authority.
11. **Supersession leaves a trail.** `event-demo-3` supersedes `event-demo-2` only with its own provenance. Current readers follow `event-demo-3`. History readers can still open `event-demo-2`.
12. **Chat is not the record.** A transcript line does not promote, correct, or supersede.
13. **Fixture hygiene.** Every identifier in this list is synthetic. The check fails if a fixture adds a real name, address, school, schedule, health or finance record, credential, calendar ID, provider object ID, private topology, or copied HOUSE or VAULT payload.

## Non-claims

- This note does not define issue #8 schema fields and does not pre-empt claude-warden's domain model.
- Conceptual field lists are interaction vocabulary. They are not HOUSE payloads and not a schema migration.
- Illustrative retention windows are expectations. They are not deployed configuration and not evidence of a running worker.
- HOS-2 stays `planned`. HOS-3 stays `planned`. Neither milestone is complete because this note exists.
- Trusted troubleshooting history is an auditable promotion. It is not a root-cause verdict and not a production incident record.
- Action receipts, calendar intake events, and Kanban work items keep the meanings already given in their own notes.
- No live connector, credential, or household deployment is claimed.

## Related documents

- [`AGENT_INTERACTION_CONTRACTS.md`](AGENT_INTERACTION_CONTRACTS.md) — proposals, approvals, and attempt receipts that this policy may cite and does not replace.
- [`ROADMAP.md`](ROADMAP.md) — HOS-2 synthetic connector conformance, which this note informs and does not complete.
- [`IMAGE_CALENDAR_INTAKE.md`](IMAGE_CALENDAR_INTAKE.md) — canonical dated events and provider reconciliation.
- [`PLANNING_WORK_PLANE.md`](PLANNING_WORK_PLANE.md) — work items, and the separation between chat and durable coordination records.
- [`README.md`](../README.md) — public-repository rule and system boundary.
- [Issue #8](https://github.com/jryski/Household-OS/issues/8) — household entity, observation, event, capability, and provenance model.
- [Issue #11](https://github.com/jryski/Household-OS/issues/11) — the policy deliverable this note drafts.
