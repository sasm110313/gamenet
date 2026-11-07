# Phase 1 — Customers, pricing, wallets, ledger and sessions

Status: implemented and covered by the automated backend suite on the Linux dev
host. Windows hardware acceptance from Phase 0 is still pending and is not
claimed here.

## Scope

Phase 1 adds the first real business domain on top of the Phase 0 transport:

- tariffs and customer groups;
- customers with credit limits and optional group membership;
- wallets with deposits, manual adjustments and reversals;
- an append-only money ledger;
- gaming sessions with exact elapsed-time charging;
- read-only cloud projections of every edge fact;
- edge and cloud dashboards for the new aggregates.

The edge remains the only writer of customer, pricing, wallet, ledger and session
facts. The cloud stores replicas and serves reporting; it never recomputes money
or last-write-wins an edge fact.

## Data model

| Model | Owner | Key rules |
|---|---|---|
| `pricing.Tariff` | Edge | Positive hourly rate; unique name per edge; never reprices a live session |
| `customer_groups.CustomerGroup` | Edge | Unique name per edge; optional tariff; inactive group cannot start a session |
| `customers.Customer` | Edge | Unique non-empty phone per edge; non-negative credit limit; cannot deactivate with an active session |
| `wallets.Wallet` | Edge | One per customer; balance may go down to `-credit_limit` |
| `ledger.LedgerEntry` | Edge | Append-only; non-zero signed `amount`; `balance_after`; one `SESSION_CHARGE` per session |
| `sessions.GamingSession` | Edge | One ACTIVE session per device; tariff name/rate snapshot; end fields match status |

Defaults come from the environment: `DEFAULT_HOURLY_RATE=40000` Toman/hour and
`DEFAULT_CREDIT_LIMIT=60000` Toman.

## Money rules

All amounts are integer Toman. Elapsed-time cost uses half-up integer rounding:

```
cost = (hourly_rate * elapsed_seconds + 1800) // 3600
```

- The session copies `tariff_name` and `hourly_rate` at start, so changing a
  tariff later affects only future sessions.
- Starting a session reserves one billable hour for every active session of that
  customer. The check is:
  `balance + credit_limit - sum(active.hourly_rate) >= new_hourly_rate`.
- Stopping a session charges actual elapsed time and is allowed to exceed the
  credit limit, because the time was already consumed.
- A session that ends with zero cost writes no ledger row; the database rejects
  `amount = 0` anyway, and the session status is the idempotency guard.
- Deposits require a positive amount; adjustments require a non-zero amount.
  A reversal is the negated original row and is unique per original.
- Ledger entries cannot be updated or deleted. Corrections are new reversal rows
  that reference the original entry.

## Concurrency and lock order

All wallet-affecting paths use one canonical order:

```
customer row (SELECT FOR UPDATE)
  -> customer advisory lock
    -> wallet row (SELECT FOR UPDATE)
```

Session stop first locks the session row, then follows the same order. This
serialises concurrent starts for the same customer so they re-read the committed
balance and active-session exposure before passing the credit check. Concurrent
deposits also cannot lose money.

## Session lifecycle

1. Operator selects an active customer and an idle/online/locked device.
2. Edge validates ownership, device state, tariff/group activity and credit.
3. Edge creates the ACTIVE session and queues a `client.unlock` device command.
4. `session.started` is emitted in the same transaction.
5. On stop, the edge locks the session, computes elapsed time from
   `started_at`, posts the `SESSION_CHARGE` ledger entry once, marks the session
   COMPLETED and queues `client.lock`.
6. `session.ended` is emitted with duration, cost and the ledger entry id.

A duplicate stop returns the existing state and charge. A device can hold only
one ACTIVE session; a customer may hold several concurrent sessions as long as
the one-hour reservation per session passes.

## Replication

Phase 1 event types are registered in `KNOWN_EVENT_TYPES` and projected by
`apps/synchronization/handlers.py`:

- `tariff.created` / `tariff.updated`
- `customer_group.created` / `customer_group.updated`
- `customer.created` / `customer.updated`
- `ledger.entry_created`
- `session.started` / `session.ended`

Projection behaviour:

- Upserts are idempotent.
- A group with an unknown tariff, a customer with an unknown group, a ledger
  entry with an unknown customer/session/reversed entry, or a session with an
  unknown customer/device/tariff rejects the event. The cloud does not store a
  partial fact, and the edge retries after the reference arrives.
- A customer event never overwrites an existing replica wallet balance; only the
  ledger stream may move it.
- `(edge, event_id)` deduplicates duplicates, a reused sequence with a different
  event id is rejected, and per-aggregate regression is rejected.

The edge outbox drains strict FIFO. A FAILED head blocks later financial events;
the dashboard exposes the block and a manual retry action. The acknowledgement
watermark advances only over a contiguous acknowledged prefix.

## Dashboard routes

Edge (authoritative, authenticated):

| Route | Purpose |
|---|---|
| `/customers/` | Search, create and inspect customers |
| `/customers/<id>/` | Profile, wallet, ledger history, sessions, deposit/adjust/reverse and session actions |
| `/sessions/` | Active and recent sessions, start/stop |
| `/ledger/` | Filtered ledger history |
| `/pricing/` | Tariff and group management |

Cloud (read-only replica):

| Route | Purpose |
|---|---|
| `/customers/` | Replicated customer list |
| `/customers/<id>/` | Replicated profile, wallet history and sessions |
| `/sessions/` | Replicated sessions with status filters |
| `/ledger/` | Replicated ledger with type filters and filtered total |
| `/pricing/` | Replicated tariffs and groups |

## Test evidence

Executed on the Linux dev host with PostgreSQL 18 and Redis running:

```
cd backend
LD_LIBRARY_PATH=../.artifacts/pg/lib64:../.artifacts/pg/lib .venv/bin/pytest
# 109 passed in 9.03s, exit code 0
```

Phase 1 focused tests:

| File | Tests | Coverage |
|---|---|---|
| `tests/test_customers.py` | 6 | Creation/wallet/events, duplicate phone, credit-limit floor, deactivation guard, role guard |
| `tests/test_wallets.py` | 8 | Deposits, limits, reversal idempotency, append-only guard, role guard, concurrent deposits |
| `tests/test_sessions.py` | 9 | Tariff snapshot, reprice isolation, exact-once charge, zero cost, credit reservation, offline device, reconnect reconciliation, concurrent starts |
| `tests/test_phase1_roundtrip.py` | 4 | Full edge→cloud replication, ledger dedupe/balance, read-only replica, ordering |
| `tests/test_phase1_ui.py` | 2 | Edge pages/actions and cloud read-only pages |

Other checks run in the same session:

```
./dev/manage.sh edge check    # no issues
./dev/manage.sh cloud check   # no issues
cd client && npm run typecheck && npm run build   # passed
./dev/manage.sh edge migrate  # Phase 1 migrations applied
./dev/manage.sh cloud migrate # Phase 1 migrations applied
```

No Phase 1 claim depends on the Windows 7 SP1 or Windows 10 hardware that is
still unavailable.
