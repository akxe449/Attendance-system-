
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "attendance.db"
SQL_PATH = Path(__file__).resolve().parent / "queries.sql"

def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return

    sql_text = SQL_PATH.read_text(encoding="utf-8")

    # Remove SQLite shell-only commands and SQL comments.
    lines = [
        line for line in sql_text.splitlines()
        if not line.strip().startswith((".headers", ".mode", "--"))
    ]
    sql_text = "\n".join(lines)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Execute queries individually so the transaction demo can roll back.
        statements = [
            statement.strip()
            for statement in sql_text.split(";")
            if statement.strip()
        ]

        for number, statement in enumerate(statements, start=1):
            print(f"\n{'=' * 18} QUERY {number} {'=' * 18}")

            cursor = conn.execute(statement)

            if cursor.description:
                rows = cursor.fetchall()
                if rows:
                    print(" | ".join(cursor.description[i][0]
                                    for i in range(len(cursor.description))))
                    for row in rows:
                        print(" | ".join(str(value) for value in row))
                else:
                    print("(No rows returned)")
            else:
                print("Statement executed successfully.")

            # Query 12 ends with ROLLBACK, so no permanent update is made.

    except sqlite3.Error as error:
        print(f"\nSQLite error: {error}")
        print("Stop here and share the error before changing the database.")

    finally:
        conn.close()

if __name__ == "__main__":
    main()

