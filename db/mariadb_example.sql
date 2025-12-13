-- MariaDB Example: Library Management Database
-- Create 'authors' table
CREATE TABLE IF NOT EXISTS authors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    nationality VARCHAR(50),
    birth_year INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create 'genres' table
CREATE TABLE IF NOT EXISTS genres (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT
);

-- Create 'books' table
CREATE TABLE IF NOT EXISTS books (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    author_id INT NOT NULL,
    genre_id INT,
    isbn VARCHAR(20) UNIQUE,
    published_year INT,
    pages INT,
    available_copies INT DEFAULT 1,
    FOREIGN KEY (author_id) REFERENCES authors(id),
    FOREIGN KEY (genre_id) REFERENCES genres(id)
);

-- Create 'members' table
CREATE TABLE IF NOT EXISTS members (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    membership_date DATE DEFAULT (CURRENT_DATE),
    membership_type ENUM('basic', 'premium', 'student') DEFAULT 'basic'
);

-- Create 'loans' table
CREATE TABLE IF NOT EXISTS loans (
    id INT AUTO_INCREMENT PRIMARY KEY,
    book_id INT NOT NULL,
    member_id INT NOT NULL,
    loan_date DATE DEFAULT (CURRENT_DATE),
    due_date DATE NOT NULL,
    return_date DATE,
    status ENUM('active', 'returned', 'overdue') DEFAULT 'active',
    FOREIGN KEY (book_id) REFERENCES books(id),
    FOREIGN KEY (member_id) REFERENCES members(id)
);

-- Insert sample authors
INSERT INTO authors (name, nationality, birth_year) VALUES
('George Orwell', 'British', 1903),
('Jane Austen', 'British', 1775),
('Gabriel García Márquez', 'Colombian', 1927),
('Haruki Murakami', 'Japanese', 1949),
('Chimamanda Ngozi Adichie', 'Nigerian', 1977);

-- Insert sample genres
INSERT INTO genres (name, description) VALUES
('Fiction', 'Literary works of imagination'),
('Science Fiction', 'Fiction based on scientific discoveries'),
('Romance', 'Stories centered on romantic relationships'),
('Mystery', 'Fiction dealing with puzzling crimes'),
('Non-Fiction', 'Factual prose writing');

-- Insert sample books
INSERT INTO books (title, author_id, genre_id, isbn, published_year, pages, available_copies) VALUES
('1984', 1, 2, '978-0451524935', 1949, 328, 3),
('Animal Farm', 1, 1, '978-0451526342', 1945, 112, 2),
('Pride and Prejudice', 2, 3, '978-0141439518', 1813, 432, 4),
('One Hundred Years of Solitude', 3, 1, '978-0060883287', 1967, 417, 2),
('Norwegian Wood', 4, 1, '978-0375704024', 1987, 296, 3),
('Kafka on the Shore', 4, 1, '978-1400079278', 2002, 467, 1),
('Purple Hibiscus', 5, 1, '978-1616202415', 2003, 307, 2),
('Americanah', 5, 1, '978-0307455925', 2013, 477, 3);

-- Insert sample members
INSERT INTO members (name, email, phone, membership_type) VALUES
('Alice Cooper', 'alice@library.com', '555-0101', 'premium'),
('Bob Wilson', 'bob@library.com', '555-0102', 'basic'),
('Carol Davis', 'carol@library.com', '555-0103', 'student'),
('David Brown', 'david@library.com', '555-0104', 'premium'),
('Eve Martinez', 'eve@library.com', '555-0105', 'basic');

-- Insert sample loans
INSERT INTO loans (book_id, member_id, loan_date, due_date, return_date, status) VALUES
(1, 1, '2024-01-10', '2024-01-24', '2024-01-22', 'returned'),
(3, 2, '2024-01-15', '2024-01-29', NULL, 'active'),
(5, 3, '2024-01-18', '2024-02-01', '2024-01-30', 'returned'),
(2, 4, '2024-01-20', '2024-02-03', NULL, 'active'),
(7, 5, '2024-01-22', '2024-02-05', NULL, 'active'),
(4, 1, '2024-01-25', '2024-02-08', NULL, 'active'),
(6, 3, '2024-01-28', '2024-02-11', NULL, 'active');
