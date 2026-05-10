#!/usr/bin/env python3
"""
Migra dados do SQLite para PostgreSQL.
Executa depois que o PostgreSQL já está rodando e DATABASE_URL está configurado.

Uso: python3 migrate_sqlite_to_pg.py
"""

import os
import sys

SQLITE_PATH = os.path.join(os.path.dirname(__file__), "data", "postsocial.db")
PG_URL = os.environ.get("DATABASE_URL", "")

if not PG_URL:
    print("ERRO: Defina DATABASE_URL antes de executar.")
    sys.exit(1)

if PG_URL.startswith("postgres://"):
    PG_URL = PG_URL.replace("postgres://", "postgresql://", 1)

try:
    import sqlalchemy as sa
except ImportError:
    print("ERRO: sqlalchemy não instalado. Execute: pip install sqlalchemy psycopg2-binary")
    sys.exit(1)

print(f"SQLite: {SQLITE_PATH}")
print(f"PostgreSQL: {PG_URL[:40]}...")

sqlite_eng = sa.create_engine(f"sqlite:///{SQLITE_PATH}")
pg_eng = sa.create_engine(PG_URL)

meta = sa.MetaData()
meta.reflect(bind=sqlite_eng)

tables_in_order = [
    "clients",
    "instagram_accounts",
    "tiktok_accounts",
    "caption_templates",
    "whitelabel_config",
    "post_queue",
]

with sqlite_eng.connect() as src, pg_eng.connect() as dst:
    for table_name in tables_in_order:
        if table_name not in meta.tables:
            print(f"  SKIP {table_name} (não existe no SQLite)")
            continue

        table = meta.tables[table_name]
        rows = src.execute(sa.select(table)).fetchall()
        keys = [c.key for c in table.columns]

        if not rows:
            print(f"  SKIP {table_name} (vazio)")
            continue

        # Desabilitar verificação de FK temporariamente no PostgreSQL
        dst.execute(sa.text("SET session_replication_role = replica"))

        # Limpar tabela no destino para evitar duplicatas
        dst.execute(sa.text(f'TRUNCATE TABLE "{table_name}" RESTART IDENTITY CASCADE'))

        batch = [dict(zip(keys, row)) for row in rows]
        dst.execute(table.insert(), batch)
        dst.execute(sa.text("SET session_replication_role = DEFAULT"))
        dst.commit()
        print(f"  OK {table_name}: {len(rows)} registros migrados")

print("\nMigração concluída! Atualize DATABASE_URL no .env e reinicie os containers.")
