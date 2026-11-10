-- Demo company data, in the same Postgres as the 10xGraph API (schema "demo").
-- Runs at every startup: everything is IF NOT EXISTS / ON CONFLICT DO NOTHING.

CREATE SCHEMA IF NOT EXISTS demo;

CREATE TABLE IF NOT EXISTS demo.orders (
    org_id   text NOT NULL,
    order_id text NOT NULL,
    item     text NOT NULL,
    total    numeric(12, 2) NOT NULL,
    status   text NOT NULL,
    PRIMARY KEY (org_id, order_id)
);

CREATE TABLE IF NOT EXISTS demo.refunds (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    org_id       text NOT NULL,
    order_id     text NOT NULL,
    amount       numeric(12, 2) NOT NULL CHECK (amount > 0),
    reason       text NOT NULL,
    status       text NOT NULL CHECK (status IN ('issued', 'pending', 'rejected')),
    requested_by text NOT NULL,
    decided_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    decided_at   timestamptz,
    UNIQUE (org_id, order_id)  -- one refund per order
);

CREATE TABLE IF NOT EXISTS demo.tickets (
    id          bigint GENERATED ALWAYS AS IDENTITY (START WITH 1001) PRIMARY KEY,
    org_id      text NOT NULL,
    user_id     text NOT NULL,
    summary     text NOT NULL,
    needs_human boolean NOT NULL DEFAULT false,
    status      text NOT NULL DEFAULT 'open',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Dummy data: two organisations and their orders.
INSERT INTO demo.orders (org_id, order_id, item, total, status) VALUES
    ('acme',   'A-1001', 'Wireless headset',    45.00,  'delivered'),
    ('acme',   'A-1002', '27-inch monitor',     250.00, 'delivered'),
    ('acme',   'A-1003', 'USB-C dock',          89.50,  'shipped'),
    ('globex', 'G-2001', 'Mechanical keyboard', 80.00,  'delivered'),
    ('globex', 'G-2002', 'Standing desk',       500.00, 'delivered')
ON CONFLICT DO NOTHING;
