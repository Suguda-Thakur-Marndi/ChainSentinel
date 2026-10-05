import os
import sys
sys.path.insert(0, os.path.abspath("."))
import re
import psycopg
import app.models as models

def main():
    with open('alembic/versions/d11e5e8a65df_initial_schema.py') as f:
        content = f.read()

    migration_tables = set(re.findall(r"op\.create_table\('([^']+)'", content))
    meta_tables = set(models.Base.metadata.tables.keys())

    with psycopg.connect('postgresql://postgres@127.0.0.1:5433/riskwise_test') as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            all_pg_tables = [r[0] for r in cur.fetchall()]

    pg_domain_tables = set(all_pg_tables) - {'alembic_version'}

    print(f"Meta tables count: {len(meta_tables)}")
    print(f"Migration tables count: {len(migration_tables)}")
    print(f"PostgreSQL domain tables count: {len(pg_domain_tables)}")

    # Table to Model class mapping
    table_to_model = {}
    for mapper in models.Base.registry.mappers:
        table_to_model[mapper.persist_selectable.name] = mapper.class_.__name__

    print("\n| # | Table | Model | Migration | PostgreSQL | Status |")
    print("|---|-------|-------|-----------|------------|--------|")
    for i, t in enumerate(sorted(meta_tables), 1):
        m_cls = table_to_model.get(t, "N/A")
        in_mig = "YES" if t in migration_tables else "NO"
        in_pg = "YES" if t in pg_domain_tables else "NO"
        status = "VERIFIED" if in_mig == "YES" and in_pg == "YES" else "MISMATCH"
        print(f"| {i:02d} | {t} | {m_cls} | {in_mig} | {in_pg} | {status} |")

    missing = meta_tables - pg_domain_tables
    unexpected = pg_domain_tables - meta_tables
    print(f"\nMissing tables: {missing if missing else 'None'}")
    print(f"Unexpected tables: {unexpected if unexpected else 'None'}")

if __name__ == '__main__':
    main()
