# Demo migrations (paste these into the chat one at a time)

## 1. Safe: expect SAFE, then the approval pause, then Allow
```sql
ALTER TABLE orders ADD COLUMN discount_code text;
```

## 2. Silent trap: expect BLOCK
Runs without any error, but rounds every amount to whole rupees, so total revenue drifts.
```sql
ALTER TABLE orders ALTER COLUMN amount TYPE integer;
```
The agent should suggest a safer version (keep `numeric(12,2)`, or store paise as `bigint` via `amount * 100`).

## 3. Loud trap: expect "failed on the branch, prod untouched"
40 customers have NULL emails.
```sql
ALTER TABLE customers ALTER COLUMN email SET NOT NULL;
```
The agent should propose a backfill first (for example `UPDATE customers SET email = ... WHERE email IS NULL`).
