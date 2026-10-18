from tadris.config import db_path
from tadris.db.connection import connect
from tadris.db.migrate import migrate


def main():
    conn = connect(db_path())
    print("DB schema version:", migrate(conn))

if __name__ == "__main__":
    main()