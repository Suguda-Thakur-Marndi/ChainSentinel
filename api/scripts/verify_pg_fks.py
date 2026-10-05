import os
import sys
sys.path.insert(0, os.path.abspath("."))
import psycopg
import app.models as models

def main():
    # Introspect expected FKs from SQLAlchemy metadata
    expected_fks = {}
    for table_name, table in models.Base.metadata.tables.items():
        for fk in table.foreign_keys:
            # fk.parent is Column, fk.column is target Column
            source_col = fk.parent.name
            target_table = fk.column.table.name
            target_col = fk.column.name
            expected_fks[(table_name, source_col)] = (target_table, target_col)

    # Introspect actual FKs from PostgreSQL catalog
    actual_fks = {}
    with psycopg.connect('postgresql://postgres@127.0.0.1:5433/riskwise_test') as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    rc.update_rule,
                    rc.delete_rule,
                    tc.constraint_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                JOIN information_schema.referential_constraints AS rc
                    ON rc.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema = 'public'
                ORDER BY tc.table_name, kcu.column_name;
            """)
            rows = cur.fetchall()
            for r in rows:
                tbl, col, f_tbl, f_col, upd, dlt, cname = r
                actual_fks[(tbl, col)] = {
                    'target_table': f_tbl,
                    'target_col': f_col,
                    'update_rule': upd,
                    'delete_rule': dlt,
                    'constraint_name': cname
                }

    print(f"Total expected FKs in SQLAlchemy metadata: {len(expected_fks)}")
    print(f"Total actual FKs in PostgreSQL: {len(actual_fks)}")

    mismatches = 0
    print("\n| Source Table | Source Column | Target Table | Target Column | Update Rule | Delete Rule | Status |")
    print("|--------------|---------------|--------------|---------------|-------------|-------------|--------|")
    for (src_tbl, src_col), (exp_target_tbl, exp_target_col) in sorted(expected_fks.items()):
        act = actual_fks.get((src_tbl, src_col))
        if act and act['target_table'] == exp_target_tbl and act['target_col'] == exp_target_col:
            status = "VERIFIED"
        else:
            status = "MISMATCH / MISSING"
            mismatches += 1
        upd = act['update_rule'] if act else "N/A"
        dlt = act['delete_rule'] if act else "N/A"
        print(f"| {src_tbl} | {src_col} | {exp_target_tbl} | {exp_target_col} | {upd} | {dlt} | {status} |")

    print(f"\nTotal FK mismatches / failures: {mismatches}")
    assert mismatches == 0
    print("All Foreign Keys in PostgreSQL match SQLAlchemy metadata exactly!")

if __name__ == '__main__':
    main()
