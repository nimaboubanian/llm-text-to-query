-- Create 'customers' table
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    join_date DATE DEFAULT CURRENT_DATE
);

-- Create 'products' table
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price DECIMAL NOT NULL
);

-- Create 'orders' table
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    customer_id INT REFERENCES customers(id),
    order_date DATE DEFAULT CURRENT_DATE
);

-- Create 'order_items' (Orderline) table
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INT REFERENCES orders(id),
    product_id INT REFERENCES products(id),
    quantity INT NOT NULL
);

-- Insert sample data
INSERT INTO customers (name, email) VALUES
('Alice Johnson', 'alice.johnson@example.com'),
('Bob Smith', 'bob.smith@example.com'),
('Charlie Brown', 'charlie.brown@example.com'),
('Diana Prince', 'diana.prince@example.com'),
('Ethan Hunt', 'ethan.hunt@example.com');
INSERT INTO products (name, category, price) VALUES
('Laptop', 'Electronics', 999.99),
('Smartphone', 'Electronics', 699.99),
('Desk Chair', 'Furniture', 149.99),
('Notebook', 'Stationery', 2.99),
('Pen Set', 'Stationery', 5.99),
('Headphones', 'Electronics', 199.99),
('Coffee Maker', 'Appliances', 89.99),
('Backpack', 'Accessories', 49.99),
('Monitor', 'Electronics', 249.99),
('Mouse', 'Electronics', 29.99);
INSERT INTO orders (customer_id, order_date) VALUES
(1, '2024-01-15'),
(2, '2024-01-16'),
(3, '2024-01-17'),
(4, '2024-01-18'),
(5, '2024-01-19'),
(1, '2024-01-20'),
(2, '2024-01-21'),
(3, '2024-01-22'),
(4, '2024-01-23'),
(5, '2024-01-24');
INSERT INTO order_items (order_id, product_id, quantity) VALUES
(1, 1, 1),
(1, 4, 2),
(2, 2, 1),
(2, 5, 3),
(3, 3, 1),
(3, 6, 1),
(4, 7, 1),
(4, 8, 1),
(5, 9, 1),
(5, 10, 2),
(6, 1, 1),
(6, 2, 1),
(7, 3, 2),
(7, 4, 1),
(8, 5, 1),
(8, 6, 1),
(9, 7, 1),
(9, 8, 2),
(10, 9, 1),
(10, 10, 1);