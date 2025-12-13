-- SQLite Example: Task Management Database
-- Note: SQLite uses simpler types and no AUTO_INCREMENT (uses AUTOINCREMENT)

-- Create 'projects' table
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT CHECK(status IN ('planning', 'active', 'completed', 'on_hold')) DEFAULT 'planning',
    start_date DATE,
    end_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create 'users' table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    role TEXT CHECK(role IN ('admin', 'manager', 'developer', 'viewer')) DEFAULT 'developer',
    active INTEGER DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Create 'tasks' table
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    project_id INTEGER NOT NULL,
    assigned_to INTEGER,
    priority TEXT CHECK(priority IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
    status TEXT CHECK(status IN ('todo', 'in_progress', 'review', 'done')) DEFAULT 'todo',
    estimated_hours REAL,
    actual_hours REAL,
    due_date DATE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (assigned_to) REFERENCES users(id)
);

-- Create 'comments' table
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Create 'tags' table
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT DEFAULT '#808080'
);

-- Create 'task_tags' junction table
CREATE TABLE IF NOT EXISTS task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (tag_id) REFERENCES tags(id)
);

-- Insert sample projects
INSERT INTO projects (name, description, status, start_date, end_date) VALUES
('Website Redesign', 'Complete overhaul of company website', 'active', '2024-01-01', '2024-06-30'),
('Mobile App v2', 'Major update to mobile application', 'active', '2024-02-01', '2024-08-31'),
('API Integration', 'Third-party API integrations', 'planning', '2024-04-01', NULL),
('Database Migration', 'Migrate from legacy system', 'completed', '2023-10-01', '2024-01-15');

-- Insert sample users
INSERT INTO users (username, email, role) VALUES
('john_admin', 'john@company.com', 'admin'),
('sarah_pm', 'sarah@company.com', 'manager'),
('mike_dev', 'mike@company.com', 'developer'),
('lisa_dev', 'lisa@company.com', 'developer'),
('tom_viewer', 'tom@company.com', 'viewer');

-- Insert sample tasks
INSERT INTO tasks (title, description, project_id, assigned_to, priority, status, estimated_hours, due_date) VALUES
('Design homepage mockup', 'Create wireframes and mockups', 1, 3, 'high', 'done', 16, '2024-02-01'),
('Implement responsive nav', 'Mobile-first navigation', 1, 3, 'high', 'in_progress', 8, '2024-02-15'),
('Setup CI/CD pipeline', 'Configure automated deployments', 1, 4, 'medium', 'todo', 12, '2024-03-01'),
('User authentication', 'OAuth2 implementation', 2, 4, 'critical', 'in_progress', 24, '2024-03-15'),
('Push notifications', 'Firebase integration', 2, 3, 'medium', 'todo', 16, '2024-04-01'),
('API documentation', 'Swagger/OpenAPI docs', 3, 4, 'low', 'todo', 8, '2024-05-01'),
('Data export scripts', 'Export legacy data', 4, 3, 'high', 'done', 20, '2023-12-15');

-- Insert sample tags
INSERT INTO tags (name, color) VALUES
('frontend', '#3498db'),
('backend', '#e74c3c'),
('urgent', '#f39c12'),
('bug', '#9b59b6'),
('feature', '#2ecc71'),
('documentation', '#95a5a6');

-- Insert task-tag relationships
INSERT INTO task_tags (task_id, tag_id) VALUES
(1, 1), (1, 5),
(2, 1), (2, 5),
(3, 2),
(4, 2), (4, 5),
(5, 2), (5, 5),
(6, 6),
(7, 2);

-- Insert sample comments
INSERT INTO comments (task_id, user_id, content) VALUES
(1, 2, 'Looks great! Approved for development.'),
(2, 3, 'Working on hamburger menu animation.'),
(4, 4, 'Should we use JWT or session tokens?'),
(4, 2, 'Let''s go with JWT for better mobile support.'),
(7, 3, 'Migration completed successfully!');
