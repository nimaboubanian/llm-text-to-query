from sqlalchemy import inspect

def get_database_schema_string(engine):
    """
    Introspects the database to generate a DDL-like string for the LLM prompt.
    """
    inspector = inspect(engine)
    schema_strings = []
    
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        foreign_keys = inspector.get_foreign_keys(table_name)
        
        column_descriptions = []
        for column in columns:
            col_desc = f"{column['name']} ({str(column['type'])})"
            column_descriptions.append(col_desc)
        
        fk_descriptions = []
        for fk in foreign_keys:
            referred_table = fk['referred_table']
            referred_columns = ", ".join(fk['referred_columns'])
            fk_desc = f"FOREIGN KEY ({', '.join(fk['constrained_columns'])}) REFERENCES {referred_table}({referred_columns})"
            fk_descriptions.append(fk_desc)
        
        table_description = f"Table '{table_name}' has columns: " + ", ".join(column_descriptions)
        if fk_descriptions:
            table_description += ". " + " ".join(fk_descriptions)
        
        schema_strings.append(table_description)
    
    return "\n".join(schema_strings)
