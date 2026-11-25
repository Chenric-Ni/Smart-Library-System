
import sqlite3

# Connect to SQLite database
conn = sqlite3.connect("seat_detection.db")
cursor = conn.cursor()

# 1. Check database tables
cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type='table'
""")

tables = cursor.fetchall()

print("========== Database Tables ==========")
for table in tables:
    print(table[0])

# 2. Count total records
cursor.execute("""
    SELECT COUNT(*)
    FROM sensor_data
""")

total = cursor.fetchone()[0]

print("\n========== Total Records ==========")
print("Total sensor records:", total)

# 3. Display latest 20 records
cursor.execute("""
    SELECT id, device_id, sequence, raw_value, received_at
    FROM sensor_data
    ORDER BY id DESC
    LIMIT 20
""")

rows = cursor.fetchall()

print("\n========== Latest 20 Records ==========")

for row in rows:
    print(
        f"ID: {row[0]}, "
        f"Device: {row[1]}, "
        f"Sequence: {row[2]}, "
        f"RAW: {row[3]}, "
        f"Time: {row[4]}"
    )

conn.close()
