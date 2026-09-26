-- Fake "production" shop database. Run once in the Neon SQL Editor on the main branch.

CREATE TABLE customers (
  id serial PRIMARY KEY,
  name text NOT NULL,
  email text,                 -- 40 rows are NULL on purpose (trap for migration 3)
  city text,
  created_at timestamptz DEFAULT now()
);

INSERT INTO customers (name, email, city)
SELECT 'Customer ' || g,
       CASE WHEN g % 50 = 0 THEN NULL ELSE 'user' || g || '@example.com' END,
       (ARRAY['Bengaluru','Mumbai','Delhi','Pune','Hyderabad'])[1 + g % 5]
FROM generate_series(1, 2000) g;

CREATE TABLE orders (
  id serial PRIMARY KEY,
  customer_id int REFERENCES customers(id),
  amount numeric(10,2) NOT NULL,   -- paise matter (trap for migration 2)
  status text NOT NULL,
  created_at timestamptz DEFAULT now()
);

INSERT INTO orders (customer_id, amount, status)
SELECT 1 + (g % 2000),
       round((random() * 5000 + 99)::numeric, 2),
       (ARRAY['paid','shipped','refunded'])[1 + g % 3]
FROM generate_series(1, 20000) g;
