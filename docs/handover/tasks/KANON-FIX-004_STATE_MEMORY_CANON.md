# TASK: KANON-FIX-004_STATE_MEMORY_CANON

- STATUS: DONE

## Goal

Uvesti **State/Memory SSOT** kao jedini kanonski sloj za:
- sistemsku memoriju (STM/analytics),
- audit podatke koji se akumuliraju (append-only),
- stabilan read API za druge servise (nema “random dict” po servisima).

Za Level 1 backend ostaje lokalni (file-backed) i thread-safe.

## Context

U kodu već postoji `services/memory_service.py`, ali nije formaliziran kao SSOT i nedostajale su jasne:
- semantike append-only kanala (npr. write audit),
- stabilan injection model (AuditService treba da koristi istu memoriju),
- stabilnost “approval pending list” kroz različite instance u procesu.

## Scope

**In scope**
- Standardizovati `MemoryService` kao kanonski state sloj (jedna semantika, thread-safe).
- Dodati/učvrstiti append-only kanal za **write audit events** (npr. `write_audit_events`) koji koristi WriteGateway.
- Omogućiti `AuditService` da koristi isti `MemoryService` (dependency injection).
- Stabilizovati approval state da se izbjegne “approval not found in pending list” (global backing store).

**Out of scope**
- Redis / DB backend.
- Multi-process distribucija state-a.
- Novi business feature-i.

## Design

### MemoryService (SSOT)
- Lokalni JSON storage (file-backed) + cache u procesu.
- Thread-safe `_lock`.
- Kanonske kolekcije:
  - `entries`, `decision_outcomes`, `execution_stats`, `cross_sop_relations`, `goals`, `plans`, `active_decision`
  - `write_audit_events` (append-only)

### AuditService
- READ-ONLY servis koji čita iz `MemoryService`.
- Omogućen injection `memory_service` da se koristi isti singleton u procesu.

### ApprovalStateService
- Global backing store (class-level) da svaka instanca vidi isti pending/approved state.

## Files touched

- `services/memory_service.py`
- `services/audit_service.py`
- `services/approval_state_service.py`

## Tests

- `.\test_runner.ps1` — **ALL HAPPY PATH TESTS PASSED**

## Closure

Task je DONE jer:
- postoje stabilni append-only audit podaci u MemoryService (write audit events),
- AuditService koristi kanonski MemoryService (injectable),
- approval pending list je stabilan (global backing store),
- svi HAPPY path testovi prolaze.
