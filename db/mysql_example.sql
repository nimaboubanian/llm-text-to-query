-- MySQL Example: E-commerce Database
-- Create 'users' table
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create 'categories' table
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_id INT NULL,
    FOREIGN KEY (parent_id) REFERENCES categories(id)
);

-- Create 'items' table
CREATE TABLE IF NOT EXISTS items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    category_id INT,
    seller_id INT,
    stock_quantity INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (seller_id) REFERENCES users(id)
);

-- Create 'purchases' table
CREATE TABLE IF NOT EXISTS purchases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    buyer_id INT NOT NULL,
    item_id INT NOT NULL,
    quantity INT NOT NULL,
    total_price DECIMAL(10, 2) NOT NULL,
    purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('pending', 'shipped', 'delivered', 'cancelled') DEFAULT 'pending',
    FOREIGN KEY (buyer_id) REFERENCES users(id),
    FOREIGN KEY (item_id) REFERENCES items(id)
);

-- Create 'reviews' table
CREATE TABLE IF NOT EXISTS reviews (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_id INT NOT NULL,
    user_id INT NOT NULL,
    rating TINYINT NOT NULL CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (item_id) REFERENCES items(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Insert sample data
INSERT INTO users (username, email, password_hash) VALUES
('johndoe', 'john.doe@email.com', 'hash123'),
('janedoe', 'jane.doe@email.com', 'hash456'),
('seller_mike', 'mike@shop.com', 'hash789'),
('seller_sarah', 'sarah@shop.com', 'hash101'),
('buyer_tom', 'tom@email.com', 'hash202');

INSERT INTO categories (name, parent_id) VALUES
('Electronics', NULL),
('Clothing', NULL),
('Books', NULL),
('Smartphones', 1),
('Laptops', 1),
('Men''s Wear', 2),
('Women''s Wear', 2),
('Fiction', 3),
('Non-Fiction', 3);

INSERT INTO items (title, description, price, category_id, seller_id, stock_quantity) VALUES
('iPhone 15 Pro', 'Latest Apple smartphone with A17 chip', 999.99, 4, 3, 50),
('Samsung Galaxy S24', 'Flagship Android phone', 899.99, 4, 3, 35),
('MacBook Pro 14"', 'M3 Pro chip, 18GB RAM', 1999.99, 5, 3, 20),
('Dell XPS 15', 'Intel i9, 32GB RAM, OLED display', 1799.99, 5, 4, 15),
('Cotton T-Shirt Blue', 'Comfortable 100% cotton', 29.99, 6, 4, 200),
('Summer Dress Floral', 'Light and breezy summer dress', 59.99, 7, 4, 75),
('The Great Gatsby', 'Classic American novel', 14.99, 8, 3, 100),
('Atomic Habits', 'Self-improvement bestseller', 18.99, 9, 3, 150);

INSERT INTO purchases (buyer_id, item_id, quantity, total_price, status) VALUES
(1, 1, 1, 999.99, 'delivered'),
(1, 7, 2, 29.98, 'delivered'),
(2, 3, 1, 1999.99, 'shipped'),
(2, 6, 1, 59.99, 'delivered'),
(5, 2, 1, 899.99, 'pending'),
(5, 5, 3, 89.97, 'shipped'),
(1, 8, 1, 18.99, 'delivered');

INSERT INTO reviews (item_id, user_id, rating, comment) VALUES
(1, 1, 5, 'Amazing phone, love the camera!'),
(1, 2, 4, 'Great device but expensive'),
(3, 2, 5, 'Best laptop I ever owned'),
(7, 1, 5, 'A timeless classic'),
(5, 5, 4, 'Good quality, fits well'),
(8, 1, 5, 'Changed my daily habits!');
