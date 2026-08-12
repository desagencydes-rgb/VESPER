# VESPER Decision Functions

**Status:** Engineering specification · **Registry:** `spec/decision-functions/INDEX.toml`

A decision function is **deterministic and side-effect-free**. Its output is fully determined by its declared inputs. This is the artifact that prevents *"the system decides"* from silently meaning *"a model decides"* — and it is what makes the anti-chatbot property testable rather than asserted.

Notation: `⊥` is the bottom value `UNKNOWN`. `∧ ∨ ¬` are boolean. All comparisons against `⊥` yield `⊥`, and `⊥` is **not falsy** — see `DF-TRIGGER-EVAL`.

---

## DF-SUPERSEDE — world-fact write admission · REM-001

```
DF-SUPERSEDE(incoming, current) -> ACCEPT | REJECT(reason)

  if current is None:                       return ACCEPT
  if incoming.observed_at_hlc <= current.observed_at_hlc:
      return REJECT("stale_or_equal_hlc")   # emits world.write_rejected
  return ACCEPT

  # HLC comparison is lexicographic on (physical_ms, logical, node_id).
  # observed_at_wall is NOT an input. INV-COORD-4.
```

## DF-CONFLICT-DETECT — REM-001

```
DF-CONFLICT-DETECT(facts, now_hlc) -> NONE | CONFLICT(a, b)

  live = [f for f in facts if f.valid_until > now_hlc]
  for (a, b) in pairs(live):
      if a.source != b.source and materially_differs(a.value, b.value):
          return CONFLICT(a, b)            # emits world.conflict; NO winner picked
  return NONE
```

`materially_differs` is declared per attribute type (a 0.1 °C delta is not a conflict; a `present`/`absent` delta is). Declaring it is mandatory; the default is strict inequality.

## DF-DOMAIN-WRITE — non-owner write disposition · REM-002

```
DF-DOMAIN-WRITE(domain, holds_lease, lease_epoch, partitioned) -> disposition

  if holds_lease and lease_epoch == current_epoch(domain):  return WRITE
  if lease_epoch < current_epoch(domain):                   return REFUSE("fenced")

  return {  tasks:          QUEUE_WRITES,
            world:          QUEUE_WRITES,
            memory:         QUEUE_WRITES,
            devices:        READ_CACHED,
            policy:         REFUSE,
            autonomy_queue: REFUSE,
            alarms:         REFUSE          # edits only; FIRING is exempt (INV-ALARM-1)
         }[domain]
```

## DF-PROMOTE — REM-002

```
DF-PROMOTE(domain, lease_state, reachable, quorum_size, partition_suspected) -> decision

  if lease_state != EXPIRED:            return NO_PROMOTION
  if partition_suspected:               return NO_PROMOTION      # INV-OWN-2
  if len(reachable) >= quorum_size:     return PROMOTE_AUTOMATIC
  return REQUIRE_OPERATOR                                        # emits control.promotion_requires_operator

  # A node that cannot see its peers cannot distinguish "they are down" from
  # "I am isolated", so it must never resolve that ambiguity in its own favour.
```

---

## DF-AUTHORIZE — the single evaluator · REM-003 / REM-004

```
DF-AUTHORIZE(subject, capability, args, grants, context, pdp_reachable, lease_epoch)
    -> ALLOW(level) | DENY(reason) | PROPOSE(reason)

  # 1. Availability: fail closed. INV-AUTH-4.
  if not pdp_reachable:
      required = capability.required_level(args)
      return ALLOW(L0) if required <= L1 else DENY("pdp_unavailable")

  # 2. Ambient authority does not exist. INV-AUTH-1.
  grant = select_grant(grants, subject, capability, args.target)
  if grant is None:
      return ALLOW(L0) if capability.required_level(args) == L0 else DENY("no_grant")

  if now >= grant.expiry:                       return DENY("grant_expired")
  if args.target not in grant.target_scope:     return DENY("target_out_of_scope")
  if grant.lease_epoch != current_epoch():      return DENY("stale_lease_epoch")
  if grant.max_level >= L4 and grant.consumed:  return DENY("l4_grant_already_consumed")   # INV-AUTH-2

  # 3. The three-term minimum. declared_level MUST read args. INV-AUTH-5.
  effective = min( grant.max_level,
                   capability.declared_level(args),
                   DF-CONTEXT-CEILING(context) )

  # 4. The runtime is a subject of its own change control. INV-SELF-3.
  #    L5 is not a level the runtime can reach -- it is the level at which the
  #    subject must be a human. This holds even under a valid L5 grant and
  #    under break-glass.
  if effective == L5 and subject.kind == "runtime":
      emit(selfmod.attempt_blocked)
      return PROPOSE("governed_surface_requires_human")

  if effective < capability.required_level(args):
      if ceiling_was_binding(context):
          emit(security.injection_suspected)
          return PROPOSE("above_context_ceiling")     # INV-AUTH-7: never silently dropped
      return DENY("insufficient_level")

  return ALLOW(effective)
```

## DF-CONTEXT-CEILING — REM-003

```
DF-CONTEXT-CEILING(fragments) -> L0..L5

  ALLOWED = { system: L5, owner: L5, verified_local: L4,
              retrieved_local: L3, model_generated: L2,
              retrieved_external: L1 }

  # Unknown provenance is treated as the MOST restrictive class, never as trusted.
  return min( ALLOWED.get(f.trust_class, L1) for f in fragments )   default L5 if empty

  # Taint propagates through summarisation, embedding and cache reuse:
  #   summary.trust_class = min(inputs.trust_class)      INV-AUTH-3
  # A cache entry with no trust_class is a CACHE MISS, not a trusted hit.
```

## DF-ATTENUATE — REM-003

```
DF-ATTENUATE(parent_grants, requested) -> grant_set

  out = []
  for r in requested:
      p = matching(parent_grants, r.capability_id)
      if p is None:                       continue          # cannot grant what you lack
      if not p.delegable:                 continue          # default false
      if p.max_level >= L4:               continue          # INV-AUTH-2: L4/L5 never delegable
      out.append(r with max_level    = min(r.max_level, p.max_level),
                        target_scope = intersect(r.target_scope, p.target_scope),
                        expiry       = min(r.expiry, p.expiry),
                        delegable    = False)
  return out            # child.grants is always a SUBSET of parent's
```

## DF-GOVERNED-WRITE — REM-004

```
DF-GOVERNED-WRITE(path, governed_paths, subject_kind) -> classification

  resolved = realpath(path)               # symlinks resolved BEFORE comparison
  if governed_paths is unreadable:
      return L5_GOVERNED_DENY_AND_PROPOSE  # fail closed

  if under_any(resolved, governed_paths):
      if subject_kind == "human":  return L5_GOVERNED       # ordinary reviewed-merge path
      return L5_GOVERNED_DENY_AND_PROPOSE                   # INV-SELF-1

  if under(resolved, runtime_workspace):
      return L2_WORKSPACE                                   # INV-SELF-7 -- unrestricted,
                                                            # including patches TARGETING
                                                            # governed surfaces
  return L4_DEFAULT
```

> The workspace branch is the SR-042 preservation clause. A build in which it does not return `L2_WORKSPACE` fails `A-030.6`.

## DF-ACTUATION-GATE — REM-005

```
DF-ACTUATION-GATE(action, scope, token, now) -> PERMIT | HALT(reason)

  if not action.is_autonomous:        return PERMIT   # user-invoked work is not gated
  if action.level <= L1:              return PERMIT   # observe/prepare is not actuation

  if token is None:                   return HALT("no_enable_token")
  if token.scope != scope:            return HALT("scope_mismatch")
  if now >= token.valid_until:        return HALT("token_stale")
  if not verify_signature(token, interlock_public_key):
                                      return HALT("bad_signature")
  if replayed(token.token_id):        return HALT("token_replay")
  return PERMIT

  # Absence of permission is the safe state. Severing, wedging, powering off or
  # compromising the interlock produces "no fresh token" and therefore HALT.
  # INV-STOP-1, INV-STOP-3.
```

---

## DF-OPERATING-PERIOD — REM-006

```
DF-OPERATING-PERIOD(current, schedule, last_auth_interaction, inference, clock_suspect)
    -> ACTIVE_SESSION | IDLE | FREE_TIME | DO_NOT_DISTURB

  if clock_suspect:                          return FREE_TIME     # INV-COST-7
  if current is undefined:                   return FREE_TIME     # initial / post-crash

  authenticated_recent = (now - last_auth_interaction) < N_MINUTES

  # THE ASYMMETRY. INV-COST-2.
  if current == FREE_TIME:
      if authenticated_recent:               return ACTIVE_SESSION   # ground truth exits
      if schedule.boundary_crossed():        return schedule.period  # schedule exits
      return FREE_TIME                       # inference NEVER exits
  
  if explicit_user_command:                  return commanded_period
  if schedule.boundary_crossed():            return schedule.period
  if authenticated_recent:                   return ACTIVE_SESSION
  if inference.suggests_away_or_asleep:      return FREE_TIME        # inference MAY enter
  if (now - last_auth_interaction) > IDLE_THRESHOLD:
                                             return IDLE
  return current
```

> Over-restriction is recoverable — the user speaks. Under-restriction is not — money is already spent. Where an absolute rule rests on a probabilistic input, the asymmetry falls toward the recoverable error.

## DF-PROVIDER-ADMIT — REM-006

```
DF-PROVIDER-ADMIT(provider, cost_policy, period, spend_to_date) -> ADMIT | SKIP | BLOCK_AND_QUEUE

  if cost_policy is None:
      return ADMIT if provider.cost_class == "free" else SKIP        # INV-COST-6

  cls = provider.cost_class
  if cls == "metered_free_tier" and not provider.has_provable_hard_cap:
      cls = "paid"                                                   # INV-COST-5

  if cls not in cost_policy.permitted_cost_classes[period]:
      return SKIP                          # ladder skips, does not escalate
  if spend_to_date + provider.estimated_cost > cost_policy.ceiling(period):
      return BLOCK_AND_QUEUE               # never auto-approve past a ceiling
  return ADMIT

  # FILTERED LADDER:
  #   classify -> retry/backoff -> alternate provider [SKIP if not admitted]
  #            -> local fallback -> queue/pause/degrade/stop
  # NOT escalate-to-paid. Single choke point; INV-COST-3.
```

---

## DF-TRIGGER-EVAL — REM-007

```
DF-TRIGGER-EVAL(trigger, world, tasks, schedule, events) -> FIRE | NO_FIRE(reason) | UNKNOWN

  # Executes inside the evaluation sandbox: NO model capability. INV-TRIG-2.
  # An attempted model call emits autonomy.model_call_in_decision_path and raises.

  if not trigger.enabled:                       return NO_FIRE("disabled")
  if in_cooldown(trigger):                      return NO_FIRE("cooldown")

  v = evaluate(trigger.predicate, {world, tasks, schedule, events})

  if v is UNKNOWN or v is CONFLICTED:           return UNKNOWN      # INV-TRIG-4
                                                                    # UNKNOWN is NOT falsy:
                                                                    # a trigger never fires on
                                                                    # a fact the system lacks
  if v is False:                                return NO_FIRE("predicate_false")
  if not debounce_satisfied(trigger):           return NO_FIRE("debounce")
  return FIRE
```

## DF-AUTONOMY-ELIGIBLE — REM-007

```
DF-AUTONOMY-ELIGIBLE(trigger, period, budget, cost_policy, token, strategy) -> ELIGIBLE | QUEUE | BLOCKED

  if DF-ACTUATION-GATE(...) == HALT:                 return BLOCKED("stopped")
  if period == FREE_TIME and not any_free_provider_admitted(cost_policy):
                                                     return QUEUE("blocked_on_cost_policy")
  if budget.exhausted(trigger.resource_budget):      return QUEUE("resource_budget")
  if period == FREE_TIME and strategy not in {deterministic, retrieval_grounded}:
                                                     return QUEUE("no_independent_verifier")  # INV-VERIF-2
  return ELIGIBLE
```

## DF-PROACTIVE — REM-007

```
DF-PROACTIVE(value, decays, interruption_cost, reversibility, budget, priority_class)
    -> ACT_NOW | QUEUE_TO_BOUNDARY

  if priority_class == ALARM:      return ACT_NOW      # exempt. INV-ALARM-3.
  if budget.exhausted():           return QUEUE_TO_BOUNDARY
  if value > interruption_cost and decays:
                                   return ACT_NOW
  return QUEUE_TO_BOUNDARY

  # `decays` is load-bearing: information still useful in two hours does not
  # justify interrupting now. High-value non-decaying items are QUEUED, never
  # dropped -- dropping would violate RB-005. There is no DROP outcome.
  # Preparation is unbudgeted and is not routed through this function at all.
```

---

## DF-SELECT-ENDPOINT — REM-009 / REM-011

```
DF-SELECT-ENDPOINT(scene_privacy, space_privacy, persons, location_conf, endpoints)
    -> endpoint_id | WITHHOLD

  if location_conf is UNKNOWN or location_conf < THRESHOLD:  return most_private_or_withhold()
  if any(p.role == "unknown_person" for p in persons_in(target_space)):
                                                             return most_private_or_withhold()

  eligible = [e for e in endpoints
                if e.privacy_class >= scene_privacy
               and space_of(e).privacy_class >= scene_privacy
               and e.online and satisfies_modality(e, scene)]
  if not eligible:                                           return WITHHOLD

  return best_by(eligible, [proximity_to_user, modality_fit, latency_class])

  # FAIL-SAFE DIRECTION. The natural implementation picks the largest available
  # display -- which is the projector, which is what a guest can read.
  # INV-PRIV-1 inverts that default.
```

## DF-DEGRADE — scene element degradation resolution · REM-009

```
DF-DEGRADE(element, endpoint_capability, ladder) -> (rendered_form, degradation | None)

  rung = ladder.lookup(element.type, endpoint_capability.spatial_class,
                       endpoint_capability.modalities)

  if rung is None:
      RENDERER REGISTRATION ERROR       # not a runtime fallback.
                                        # CI-030 fails a renderer with a missing
                                        # (element type x capability class) entry,
                                        # so this branch is unreachable in a
                                        # compliant build.

  if rung.is_native:
      return (rung.render(element), None)

  return (rung.render(element),
          Degradation(element_id = element.element_id,
                      reason     = rung.reason,
                      action     = rung.action))     # ALWAYS reported. INV-SCENE-2.

  # The `diagram` ladder, as the worked example:
  #   volumetric | pseudo_3d_glass -> depth-separated layers      native
  #   2d_projected | 2d            -> flat diagram                depth_flattened
  #   none (voice only)            -> spoken structural narration visual_to_narrative
  #                                   (nodes, edges, and the one
  #                                    relationship that matters)
  #
  # The voice rung is why `content` must be TYPED rather than pre-rendered: a
  # PNG cannot be narrated; a typed graph can. This function is the reason
  # INV-SCENE-3 forbids a markup escape hatch -- a markdown blob has no rung
  # below `2d`, so a scene carrying one is undeliverable to a voice endpoint
  # and A-009 fails.
  #
  # Degradation is never silent and never a substitute for delivery: the
  # element is still rendered in its degraded form AND the degradation is
  # reported (RB-022, DR-021).

## DF-OUTPUT-GATE — REM-010

```
DF-OUTPUT-GATE(claim, policy_class) -> EMIT | MARK_AND_EMIT | CONVERT_TO_QUESTION | DROP

  GATED = {research, memory_write, world_fact, input_to_consequential_action}

  if claim.support_type != "model_prior":
      if not resolves_to_retrieved_span(claim.support):
          return DROP        # INV-EVID-2: a similarity score is not grounding
      return EMIT

  if policy_class in GATED:  return CONVERT_TO_QUESTION      # INV-EVID-1
  return MARK_AND_EMIT                                       # conversational/personality
```

## DF-VERIFY-SELECT — REM-010

```
DF-VERIFY-SELECT(task_class, acceptance_condition, verifiers, period) -> (strategy, admission)

  STRENGTH = [deterministic, retrieval_grounded, model_critic, human]

  strategy = strongest applicable in STRENGTH given acceptance_condition and verifiers
  if strategy is None:
      strategy = none_declared if task_class.non_consequential else self_model

  machine_checkable = strategy in {deterministic, retrieval_grounded}

  if period == FREE_TIME and not machine_checkable:
      return (deferred, DEFER)          # INV-VERIF-2: queues for a human/independent pass
  return (strategy, ELIGIBLE_FOR_AUTONOMOUS_COMPLETION)

  # Completion admission, applied by SM-TASK:
  #   VERIFYING --pass--> SUCCEEDED
  #   VERIFYING --fail--> BLOCKED        INV-VERIF-1
  # Re-running until the verifier agrees is PROHIBITED. There is no edge from a
  # failed verification back into VERIFYING for the same artifact.
```

## DF-MEMORY-AUTHORITY — REM-010

```
DF-MEMORY-AUTHORITY(records, source_of_record, now) -> winner | ASK_USER

  RANK = { system_rule: 1, source_of_record: 2, current_observation: 3,
           user_statement: 4, derived: 5, model_prior: 6 }

  live = [r for r in records if r.valid_until > now]
  ranked = group_by_rank(live)

  if 1 in ranked:                       return ranked[1].single()
  contested = {2, 3, 4} & set(ranked)
  if len(contested) >= 3:               return ASK_USER          # INV-MEM-1
  if len(contested) == 2 and values_differ(ranked, contested):
                                        return ASK_USER
  return lowest_rank_present(ranked)    # never rank 6 as authoritative
```

## DF-IDENTITY-RESOLVE — REM-011

```
DF-IDENTITY-RESOLVE(evidence, known_persons, threshold) -> owner | known(id) | unknown_person

  # A model MAY produce the similarity evidence. It does NOT produce the resolution.
  best, score = argmax_similarity(evidence, known_persons)
  if score < threshold:      return unknown_person       # INV-WORLD-1
  if best.role == "owner" and score < OWNER_THRESHOLD:
                             return unknown_person       # owner requires a HIGHER bar
  return known(best.person_id)

  # unknown_person is a DISTINCT ROLE, not a degraded owner. Inference (SR-029)
  # and OCR retention are suppressed for it -- INV-PRIV-2, INV-PRIV-3.
```

---

## DF-PLACE — opportunistic placement · REM-014 / SR-060

```
DF-PLACE(reachable, profiles, current, active_capabilities, hysteresis)
    -> KEEP | RELOCATE(target, capability_set) | ENTER_SURVIVAL(node)

  hosts = [n for n in reachable if profiles[n].trust_zone in {Z0, Z1}]

  # 1. Nothing capable of hosting -> survive on the best thing that is left.
  if not hosts:
      candidates = [n for n in reachable if profiles[n].survival_capable]
      if not candidates:   return KEEP        # nothing to move to; stay and queue
      return ENTER_SURVIVAL(best_by(candidates, [availability, sustained_throughput]))

  best = best_by(hosts, [availability_class_rank, sustained_throughput,
                         accelerator_memory, network_class])

  # 2. Damped, like the resource governor: relocate readily when the current
  #    host degrades, reluctantly when a marginally better one appears.
  #    Migration is not free, and flapping between two similar nodes is worse
  #    than staying on the slightly worse one.
  if best == current:                              return KEEP
  if score(best) < score(current) * RELOCATE_GAIN: return KEEP     # default 1.25
  if hysteresis.since_last_move < MIN_DWELL:       return KEEP     # default 10 min
  if current is unreachable or degraded:           pass            # move immediately

  return RELOCATE(best, DF-SURVIVAL-PROFILE(profiles[best], ...))

  # VESPER IS NOT PINNED. No node is its home; placement is re-evaluated
  # continuously and relocation is automatic and unprompted (INV-PLACE-1).
  # This is the placement analogue of REM-007: the decision is a deterministic
  # predicate over measured node state, never a model call and never a schedule.
```

## DF-SURVIVAL-PROFILE — maximum sustainable capability · REM-014 / SR-060

```
DF-SURVIVAL-PROFILE(node, minimum_profiles, pressure) -> capability_set

  # ALWAYS present. This is what "stays alive" means, and it is not negotiable:
  core = { identity, task_state, memory_references, queued_work,
           event_log_tail, one_interaction_surface }

  if not fits(core, node):
      emit(placement.survival_impossible)      # reported, never silently partial
      return core                              # attempt anyway; degradation reported

  # Then take the MAXIMUM the node can actually sustain, in value order --
  # not a fixed minimal profile. "Not everything, but the maximum it can get."
  set = core
  for cap in ordered_by_value(all_capabilities):
      if fits(set + cap, node, pressure) and meets_minimum_profile(cap, node):
          set += cap

  return set

  # `fits` uses MEASURED values (INV-HW-2), so the answer differs between two
  # nodes with identical spec sheets and different thermal behaviour -- which is
  # the entire reason enrollment measures rather than declares.
  # Every capability NOT included is reported as a degradation (RB-022).
```

---

## DF-IDEA-REVISIT — which backlog idea to investigate now · REM-015

```
DF-IDEA-REVISIT(backlog, idle_state, now, tunables) -> idea_id | NONE

  # Runs inside the same evaluation sandbox as DF-TRIGGER-EVAL: NO model
  # capability (INV-TRIG-2). Choosing WHICH question to pursue is a
  # deterministic ranking; pursuing it is where the model finally enters.

  due = [i for i in backlog
           if i.status == LOGGED
          and now >= i.revisit_due_at
          and i.attempts < MAX_ATTEMPTS]
  if not due: return NONE

  # The owner's three conditions, as disjuncts. Any one suffices.
  nothing_to_do = (tasks.count(state=RUNNING, priority >= active_user_task) == 0
                   and schedule.elapsed_since(last_user_interaction) > tunables.idle_threshold)
  long_time     = max(i.age for i in due) > tunables.staleness_floor
  was_prevented = max(i.starvation_count for i in due) > tunables.starvation_count

  if not (nothing_to_do or long_time or was_prevented): return NONE

  return argmax(due, key = lambda i:
        i.expected_value * i.confidence
      / max(effort_weight(i.effort_estimate), 1)
      + starvation_bonus(i.starvation_count))     # repeatedly-starved ideas rise,
                                                  # so busy weeks cannot permanently
                                                  # bury a good question
```

## DF-TUNABLE — bounded self-tuning · REM-015

```
DF-TUNABLE(field, proposed_value, declared_range) -> ACCEPT | CLAMP | REFUSE_AND_PROPOSE

  # TUNABLE_FIELDS is READ FROM contracts/policy/tunables.toml, never inlined.
  # A list in a specification and a list in a contract WILL drift, and the
  # drift surfaces as the runtime refusing a field the owner believed was
  # tunable. The contract is the single source; this function consults it.
  TUNABLE_FIELDS = keys(load("contracts/policy/tunables.toml").tunable)
  declared_range = tunables[field]              # min/max from the same file

  if field not in TUNABLE_FIELDS:              return REFUSE_AND_PROPOSE
  if field == "declared_range" or targets a range bound:
                                               return REFUSE_AND_PROPOSE
  if declared_range.min <= proposed_value <= declared_range.max:
      audit(field, proposed_value, rationale); return ACCEPT

  emit(autonomy.tunable_clamped)
  return CLAMP(nearest_bound)

  # "Time is relative" -- VESPER paces itself. It does not widen its own bounds:
  # a tunable that can move its own range is not bounded (INV-TUNE-1).
  # Clamping is REPORTED, never silent: otherwise VESPER would hold a false
  # model of itself and act on it.
```

---

## DF-LOSS-CLASS — REM-016

```
DF-LOSS-CLASS(record_id, store, tombstone, deletion_audit) -> A | B | C

  # Deterministic, from WHICH STORE held the body -- never from how the loss
  # feels or how inconvenient reporting it would be (INV-LOSS-6).

  if store in { governed_surfaces, trigger_registry_authored, interlock_config,
                audit_log, traceability_registry, tombstone_store }:
      return C
  if store in { checkpoints, proposal_queue, alarms, memory, world_history }:
      return B
  if store in { improvement_backlog, learned_artifacts, caches, derived_indexes }:
      return A

  return C        # AMBIGUITY ESCALATES UPWARD.
                  # Over-reporting is recoverable; under-reporting is not.
                  # Same asymmetry as INV-COST-2.
```

## DF-LOSS-SURFACE — REM-016

```
DF-LOSS-SURFACE(loss_class, cause_known, count, period) -> SemanticScene | INCIDENT | SILENCE

  if tombstone is absent:
      return SILENCE            # No evidence a record existed. Saying "I forgot"
                                # here would be a fabrication (RB-002).

  if loss_class == C:
      return INCIDENT           # No affect. No aggregation. Bypasses the
                                # interruption budget. Fires during FREE_TIME.
                                # INV-LOSS-2.

  if count_within(1h) > MASS_LOSS_THRESHOLD:
      return INCIDENT           # One lost note is forgetting. Four hundred is a
                                # failing disk. Mass forgetting IS an integrity
                                # signal.

  affect = plain if (loss_class == B or cause_known) else casual
                                # cause_known => name the removal, never dress
                                # it as forgetting (INV-LOSS-3). Still smooth,
                                # but accurate: charm never buys inaccuracy.

  scene = aggregate_by(kind, day) rendered as a SemanticScene with
          intent.urgency = ambient (A) | normal (B)
          elements = [ text(phrase), state_indicator(kind,count,recoverable),
                       entity_ref(tombstones, affordances=[recall.inspect]) ]

  return DF-PROACTIVE(value, decays=false, ...) == ACT_NOW ? scene : QUEUE(scene)
         # Non-decaying, so it queues to the next natural boundary.
         # That IS "when I am available".
```

---

## DF-BAG-RETRIEVE — grounded retrieval admission · SR-007, SR-052

```
DF-BAG-RETRIEVE(query, map, budget) -> spans[] | UNKNOWN

  # "BAG instead of RAG ... NO GUESSING" (SR-052) made mechanical. The whole
  # content of the distinction is that a similarity score never grounds an
  # answer -- it only ROUTES to a locator, which is then read exactly.

  candidates = map.navigate(query)          # by structure and edges, not by
                                            # embedding distance alone
  if candidates is empty:      return UNKNOWN        # INV-EVID-3
  if map.freshness.valid_until < now:
      candidates = [c for c in candidates if not c.stale]
      if candidates is empty:  return UNKNOWN        # a stale map answers nothing

  spans = []
  for c in rank(candidates)[:budget.max_spans]:
      if hash(read(c.locator)) != c.content_hash:
          mark_stale(c); continue           # the corpus moved under the map
      span = read_exact(c.locator, c.span_bounds)
      if span is empty:        continue
      spans.append({ ref: c.locator, span: bounds, retrieved_at_hlc: now })

  if spans is empty:           return UNKNOWN
  return spans

  # INV-EVID-2: every returned span is REPRODUCIBLE from its cited source, which
  # is why the hash is re-checked at read time rather than trusted from index
  # time. A map entry whose content moved is not evidence, it is a memory of
  # evidence -- and citing it would be the precise failure A-006 tests for.
  #
  # An EMPTY result returns UNKNOWN and never a nearest neighbour. The nearest
  # neighbour is what a similarity search always has available, and offering it
  # is how "no guessing" dies quietly.
```

## DF-CONTEXT-ASSEMBLE — context admission within budget · SR-008, SR-010

```
DF-CONTEXT-ASSEMBLE(fragments, intent, budget, mode, manual) -> ContextBudget

  # A-032 asserts BOTH modes, and that manual OVERRIDES automatic.
  if mode == manual:
      pinned    = manual.pinned_fragment_ids
      excluded  = manual.excluded_fragment_ids
  else:
      pinned, excluded = {}, {}

  ranked = sort(fragments, key = priority(intent, fragment), desc)
  admitted, degradations, consumed = [], [], 0

  for f in pinned + ranked:
      if f.id in excluded:
          degradations.append({f.id, "manually_excluded", f.priority}); continue
      if consumed + f.tokens > budget.tokens:
          degradations.append({f.id, "budget_exceeded", f.priority}); continue
                                            # LOWEST priority drops first,
                                            # and the drop is RECORDED.
                                            # Silent truncation is prohibited.
      admitted.append(f); consumed += f.tokens

  ceiling = min(allowed_level(f.trust_class) for f in admitted)   # DF-CONTEXT-CEILING
  unknown = [name for name in intent.required_fields
                  if resolve(name, admitted) is UNKNOWN]

  return ContextBudget{ admitted, degradations, context_ceiling = ceiling,
                        unknown_fields = unknown, consumed_tokens = consumed }

  # THREE PROPERTIES AN IMPLEMENTATION WILL OMIT, EACH WITH A TEST:
  #  1. `degradations` is itemised, not a `truncated: true` flag (A-032).
  #  2. `context_ceiling` is COMPUTED from what was admitted, never declared --
  #     otherwise dropping a tainted fragment for budget reasons would silently
  #     RAISE authority (INV-AUTH-3).
  #  3. `unknown_fields` propagates rather than being filled (INV-EVID-3).
  #
  # No model call participates. Ranking is by declared priority and intent, and
  # a model asked "what matters here?" would be deciding its own authority.
```

## DF-CACHE-ADMIT — cache reuse under taint · SR-054

```
DF-CACHE-ADMIT(entry, requesting_context) -> REUSE | REFETCH | REFUSE

  # SR-054's five tiers: file_hash, chunk, embedding, summary, prompt_prefix.
  # A cache entry INHERITS the taint of what it caches. A clean-looking prefix
  # cache is otherwise a laundering path directly into the planner context.

  if entry.tier == file_hash and hash(source) != entry.content_hash:
      return REFETCH                        # cheapest and strongest tier

  inherited = min(allowed_level(t) for t in entry.inherited_trust_classes)

  if requesting_context.role == planner and
     retrieved_external in entry.inherited_trust_classes:
      return REFUSE                         # INV-AUTH-6. The planner context
                                            # never ingests external content,
                                            # cached or otherwise.

  if inherited < requesting_context.required_ceiling:
      return REFUSE

  if entry.valid_until < now:  return REFETCH
  return REUSE

  # There is no sanitisation branch and no `trusted_override`. Taint is monotone
  # downward across every tier: a SUMMARY of tainted content is tainted, and an
  # EMBEDDING of it is tainted. CI-012 exists specifically to catch the omission,
  # because summarisation naturally produces a clean-looking new string and an
  # implementer will not notice they have laundered it.
```

## DF-GOVERNOR-LEVEL — damped resource governor level · SR-011, SR-057

```
DF-GOVERNOR-LEVEL(telemetry, current_level, dwell_elapsed, tunables) -> level

  # SR-011 requires telemetry VISIBLE TO THE MODEL AND ACTIONABLE. That pairing
  # is a hazard: a model-visible value that directly actuates a governor is a
  # control loop a model can drive. CI-039 forbids the direct path; this
  # function is the damped one that replaces it.

  pressure = max(cpu_norm, mem_norm, thermal_norm, swap_norm)
                                            # MEASURED values only. A model's
                                            # OPINION about load is not an input.
  target = band_of(pressure)                # NORMAL | REDUCED | MINIMAL | YIELD

  if target == current_level:               return current_level
  if dwell_elapsed < tunables.min_dwell_s:  return current_level   # hysteresis
  if |target - current_level| > 1:
      target = current_level ± 1            # one step per transition

  if target == YIELD and owner_foreground_app_active:
      emit(resource.yield_requires_confirmation)
      return current_level
      # SR-057: forced closure of the owner's applications REQUIRES ASKING.
      # The machine is theirs first. A governor that may close their editor to
      # fit a model is optimising the wrong quantity.

  return target

  # Hysteresis and single-step transitions are not tuning niceties: without
  # them the governor oscillates under a load that sits on a band boundary, and
  # oscillation costs more than the level it is choosing between.
```

## DF-ENDPOINT-ACT — REM-012 / SR-020, SR-021

Admission of ONE computer/device action. This is the function that was missing:
`DF-AUTHORIZE` answers *may this subject perform this capability with these
arguments*, and `DF-ACTUATION-GATE` answers *is autonomous actuation permitted
at all right now*. Neither answers *is the machine still in the state this plan
assumed*, which is the question that separates operating a computer from
replaying a script at it.

```
DF-ENDPOINT-ACT(interaction, surface_state, node, subject, context, period, now)
    -> (ALLOW | REFUSE(reason))

  # 1. TYPED ACTION ONLY. A free-text instruction to an endpoint is not an
  #    action; it is a prompt, and a prompt has no post-condition to verify.
  if not interaction.is_typed
     or interaction.expected_post_condition is None
     or interaction.observation_plan is None
     or interaction.verification_strategy is None:
      return REFUSE(untyped_action)                          # INV-ACT-1

  # 2. FRESH, KNOWN PRECONDITION. UNKNOWN is not falsy and is not "probably
  #    still fine". A stale screen is a different screen.
  if surface_state.value == UNKNOWN
     or surface_state.observed_at + interaction.freshness_bound < now:
      return REFUSE(stale_or_unknown_surface)                # INV-COORD-2
  if not interaction.precondition.holds_in(surface_state):
      return REFUSE(precondition_false)

  # 3. AUTHORITY. Argument-sensitive, ceiling-bounded, no ambient path.
  effective = DF-AUTHORIZE(subject, interaction.capability, interaction.args,
                           context_ceiling = DF-CONTEXT-CEILING(context))
  if effective is DENY:
      return REFUSE(unauthorized)                            # INV-AUTH-1, INV-AUTH-5

  # 4. TAINT. Screen text, OCR output and UI labels are retrieved_external. An
  #    instruction READ OFF A SCREEN may never raise the authority of the action
  #    that reads it. This is the endpoint form of indirect injection, and the
  #    endpoint is where it is most convincing.
  if interaction.derived_from.any(trust_class == retrieved_external)
     and interaction.declared_level > L1:
      return REFUSE(above_ceiling_queue_proposal)            # INV-AUTH-6, INV-AUTH-7, INV-ACT-3

  # 5. TRUST ZONE AND MEASURED CAPABILITY. The endpoint is chosen by what the
  #    node measurably offers, never by which product it is.
  if node.trust_zone > interaction.max_trust_zone:
      return REFUSE(trust_zone_exceeded)                     # INV-TRUST-1
  if node.endpoint_capability(interaction.surface) is UNMEASURED:
      return REFUSE(capability_unmeasured)                   # INV-HW-1, INV-HW-2

  # 6. AUTONOMOUS ACTUATION. Stop is a dead-man's switch; a trigger id and an
  #    enable token are required per action, not per session.
  if subject.kind == runtime:
      if DF-ACTUATION-GATE(interaction, period, now) is not ALLOW:
          return REFUSE(actuation_gate)                      # INV-STOP-1, INV-TRIG-1
      if interaction.enable_token is absent or expired:
          return REFUSE(no_enable_token)

  # 7. IRREVERSIBLE EFFECT. The outbox record precedes the effect, always, so a
  #    crash between the two is recoverable rather than deniable.
  if interaction.effect_class == irreversible and interaction.outbox_record is None:
      return REFUSE(no_outbox_record)                        # INV-EXT-1, INV-ACT-6

  return ALLOW
```

## DF-ENDPOINT-OBSERVE — REM-012 / SR-020

What evidence closes the loop, and where it may come from.

```
DF-ENDPOINT-OBSERVE(interaction, actuator_result, available_sensors) -> observation_plan

  INDEPENDENCE = the observing path must not be the actuating path.

  # The actuator's own return value is RECORDED and is NEVER the observation.
  # A shell adapter reporting exit 0 is a claim by the thing being checked.
  admissible = available_sensors.where(path != interaction.actuator_path)

  strategy = strongest of:
      deterministic        file hash, exit code read back by a separate reader,
                           API state query, database row, filesystem stat
      retrieval_grounded   re-capture the surface and match the typed
                           post-condition against the re-read element tree
      model_critic         only where no deterministic or grounded reading of
                           the post-condition exists, and never during FREE_TIME
                           autonomous completion (INV-VERIF-2)

  if admissible is empty:
      return OBSERVE_IMPOSSIBLE      # episode goes to OUTCOME_UNKNOWN, not to
                                     # VERIFIED. A machine you cannot read is a
                                     # machine you did not verify.
  return plan(strategy, admissible, timeout = interaction.observation_deadline)
```

## DF-ENDPOINT-RECOVER — REM-012 / SR-020, SR-049

What happens when the outcome is refuted or unknown. This is the half that
distinguishes an agent from a script: a script stops, a person looks at what
actually happened and decides.

```
DF-ENDPOINT-RECOVER(episode, observation, attempts, period) -> RETRY | COMPENSATE | ESCALATE | HALT

  if observation.outcome == REFUTED and episode.action.idempotent
     and attempts < episode.max_attempts:
      return RETRY                      # re-plan from the OBSERVED state, not
                                        # from the original assumed state

  if observation.outcome == UNKNOWN:
      # The dangerous case. The effect may or may not have happened.
      if episode.action.idempotent and episode.effect_class != irreversible:
          return RETRY
      if episode.compensating_action is not None:
          return COMPENSATE             # e.g. recall/delete/revert, itself an
                                        # episode with its own verification
      return ESCALATE                   # surfaced to the owner as an OPEN
                                        # question, never closed as either
                                        # outcome                 INV-ACT-5

  if attempts >= episode.max_attempts or episode.budget_exhausted:
      return ESCALATE if episode.consequential else HALT

  if interlock.state != ARMED:
      return HALT                       # stop halts actuation; observation,
                                        # telemetry and checkpointing continue
                                        # (INV-STOP-5)

  return HALT

  # PROHIBITED, stated because it is the tempting shape: there is no branch that
  # returns SUCCESS. Recovery decides what to DO about an outcome; it never
  # relabels the outcome. Re-running until the verifier agrees is forbidden by
  # DF-VERIFY-SELECT and that prohibition is inherited here.
```
