-- SQL Server Example: HR Management Database

-- Create departments table
CREATE TABLE departments (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(100) NOT NULL,
    budget DECIMAL(15,2),
    location NVARCHAR(100)
);

-- Create employees table
CREATE TABLE employees (
    id INT IDENTITY(1,1) PRIMARY KEY,
    first_name NVARCHAR(50) NOT NULL,
    last_name NVARCHAR(50) NOT NULL,
    email NVARCHAR(100) UNIQUE,
    department_id INT FOREIGN KEY REFERENCES departments(id),
    hire_date DATE,
    salary DECIMAL(10,2),
    job_title NVARCHAR(100)
);

-- Create projects table
CREATE TABLE projects (
    id INT IDENTITY(1,1) PRIMARY KEY,
    name NVARCHAR(200) NOT NULL,
    department_id INT FOREIGN KEY REFERENCES departments(id),
    start_date DATE,
    end_date DATE,
    budget DECIMAL(15,2),
    status NVARCHAR(20) DEFAULT 'active'
);

-- Create employee_projects junction table
CREATE TABLE employee_projects (
    employee_id INT FOREIGN KEY REFERENCES employees(id),
    project_id INT FOREIGN KEY REFERENCES projects(id),
    role NVARCHAR(50),
    hours_allocated INT,
    PRIMARY KEY (employee_id, project_id)
);

-- Insert departments
INSERT INTO departments (name, budget, location) VALUES
('Engineering', 500000.00, 'Building A'),
('Marketing', 200000.00, 'Building B'),
('Human Resources', 150000.00, 'Building A'),
('Finance', 300000.00, 'Building C');

-- Insert employees
INSERT INTO employees (first_name, last_name, email, department_id, hire_date, salary, job_title) VALUES
('John', 'Smith', 'john.smith@company.com', 1, '2020-01-15', 85000.00, 'Senior Developer'),
('Sarah', 'Johnson', 'sarah.j@company.com', 1, '2021-03-20', 75000.00, 'Developer'),
('Michael', 'Brown', 'mike.b@company.com', 2, '2019-06-01', 65000.00, 'Marketing Manager'),
('Emily', 'Davis', 'emily.d@company.com', 3, '2022-01-10', 55000.00, 'HR Specialist'),
('David', 'Wilson', 'david.w@company.com', 4, '2018-09-15', 90000.00, 'Finance Director'),
('Lisa', 'Anderson', 'lisa.a@company.com', 1, '2023-02-01', 70000.00, 'Developer');

-- Insert projects
INSERT INTO projects (name, department_id, start_date, end_date, budget, status) VALUES
('Website Redesign', 1, '2024-01-01', '2024-06-30', 100000.00, 'active'),
('Mobile App', 1, '2024-03-01', '2024-12-31', 200000.00, 'active'),
('Brand Campaign', 2, '2024-02-01', '2024-05-31', 50000.00, 'completed'),
('Employee Portal', 1, '2024-04-01', NULL, 75000.00, 'active');

-- Insert employee-project assignments
INSERT INTO employee_projects (employee_id, project_id, role, hours_allocated) VALUES
(1, 1, 'Lead Developer', 200),
(2, 1, 'Frontend Developer', 150),
(1, 2, 'Architect', 100),
(6, 2, 'Developer', 180),
(3, 3, 'Campaign Lead', 120),
(2, 4, 'Developer', 160);
