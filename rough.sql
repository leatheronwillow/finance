CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    username TEXT NOT NULL,
    hash TEXT NOT NULL,
    cash NUMERIC NOT NULL DEFAULT 10000.00
    );

CREATE TABLE transactions(
               transaction_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
               user_id INTEGER NOT NULL,
               symbol TEXT NOT NULL,
               stock_name TEXT NOT NULL,
               quantity INTEGER NOT NULL,
               price NUMERIC NOT NULL,
               total_cost NUMERIC NOT NULL,
               timestamp DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
               purchased_or_sold TEXT NOT NULL,
               FOREIGN KEY(user_id) REFERENCES users(id)
            );

CREATE UNIQUE INDEX username ON users (username);

CREATE TABLE portfolio (
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    shares_owned INTEGER NOT NULL,
    price NUMERIC NOT NULL,
    total_value NUMERIC NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX user ON portfolio (user_id);
CREATE INDEX stock ON portfolio (symbol);
CREATE INDEX customer  ON transactions (user_id);
CREATE INDEX symbol ON transactions (symbol);