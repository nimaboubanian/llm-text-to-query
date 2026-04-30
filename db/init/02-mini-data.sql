-- Mini Database Sample Data for Text-to-Query Testing
-- Synthetic data: ~30 customers, ~20 products, ~100 orders

-- Customers (30 rows)
INSERT INTO customers (name, email, city, created_at) VALUES
('Alice Johnson', 'alice.johnson@email.com', 'New York', '2024-01-15'),
('Bob Smith', 'bob.smith@email.com', 'London', '2024-02-20'),
('Carol Williams', 'carol.williams@email.com', 'Tokyo', '2024-01-08'),
('David Brown', 'david.brown@email.com', 'Berlin', '2024-03-12'),
('Emma Davis', 'emma.davis@email.com', 'Sydney', '2024-02-28'),
('Frank Miller', 'frank.miller@email.com', 'New York', '2024-04-05'),
('Grace Wilson', 'grace.wilson@email.com', 'London', '2024-03-18'),
('Henry Moore', 'henry.moore@email.com', 'Tokyo', '2024-05-22'),
('Ivy Taylor', 'ivy.taylor@email.com', 'Berlin', '2024-04-30'),
('Jack Anderson', 'jack.anderson@email.com', 'Sydney', '2024-06-14'),
('Karen Thomas', 'karen.thomas@email.com', 'New York', '2024-05-09'),
('Leo Jackson', 'leo.jackson@email.com', 'London', '2024-07-21'),
('Mia White', 'mia.white@email.com', 'Tokyo', '2024-06-03'),
('Noah Harris', 'noah.harris@email.com', 'Berlin', '2024-08-17'),
('Olivia Martin', 'olivia.martin@email.com', 'Sydney', '2024-07-25'),
('Paul Garcia', 'paul.garcia@email.com', 'New York', '2024-09-02'),
('Quinn Martinez', 'quinn.martinez@email.com', 'London', '2024-08-11'),
('Rachel Robinson', 'rachel.robinson@email.com', 'Tokyo', '2024-10-06'),
('Sam Clark', 'sam.clark@email.com', 'Berlin', '2024-09-19'),
('Tina Rodriguez', 'tina.rodriguez@email.com', 'Sydney', '2024-11-08'),
('Uma Lewis', 'uma.lewis@email.com', 'New York', '2024-10-23'),
('Victor Lee', 'victor.lee@email.com', 'London', '2024-12-01'),
('Wendy Walker', 'wendy.walker@email.com', 'Tokyo', '2024-11-15'),
('Xavier Hall', 'xavier.hall@email.com', 'Berlin', '2024-12-20'),
('Yara Allen', 'yara.allen@email.com', 'Sydney', '2025-01-05'),
('Zach Young', 'zach.young@email.com', 'New York', '2025-01-18'),
('Amy King', 'amy.king@email.com', 'London', '2025-02-10'),
('Brian Wright', 'brian.wright@email.com', 'Tokyo', '2025-02-22'),
('Chloe Scott', 'chloe.scott@email.com', 'Berlin', '2025-03-08'),
('Derek Green', 'derek.green@email.com', 'Sydney', '2025-03-15');

-- Products (20 rows)
INSERT INTO products (name, category, price, cost, stock) VALUES
('Laptop Pro 15', 'Electronics', 1299.99, 850.00, 45),
('Wireless Mouse', 'Electronics', 29.99, 12.00, 200),
('USB-C Hub', 'Electronics', 49.99, 22.00, 150),
('Mechanical Keyboard', 'Electronics', 129.99, 65.00, 80),
('Monitor 27 inch', 'Electronics', 349.99, 200.00, 35),
('Running Shoes', 'Sports', 89.99, 40.00, 120),
('Yoga Mat', 'Sports', 24.99, 8.00, 300),
('Tennis Racket', 'Sports', 159.99, 75.00, 40),
('Basketball', 'Sports', 29.99, 10.00, 180),
('Winter Jacket', 'Clothing', 199.99, 90.00, 60),
('Cotton T-Shirt', 'Clothing', 19.99, 6.00, 500),
('Denim Jeans', 'Clothing', 59.99, 25.00, 200),
('Wool Sweater', 'Clothing', 79.99, 35.00, 100),
('Programming Book', 'Books', 44.99, 15.00, 75),
('Novel Bestseller', 'Books', 14.99, 5.00, 250),
('Cookbook Deluxe', 'Books', 34.99, 12.00, 90),
('Coffee Maker', 'Home', 79.99, 35.00, 55),
('Blender Pro', 'Home', 69.99, 30.00, 70),
('Desk Lamp LED', 'Home', 39.99, 15.00, 140),
('Air Purifier', 'Home', 149.99, 70.00, 30);

-- Orders (100 rows)
-- Distribution: skewed (customer 1 has 8 orders, customers 24-30 have 1 each)
-- Product 20 (Air Purifier) is never ordered
INSERT INTO orders (customer_id, product_id, quantity, order_date, total_amount) VALUES
-- Customer 1: 8 orders
(1, 1, 1, '2024-02-10', 1299.99),
(1, 2, 2, '2024-02-10', 59.98),
(1, 17, 1, '2024-04-22', 79.99),
(1, 11, 2, '2024-06-15', 39.98),
(1, 7, 1, '2024-08-05', 24.99),
(1, 5, 1, '2024-10-18', 349.99),
(1, 14, 1, '2025-01-20', 44.99),
(1, 19, 2, '2025-03-01', 79.98),
-- Customer 2: 7 orders
(2, 4, 1, '2024-03-05', 129.99),
(2, 19, 2, '2024-05-18', 79.98),
(2, 13, 1, '2024-07-08', 79.99),
(2, 6, 1, '2024-09-12', 89.99),
(2, 3, 1, '2024-11-25', 49.99),
(2, 18, 1, '2025-01-15', 69.99),
(2, 10, 1, '2025-03-10', 199.99),
-- Customer 3: 6 orders
(3, 6, 1, '2024-02-15', 89.99),
(3, 7, 2, '2024-02-15', 49.98),
(3, 15, 4, '2024-06-28', 59.96),
(3, 12, 1, '2024-08-10', 59.99),
(3, 9, 3, '2025-02-20', 89.97),
(3, 16, 1, '2025-03-15', 34.99),
-- Customer 4: 6 orders
(4, 10, 1, '2024-04-01', 199.99),
(4, 2, 3, '2024-06-05', 89.97),
(4, 17, 1, '2024-08-12', 79.99),
(4, 8, 1, '2024-10-20', 159.99),
(4, 14, 2, '2025-01-08', 89.98),
(4, 5, 1, '2025-02-25', 349.99),
-- Customer 5: 5 orders
(5, 11, 3, '2024-03-20', 59.97),
(5, 12, 2, '2024-03-20', 119.98),
(5, 4, 1, '2024-05-28', 129.99),
(5, 19, 1, '2024-07-25', 39.99),
(5, 1, 1, '2024-12-10', 1299.99),
-- Customer 6: 5 orders
(6, 14, 1, '2024-05-12', 44.99),
(6, 6, 1, '2024-07-14', 89.99),
(6, 3, 2, '2024-09-01', 99.98),
(6, 17, 1, '2024-11-18', 79.99),
(6, 9, 2, '2025-01-05', 59.98),
-- Customer 7: 5 orders
(7, 15, 2, '2024-04-25', 29.98),
(7, 8, 1, '2024-06-30', 159.99),
(7, 1, 1, '2024-08-30', 1299.99),
(7, 11, 3, '2024-11-05', 59.97),
(7, 18, 1, '2025-01-28', 69.99),
-- Customer 8: 4 orders
(8, 17, 1, '2024-06-08', 79.99),
(8, 10, 1, '2024-08-22', 199.99),
(8, 3, 1, '2024-10-08', 49.99),
(8, 12, 1, '2024-12-15', 59.99),
-- Customer 9: 4 orders
(9, 1, 1, '2024-05-30', 1299.99),
(9, 5, 1, '2024-09-15', 349.99),
(9, 13, 1, '2024-12-01', 79.99),
(9, 7, 2, '2025-02-10', 49.98),
-- Customer 10: 4 orders
(10, 3, 2, '2024-07-15', 99.98),
(10, 4, 1, '2024-07-15', 129.99),
(10, 14, 2, '2024-09-05', 89.98),
(10, 6, 1, '2025-01-12', 89.99),
-- Customer 11: 4 orders
(11, 5, 1, '2024-06-22', 349.99),
(11, 15, 1, '2024-08-12', 14.99),
(11, 9, 1, '2024-10-20', 29.99),
(11, 19, 1, '2025-01-05', 39.99),
-- Customer 12: 3 orders
(12, 8, 1, '2024-08-03', 159.99),
(12, 16, 1, '2024-10-01', 34.99),
(12, 2, 1, '2024-12-20', 29.99),
-- Customer 13: 3 orders
(13, 9, 3, '2024-07-28', 89.97),
(13, 18, 1, '2024-09-25', 69.99),
(13, 13, 1, '2024-11-18', 79.99),
-- Customer 14: 3 orders
(14, 11, 5, '2024-09-10', 99.95),
(14, 1, 1, '2024-11-15', 1299.99),
(14, 15, 2, '2024-12-22', 29.98),
-- Customer 15: 3 orders
(15, 13, 2, '2024-08-18', 159.98),
(15, 3, 1, '2024-10-28', 49.99),
(15, 17, 1, '2024-12-10', 79.99),
-- Customer 16: 3 orders
(16, 14, 1, '2024-10-05', 44.99),
(16, 5, 1, '2024-12-08', 349.99),
(16, 18, 1, '2025-01-25', 69.99),
-- Customer 17: 2 orders
(17, 16, 1, '2024-09-22', 34.99),
(17, 7, 3, '2024-11-22', 74.97),
-- Customer 18: 2 orders
(18, 18, 1, '2024-11-01', 69.99),
(18, 2, 1, '2025-02-08', 29.99),
-- Customer 19: 2 orders
(19, 11, 2, '2024-12-05', 39.98),
(19, 4, 1, '2025-02-15', 129.99),
-- Customer 20: 2 orders
(20, 13, 1, '2025-01-10', 79.99),
(20, 6, 2, '2025-03-05', 179.98),
-- Customer 21: 2 orders
(21, 6, 2, '2024-11-08', 179.98),
(21, 17, 1, '2024-12-28', 79.99),
-- Customer 22: 2 orders
(22, 19, 1, '2025-01-22', 39.99),
(22, 5, 1, '2025-02-28', 349.99),
-- Customer 23: 2 orders
(23, 2, 2, '2025-01-08', 59.98),
(23, 7, 1, '2025-02-12', 24.99),
-- Customer 24: 1 order
(24, 12, 2, '2025-01-05', 119.98),
-- Customer 25: 1 order
(25, 1, 1, '2025-01-15', 1299.99),
-- Customer 26: 1 order
(26, 4, 1, '2025-02-01', 129.99),
-- Customer 27: 1 order
(27, 5, 1, '2025-02-10', 349.99),
-- Customer 28: 1 order
(28, 8, 1, '2025-02-20', 159.99),
-- Customer 29: 1 order
(29, 14, 1, '2025-03-20', 44.99),
-- Customer 30: 1 order
(30, 16, 2, '2025-03-25', 69.98);
