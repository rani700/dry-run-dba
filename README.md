# Dry-Run DBA

**An agent that rehearses every database migration on a throwaway copy of production, measures exactly what it will do to your data, and won't touch prod until a human approves.**

Built on [TrueForge](https://trueforge.dev) for the *Build Agents That Act* hackathon (TrueFoundry × Polaris).

## The problem

Some migrations don't fail. They succeed and quietly change your data:

```sql
ALTER TABLE orders ALTER COLUMN amount TYPE integer;
```

Postgres runs this without an error. Every order amount gets rounded to whole rupees, and the revenue total silently changes. CI passes, and the damage is in production.

## How it works

```
 migration SQL
      │
      ▼
 1. fingerprint production (read-only run_sql) ──► before.json ─┐
 2. prepare_database_migration → temporary Neon branch          │   Daytona sandbox
 3. fingerprint the temporary branch ──────────────► after.json ├─► compare.py ─► SAFE / REVIEW / BLOCK
      │                                                          │
      ▼
 4. risk card: verdict, findings, rollback SQL
      │
      ├─ BLOCK        → nothing applied; suggest a safer migration; delete temp branch  ⏸ approval
      └─ SAFE/REVIEW  → complete_database_migration                                    ⏸ approval
                        → re-fingerprint production and confirm it matches the rehearsal
```

| Requirement | How it's met |
|---|---|
| **Reaches a real tool** | Neon MCP server: a real Postgres, real copy-on-write branches, the real migration |
| **Runs code in a sandbox** | `compare.py` runs in a Daytona sandbox; credentials stay in the TrueForge harness |
| **Pauses before anything irreversible** | TrueForge tool approval on `complete_database_migration` and `delete_branch` |

**Fingerprint:** for every column in `public`, the row count, the NULL count and the SUM of numeric columns. A migration that silently changes data moves at least one of these numbers.

**`compare.py`** combines two checks:
- **Static lint** of the SQL: DROP, ALTER TYPE, SET NOT NULL, index without CONCURRENTLY, DELETE/UPDATE without WHERE, NOT NULL column without DEFAULT, RENAME.
- **Data drift** between the two fingerprints: rows lost, columns removed, new NULLs, changed sums.

Verdict: any HIGH drift → **BLOCK**; any risky lint or MEDIUM drift → **REVIEW**; otherwise **SAFE**.

## Demo scenarios

| Migration | Result |
|---|---|
| `ALTER TABLE orders ADD COLUMN discount_code text;` | **SAFE** → approval → applied → verified |
| `ALTER TABLE orders ALTER COLUMN amount TYPE integer;` | **BLOCK**: SUM(amount) drifted (e.g. 52,055,347.59 → 52,055,399); rollback can't restore the lost paise |
| `ALTER TABLE customers ALTER COLUMN email SET NOT NULL;` | Fails on the branch (40 NULL emails); production untouched; suggests a backfill first |

## Repository

```
migration-rehearsal/          TrueForge skill (git-backed)
  SKILL.md                    procedure + fingerprint query
  scripts/compare.py          lint + drift analysis, stdlib only
demo/
  seed.sql                    fake shop database with two planted traps
  migrations.md               the three demo migrations
```

## Run it yourself

1. `npx @truefoundry/trueforge@latest` → open http://localhost:8790
2. Settings: add a model provider, the Daytona sandbox provider, and an MCP server `neon` → `https://mcp.neon.tech/mcp` with header `Authorization: Bearer <NEON_API_KEY>`.
3. Settings → Skills → Import from GitHub: this repo, folder `migration-rehearsal`, branch `main`.
4. Seed a Neon project with `demo/seed.sql`.
5. Build an agent with the neon tools (approval on `complete_database_migration` and `delete_branch`), the `migration-rehearsal` skill, and the sandbox on.

## Limitations and next steps

- A branch rehearsal doesn't measure lock time under production load. Next: estimate lock time from table size, and run `EXPLAIN` on hot queries.
- SUMs don't catch changes to text columns. Next: per-column checksums.
- Rehearse the rollback SQL on the branch too, and mark the migration irreversible if it doesn't restore the fingerprint.
- Take migrations directly from GitHub pull requests.
