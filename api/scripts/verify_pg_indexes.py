import os
import sys
sys.path.insert(0, os.path.abspath("."))
import psycopg

def main():
    with psycopg.connect('postgresql://postgres@127.0.0.1:5433/riskwise_test') as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY tablename, indexname;
            """)
            rows = cur.fetchall()

    print(f"Total indexes in PostgreSQL public schema: {len(rows)}")
    for tbl, idx, definition in rows:
        print(f"| {tbl} | {idx} | {definition} |")

if __name__ == '__main__':
    main()
