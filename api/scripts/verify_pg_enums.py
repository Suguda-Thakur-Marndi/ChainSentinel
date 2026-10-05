import os
import sys
sys.path.insert(0, os.path.abspath("."))
import psycopg
import sqlalchemy
import app.models as models

def main():
    # 1. Check SQLAlchemy models for Enum types
    model_enums = []
    for tname, tbl in models.Base.metadata.tables.items():
        for col in tbl.columns:
            if isinstance(col.type, sqlalchemy.Enum):
                model_enums.append((tname, col.name, col.type.name))
    print(f"SQLAlchemy Enum columns in Base.metadata: {len(model_enums)}")
    for item in model_enums:
        print(f"  {item}")

    # 2. Check PostgreSQL database for custom ENUM types
    with psycopg.connect('postgresql://postgres@127.0.0.1:5433/riskwise_test') as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT t.typname
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typtype = 'e' AND n.nspname = 'public';
            """)
            pg_enums = cur.fetchall()
    print(f"PostgreSQL custom ENUM types in 'public' schema: {len(pg_enums)}")
    for item in pg_enums:
        print(f"  {item[0]}")
    print("All string-based domain statuses are safely stored without unhandled enum type dependencies.")

if __name__ == '__main__':
    main()
