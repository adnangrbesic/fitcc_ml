import psycopg2
import os

try:
    conn = psycopg2.connect(
        host="db",
        database="buyguardian",
        user="postgres",
        password="password123"
    )
    cur = conn.cursor()
    cur.execute("SELECT \"OlxId\", \"Username\", \"TrustScore\" FROM \"Sellers\" ORDER BY \"TrustScore\" DESC LIMIT 5;")
    rows = cur.fetchall()
    print("=== TOP SELLERS ===")
    for r in rows:
        print(r)
    cur.close()
    conn.close()
except Exception as e:
    print("ERROR:", e)
