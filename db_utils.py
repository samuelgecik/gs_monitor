\
import sqlite3
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DATABASE_DIR = os.path.join(os.path.dirname(__file__), 'data')
DEFAULT_DB_NAME = 'telegram_group_stats.db'

def get_db_connection(db_path=None):
    """Establishes a connection to the SQLite database, supporting env override."""
    # Check environment variable first
    env_db_path = os.environ.get('DB_PATH')
    if env_db_path:
        db_path = env_db_path
    if db_path is None:
        # Construct the default path if not provided
        if not os.path.exists(DATABASE_DIR):
            os.makedirs(DATABASE_DIR)
            logging.info(f"Created directory: {DATABASE_DIR}")
        db_path = os.path.join(DATABASE_DIR, DEFAULT_DB_NAME)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row # Access columns by name
        logging.info(f"Successfully connected to database: {db_path}")
        return conn
    except sqlite3.Error as e:
        logging.error(f"Error connecting to database {db_path}: {e}")
        raise

def create_tables(conn):
    """Creates the necessary tables in the database if they don't exist."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS member_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                member_count INTEGER NOT NULL
            )
        """)
        conn.commit()
        logging.info("Table 'member_stats' checked/created successfully.")
    except sqlite3.Error as e:
        logging.error(f"Error creating table 'member_stats': {e}")
        raise

def insert_member_count(conn, count):
    """Inserts a new member count record into the database."""
    if count is None:
        logging.warning("Attempted to insert None for member_count. Skipping.")
        return False
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO member_stats (member_count)
            VALUES (?)
        """, (count,))
        conn.commit()
        logging.info(f"Inserted member count: {count}")
        return True
    except sqlite3.Error as e:
        logging.error(f"Error inserting member count {count}: {e}")
        return False

def get_all_member_stats(conn):
    """Retrieves all member stats from the database, ordered by timestamp."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, member_count FROM member_stats ORDER BY timestamp ASC")
        stats = cursor.fetchall()
        logging.info(f"Retrieved {len(stats)} records from 'member_stats'.")
        return stats
    except sqlite3.Error as e:
        logging.error(f"Error retrieving all member stats: {e}")
        return []

def get_latest_member_count(conn):
    """Retrieves the most recent member count from the database."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT member_count, timestamp FROM member_stats ORDER BY timestamp DESC LIMIT 1")
        latest_stat = cursor.fetchone()
        if latest_stat:
            logging.info(f"Retrieved latest member count: {latest_stat['member_count']} at {latest_stat['timestamp']}")
            return latest_stat
        else:
            logging.info("No records found in 'member_stats'.")
            return None
    except sqlite3.Error as e:
        logging.error(f"Error retrieving latest member count: {e}")
        return None

if __name__ == '__main__':
    # Example usage and testing of db_utils
    logging.info("Running db_utils.py for testing...")
    
    # Construct path relative to this script for testing
    test_db_path = os.path.join(DATABASE_DIR, 'test_db_utils.db')
    if os.path.exists(test_db_path):
        os.remove(test_db_path) # Clean up before test
        logging.info(f"Removed existing test database: {test_db_path}")

    connection = None
    try:
        connection = get_db_connection(db_path=test_db_path)
        create_tables(connection)
        
        # Test insertions
        insert_member_count(connection, 100)
        insert_member_count(connection, 105)
        insert_member_count(connection, None) # Test inserting None
        
        # Test retrieval
        all_stats = get_all_member_stats(connection)
        logging.info(f"All stats: {[(stat['timestamp'], stat['member_count']) for stat in all_stats]}")
        
        latest = get_latest_member_count(connection)
        if latest:
            logging.info(f"Latest stat: Count={latest['member_count']}, Time={latest['timestamp']}")
        else:
            logging.info("No latest stat found (as expected if only None was inserted after valid ones, or DB is empty).")

        # Test with default path (creates in data/telegram_group_stats.db)
        # default_conn = get_db_connection()
        # create_tables(default_conn)
        # insert_member_count(default_conn, 500)
        # default_conn.close()

    except Exception as e:
        logging.error(f"An error occurred during db_utils testing: {e}")
    finally:
        if connection:
            connection.close()
            logging.info(f"Closed connection to {test_db_path}")
        # Clean up test database
        # if os.path.exists(test_db_path):
        #     os.remove(test_db_path)
        #     logging.info(f"Cleaned up test database: {test_db_path}")
    logging.info("db_utils.py testing finished.")
