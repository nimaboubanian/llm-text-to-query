// Neo4j Example: Social Network Database
// Run these commands in Neo4j Browser or via cypher-shell

// Clear existing data
MATCH (n) DETACH DELETE n;

// Create Person nodes
CREATE (alice:Person {name: 'Alice', age: 28, city: 'New York', occupation: 'Engineer'})
CREATE (bob:Person {name: 'Bob', age: 32, city: 'San Francisco', occupation: 'Designer'})
CREATE (carol:Person {name: 'Carol', age: 25, city: 'New York', occupation: 'Developer'})
CREATE (david:Person {name: 'David', age: 35, city: 'Boston', occupation: 'Manager'})
CREATE (eve:Person {name: 'Eve', age: 29, city: 'San Francisco', occupation: 'Data Scientist'})
CREATE (frank:Person {name: 'Frank', age: 31, city: 'New York', occupation: 'Engineer'});

// Create Company nodes
CREATE (techcorp:Company {name: 'TechCorp', industry: 'Technology', size: 500})
CREATE (designco:Company {name: 'DesignCo', industry: 'Design', size: 50})
CREATE (datalab:Company {name: 'DataLab', industry: 'Analytics', size: 200});

// Create Skill nodes
CREATE (python:Skill {name: 'Python'})
CREATE (javascript:Skill {name: 'JavaScript'})
CREATE (design:Skill {name: 'UI Design'})
CREATE (ml:Skill {name: 'Machine Learning'})
CREATE (management:Skill {name: 'Project Management'});

// Create FRIENDS relationships
MATCH (alice:Person {name: 'Alice'}), (bob:Person {name: 'Bob'})
CREATE (alice)-[:FRIENDS {since: 2020}]->(bob);
MATCH (alice:Person {name: 'Alice'}), (carol:Person {name: 'Carol'})
CREATE (alice)-[:FRIENDS {since: 2021}]->(carol);
MATCH (bob:Person {name: 'Bob'}), (eve:Person {name: 'Eve'})
CREATE (bob)-[:FRIENDS {since: 2019}]->(eve);
MATCH (carol:Person {name: 'Carol'}), (frank:Person {name: 'Frank'})
CREATE (carol)-[:FRIENDS {since: 2022}]->(frank);
MATCH (david:Person {name: 'David'}), (alice:Person {name: 'Alice'})
CREATE (david)-[:FRIENDS {since: 2018}]->(alice);

// Create WORKS_AT relationships
MATCH (alice:Person {name: 'Alice'}), (techcorp:Company {name: 'TechCorp'})
CREATE (alice)-[:WORKS_AT {role: 'Senior Engineer', since: 2020}]->(techcorp);
MATCH (bob:Person {name: 'Bob'}), (designco:Company {name: 'DesignCo'})
CREATE (bob)-[:WORKS_AT {role: 'Lead Designer', since: 2019}]->(designco);
MATCH (carol:Person {name: 'Carol'}), (techcorp:Company {name: 'TechCorp'})
CREATE (carol)-[:WORKS_AT {role: 'Developer', since: 2022}]->(techcorp);
MATCH (eve:Person {name: 'Eve'}), (datalab:Company {name: 'DataLab'})
CREATE (eve)-[:WORKS_AT {role: 'Data Scientist', since: 2021}]->(datalab);

// Create HAS_SKILL relationships
MATCH (alice:Person {name: 'Alice'}), (python:Skill {name: 'Python'})
CREATE (alice)-[:HAS_SKILL {level: 'expert'}]->(python);
MATCH (alice:Person {name: 'Alice'}), (javascript:Skill {name: 'JavaScript'})
CREATE (alice)-[:HAS_SKILL {level: 'intermediate'}]->(javascript);
MATCH (bob:Person {name: 'Bob'}), (design:Skill {name: 'UI Design'})
CREATE (bob)-[:HAS_SKILL {level: 'expert'}]->(design);
MATCH (eve:Person {name: 'Eve'}), (python:Skill {name: 'Python'})
CREATE (eve)-[:HAS_SKILL {level: 'expert'}]->(python);
MATCH (eve:Person {name: 'Eve'}), (ml:Skill {name: 'Machine Learning'})
CREATE (eve)-[:HAS_SKILL {level: 'expert'}]->(ml);
MATCH (david:Person {name: 'David'}), (management:Skill {name: 'Project Management'})
CREATE (david)-[:HAS_SKILL {level: 'expert'}]->(management);
