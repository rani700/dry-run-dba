# Dry-Run DBA: build guide

**One-line pitch:** "An agent that rehearses every database migration on a throwaway copy of production, measures exactly what it will do to your data, and won't touch prod until a human approves."

How it covers the three judging criteria:

| Criterion | Where it shows up |
|---|---|
| A real tool reached | **Neon MCP**: a real Postgres. The agent creates a real branch and applies the real migration. |
| Code run in a sandbox | **Daytona sandbox**: `compare.py` diffs prod against the rehearsal and lints the SQL. |
| A pause before anything irreversible | **Tool approval** on `complete_database_migration`: Allow/Deny before prod changes. |

```
 user pastes SQL
      │
      ▼
 fingerprint prod (run_sql, read-only) ──► before.json ─┐
      │                                                 │
 prepare_database_migration ──► temp Neon branch        │   SANDBOX
      │                                                 ├─► compare.py ─► VERDICT
 fingerprint branch (run_sql) ──► after.json ───────────┘
      │
 Risk card (Generative UI)
      │
  BLOCK → stop, suggest a fix        SAFE/REVIEW → complete_database_migration
                                                   ⏸  HUMAN APPROVAL  ⏸
                                                   → prod updated → verify
```

---

## Step 0: Accounts and keys (15 min, do these first)

1. **LLM key.** Anthropic (Claude Sonnet) or OpenAI, whichever you have credit for.
2. **Neon** (free): sign up at neon.tech → create project `shopdb` (region: Singapore/AWS ap-southeast-1).
   Then **Account settings → API keys → Create** and copy it (`napi_...`).
3. **Daytona** (free credits): sign up at app.daytona.io → **Keys → Create key**.
   ⚠️ Give it **Sandboxes** access *and* **Snapshots write/create** permission, or TrueForge will reject it.
4. **GitHub** account, for the skill repo.
5. Node.js **22.14+** (`node -v`).

## Step 1: Run TrueForge (5 min)

```bash
npx @truefoundry/trueforge@latest
```
Open http://localhost:8790.

## Step 2: Settings (15 min)

1. **Settings → Models** → pick your provider → **Configure** → paste key → **Create**.
2. **Settings → Sandbox providers** → **Daytona** → **Configure** → paste key → **Save**.
   The first save builds a snapshot, so give it a minute.
3. **Settings → Connectors → Add MCP Server**:
   - Name: `neon`
   - URL: `https://mcp.neon.tech/mcp`
   - Auth: **Header**, key `Authorization`, value `Bearer napi_YOUR_KEY`
   - (OAuth also works, but the header is simpler and has fewer moving parts.)

✅ **Checkpoint:** in Build Agent, open a quick chat with the neon tools attached and ask "list my Neon projects". You should see `shopdb`.

## Step 3: Seed the fake "production" DB (5 min)

Neon console → `shopdb` → sidebar **Postgres database › SQL Editor** (branch `production`, database `neondb`) → paste `demo/seed.sql` → **Run**.
You get 2,000 customers (40 with NULL email) and 20,000 orders with paise amounts. Those are the two traps.

## Step 4: Publish the skill on GitHub (15 min)

1. Create a **public** repo, e.g. `dry-run-dba`.
2. Push this folder (it already contains `migration-rehearsal/SKILL.md` and `migration-rehearsal/scripts/compare.py`):
   ```bash
   cd ~/Developer/dry-run-dba
   git init && git add . && git commit -m "Dry-Run DBA skill"
   git branch -M main
   git remote add origin https://github.com/<you>/dry-run-dba.git
   git push -u origin main
   ```
3. TrueForge → **Settings → Skills → Import from GitHub**: repo URL, path `migration-rehearsal`, ref `main`.

Read both files before the Q&A, since you need to be able to explain every line:
- `SKILL.md` is the procedure plus the **fingerprint query**: for every column it gets the row count, NULL count and SUM. Any migration that silently changes data moves at least one of these numbers.
- `compare.py` has **static lint** (DROP, ALTER TYPE, SET NOT NULL, index without CONCURRENTLY, and so on) plus a **data drift diff** between the two fingerprints. It ends with `VERDICT: SAFE|REVIEW|BLOCK`: any HIGH drift → BLOCK; any HIGH/MEDIUM lint or MEDIUM drift → REVIEW; else SAFE.

Try it locally first:
```bash
python3 migration-rehearsal/scripts/compare.py   # prints usage
```

## Step 5: Build the agent (20 min)

**Build Agent** page:

- **Model:** your Claude/GPT model, reasoning effort medium.
- **Instructions** (paste):

```text
You are Dry-Run DBA, a migration safety agent for Postgres on Neon.
The Neon project's default branch (named "production") is PRODUCTION. Nothing may change it until the migration has been
rehearsed on a temporary branch and a human has approved it.

For every migration the user gives you, load and follow the migration-rehearsal skill exactly.

Hard rules:
- On the production branch, use run_sql for SELECT queries only. Never run INSERT, UPDATE, DELETE,
  ALTER, DROP or TRUNCATE on production yourself; production changes go only through
  complete_database_migration.
- Never call complete_database_migration when the verdict is BLOCK.
- Never delete projects, or any branch other than the temporary migration branch.
- Base every number you report on tool or script output, never on estimates.
- Keep the user informed with short progress lines: "Fingerprinting prod…", "Rehearsing on a
  temporary branch…", "Analyzing in sandbox…".
- End with a risk card (Generative UI): verdict badge, changes, findings, rollback SQL.
```

- **MCP Servers → Select MCP Tools → `neon`**. Enable only what you need:
  `list_projects`, `describe_project`, `list_branches`, `run_sql`, `describe_table_schema`,
  `get_database_tables`, `prepare_database_migration`, `complete_database_migration`,
  `compare_database_schema`, `delete_branch`.
- **Approval shields ON** (click the shield on each):
  `complete_database_migration`, `delete_branch`.
  (Don't rely on the default "@destructive" setting. It only applies to tools the server annotates, so set the shields explicitly.)
- **Skills:** `migration-rehearsal`.
- **Runtime Config:** Sandbox **ON**, Generative UI **ON**, Ask user questions **ON**. Dynamic sub-agents can stay on.
- **Save Agent** → name `dry-run-dba`, description "Rehearses DB migrations before prod".

## Step 6: Test the three scenarios (60–90 min, where most of the work is)

Open the agent → **Try**. Paste each migration from `demo/migrations.md`:

| # | Migration | Expected result |
|---|---|---|
| 1 | `ADD COLUMN discount_code text` | SAFE → approval pause → **Allow** → applied → verified |
| 2 | `ALTER COLUMN amount TYPE integer` | Succeeds on the branch, **but** SUM(amount) drifts → **BLOCK**, and it suggests a safer migration |
| 3 | `ALTER COLUMN email SET NOT NULL` | Fails on the branch (40 NULLs), prod untouched, and it suggests a backfill first |

Things to fix while testing:
- If the agent **skips the sandbox** and reasons in its head, strengthen the instructions: "You MUST run compare.py".
- If it **runs ALTER on production via run_sql**, turn on the shield for `run_sql` too. You'll get more pauses, but it's safer, and you can tell judges why.
- If `prepare_database_migration` asks it to "confirm with the user", that's fine. Neon's own tool expects that flow.
- Check the **Sessions** page to see every tool call and sandbox run. This is your audit log, so show it in the demo.
- After each test, check the Neon console: the branch appears and disappears, and production only changes after Allow.

## Step 7: Polish, only if the core works (60 min)

Pick in this order and stop when time runs out:
1. **Better risk card:** ask for a red/amber/green verdict badge, a table of findings, and "₹ revenue drift" in big numbers.
2. **Rollback rehearsal:** have the agent also run the rollback SQL on the temp branch and fingerprint again. If it doesn't match `before.json`, mark the migration **irreversible**.
3. **Migration from a GitHub PR:** add the GitHub connector from the catalog. "Rehearse the migration in PR #3."
4. **Code Mode:** let the sandbox script call `run_sql` itself via `from mcp_client import call_tool` (see trueforge.dev/key-features/code-mode). Approvals still apply inside scripts.

## Step 8: Demo (3 min) and backup

Record a **backup screen recording** of the full demo as soon as scenario 1 and 2 work.

**Script:**
1. (20s) Problem: "Migrations are the scariest button in engineering. Here's one that *doesn't error*, but quietly corrupts your revenue."
2. (60s) Paste migration 2. Show the progress lines, the branch appearing in Neon, the sandbox run, and **BLOCK: revenue drifted by ₹X**. Point out that Postgres raised no error, so a normal CI pipeline would have shipped it.
3. (60s) Paste migration 1. SAFE → the **approval pause** → Allow → prod updated → verified.
4. (20s) Show the Sessions audit trail.
5. (20s) "Real tool: Neon. Code in sandbox: Daytona. Pause before irreversible: TrueForge approvals."

## Step 9: Build story post (for the ₹75k community prize)

Post mid-day and again at the end, tagging **@truefoundry @polariscodes**:

> Building "Dry-Run DBA" at #BuildAgentsThatAct: an agent that rehearses every DB migration on a throwaway Neon branch, fingerprints the data before/after in a Daytona sandbox, and refuses to touch prod without human approval.
> First catch: `ALTER COLUMN amount TYPE integer`. Postgres runs it with no error, but it silently rounds every order and ₹X of revenue vanished. The agent blocked it. 🧵

Add a screenshot of the BLOCK card.

---

## Q&A prep: likely judge questions

**Why is this agentic and not just a script?**
The procedure is fixed, but the judgement isn't. The agent reads the error or drift, explains it in business terms, writes a safer migration and a rollback, and re-rehearses. The script makes the numbers exact; the agent makes the decision and explains it.

**What does the sandbox actually do?**
It runs the analysis code (`compare.py`) in isolated Daytona compute. The credentials stay in the TrueForge harness ("sandbox as tool"), so the sandbox never holds the Neon key.

**What if the agent tries to ALTER prod directly with run_sql?**
Instructions forbid it, and the approval shield can be put on `run_sql` too. A v2 would use two connectors: a read-only Neon connector for production (`?readonly=true`) and a write connector limited to the migration tools.

**Why fingerprints (counts, NULLs, sums)?**
They're cheap, work on any schema, and catch the dangerous class of silent data changes: truncation, precision loss, rows lost to cascades, NULLs introduced.

**Limitations?**
Rehearsing on a branch doesn't measure lock time under production load, and sums won't catch changes to text columns. Next steps: per-column checksums, `EXPLAIN` on hot queries, and lock-time estimates from table size.

**Why Neon?**
Copy-on-write branching gives a full copy of production data in seconds for free. That's what makes rehearsing every migration practical.

## Timeline (7 hours)

| Time | Goal |
|---|---|
| 0:00–0:45 | Steps 0–3: accounts, TrueForge running, Neon connected, DB seeded |
| 0:45–1:30 | Steps 4–5: skill pushed, agent saved |
| 1:30–3:30 | Step 6: all three scenarios working reliably (post the first build story here) |
| 3:30–5:00 | Step 7 polish (risk card, then rollback rehearsal) |
| 5:00–6:00 | Record the backup video, rehearse the demo 3×, prepare Q&A answers |
| 6:00–7:00 | Buffer, final post, submit |
