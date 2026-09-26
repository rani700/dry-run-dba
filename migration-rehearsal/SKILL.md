---
name: migration-rehearsal
description: Rehearse a Postgres schema migration on a temporary Neon branch, measure exactly what it changes in the data, and produce a SAFE / REVIEW / BLOCK risk report before anything touches the production branch. Use for any request to run, apply, test or review a database migration.
---

# Migration rehearsal

Production is the project's **default branch** (named `production` in the demo project; in other projects it may be `main`). It must never change until the migration has
been rehearsed on a temporary branch and a human has approved it.

## Procedure

Work in one folder: run `mkdir -p /tmp/rehearsal` first and use the absolute paths
`/tmp/rehearsal/before.json`, `/tmp/rehearsal/after.json` and `/tmp/rehearsal/migration.sql`.
Call `run_sql` as a normal tool call, not from a script.

1. **Find the target.** Use `list_projects` to get the Neon project id and the database
   name (usually `neondb`). If there is more than one candidate, ask the user.

2. **Fingerprint production.** Run the fingerprint query below with `run_sql` on the
   default (production) branch. Write the `run_sql` result to `/tmp/rehearsal/before.json` exactly as returned.
   Do not reshape it; `compare.py` understands Neon's format.

3. **Rehearse.** Call `prepare_database_migration` with the migration SQL. Neon applies
   it to a temporary branch only and returns that branch's id and a migration id.
   - If it fails, stop and report the error. Say clearly that production was not
     touched, explain the cause (for example, NULLs blocking SET NOT NULL, with the
     count), and propose a fixed migration. If a temporary branch was created anyway,
     delete it with `delete_branch`.

4. **Fingerprint the rehearsal.** Run the same fingerprint query with `run_sql` on the
   temporary branch. Write the result to `/tmp/rehearsal/after.json` exactly as returned.

5. **Analyze in code.** Write the migration SQL to `/tmp/rehearsal/migration.sql`, then run:

   ```bash
   python3 /opt/tf/skills/migration-rehearsal/scripts/compare.py /tmp/rehearsal/before.json /tmp/rehearsal/after.json /tmp/rehearsal/migration.sql
   ```

   Use the script's findings and its final `VERDICT:` line. Do not compute diffs yourself.

6. **Report with a risk card.** Show:
   - Verdict: SAFE / REVIEW / BLOCK
   - What changes (tables, columns, types)
   - Rows affected, and whether the change can be undone
   - Every HIGH / MEDIUM finding from the script, in plain words
   - A rollback SQL that you wrote. If data would be lost (dropped column, precision
     lost), say "rollback cannot restore the data" and treat the migration as irreversible.

7. **Decide.**
   - **BLOCK**: do not apply the migration. Explain the problem with the real numbers,
     propose a safer migration, and offer to rehearse it. Then clean up: call `delete_branch`
     on the temporary branch from step 3 (never on any other branch). This pauses for approval.
   - **SAFE / REVIEW**: first show the full risk card to the user, then call
     `complete_database_migration` with the migration id. The harness pauses for human
     approval here, and the approver must be able to see the risk card when deciding.

8. **Verify.** After the migration is applied, fingerprint the production branch again, compare it with
   `after.json`, and confirm that production now matches the rehearsal.

## Fingerprint query

Row counts, NULL counts and numeric sums for every column in the `public` schema.
A migration that silently changes data will change at least one of these.

```sql
SELECT json_agg(x) AS fingerprint FROM (
  SELECT c.table_name, c.column_name, c.data_type,
    (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', c.table_schema, c.table_name), false, true, '')))[1]::text::bigint AS row_count,
    (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I WHERE %I IS NULL', c.table_schema, c.table_name, c.column_name), false, true, '')))[1]::text::bigint AS null_count,
    CASE WHEN c.data_type IN ('smallint','integer','bigint','numeric','real','double precision')
      THEN (xpath('/row/s/text()', query_to_xml(format('SELECT sum(%I)::numeric AS s FROM %I.%I', c.column_name, c.table_schema, c.table_name), false, true, '')))[1]::text
    END AS col_sum
  FROM information_schema.columns c
  JOIN information_schema.tables t
    ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
  WHERE c.table_schema = 'public'
  ORDER BY c.table_name, c.ordinal_position
) x;
```
