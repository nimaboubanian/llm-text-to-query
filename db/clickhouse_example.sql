-- ClickHouse Example: Web Analytics Database

-- Create page_views table
CREATE TABLE IF NOT EXISTS page_views (
    event_date Date,
    event_time DateTime,
    user_id UInt64,
    session_id String,
    page_url String,
    referrer String,
    device_type String,
    country String,
    duration_seconds UInt32
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, user_id, event_time);

-- Create users table
CREATE TABLE IF NOT EXISTS users (
    user_id UInt64,
    username String,
    email String,
    signup_date Date,
    subscription_type String,
    country String
) ENGINE = MergeTree()
ORDER BY user_id;

-- Create events table
CREATE TABLE IF NOT EXISTS events (
    event_date Date,
    event_time DateTime,
    user_id UInt64,
    event_type String,
    event_properties String,
    revenue Decimal(10,2)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_date)
ORDER BY (event_date, event_type, user_id);

-- Insert sample users
INSERT INTO users VALUES
(1, 'alice_wonder', 'alice@example.com', '2024-01-15', 'premium', 'USA'),
(2, 'bob_builder', 'bob@example.com', '2024-01-20', 'free', 'UK'),
(3, 'carol_singer', 'carol@example.com', '2024-02-01', 'premium', 'Canada'),
(4, 'david_star', 'david@example.com', '2024-02-10', 'free', 'USA'),
(5, 'eve_night', 'eve@example.com', '2024-02-15', 'premium', 'Germany');

-- Insert sample page views
INSERT INTO page_views VALUES
('2024-03-01', '2024-03-01 10:00:00', 1, 'sess_001', '/home', 'google.com', 'desktop', 'USA', 45),
('2024-03-01', '2024-03-01 10:01:00', 1, 'sess_001', '/products', '/home', 'desktop', 'USA', 120),
('2024-03-01', '2024-03-01 11:00:00', 2, 'sess_002', '/home', 'facebook.com', 'mobile', 'UK', 30),
('2024-03-01', '2024-03-01 14:00:00', 3, 'sess_003', '/pricing', 'google.com', 'desktop', 'Canada', 90),
('2024-03-02', '2024-03-02 09:00:00', 1, 'sess_004', '/home', '', 'desktop', 'USA', 60),
('2024-03-02', '2024-03-02 10:30:00', 4, 'sess_005', '/signup', 'twitter.com', 'mobile', 'USA', 180),
('2024-03-02', '2024-03-02 15:00:00', 5, 'sess_006', '/products', 'google.com', 'tablet', 'Germany', 75);

-- Insert sample events
INSERT INTO events VALUES
('2024-03-01', '2024-03-01 10:05:00', 1, 'purchase', '{"product": "subscription"}', 29.99),
('2024-03-01', '2024-03-01 11:02:00', 2, 'signup', '{"source": "facebook"}', 0),
('2024-03-01', '2024-03-01 14:10:00', 3, 'purchase', '{"product": "addon"}', 9.99),
('2024-03-02', '2024-03-02 10:35:00', 4, 'signup', '{"source": "twitter"}', 0),
('2024-03-02', '2024-03-02 15:05:00', 5, 'purchase', '{"product": "subscription"}', 29.99);
