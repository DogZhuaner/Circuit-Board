import mysql.connector
from mysql.connector import Error

from tools.config import DB_CONFIG


class MySQLConnector:
    """服务器端数据库连接器。"""

    def __init__(self, config=None):
        self.config = config or DB_CONFIG
        self.connection = None

    def connect(self):
        if self.connection is not None and self.connection.is_connected():
            return
        self.connection = mysql.connector.connect(**self.config)

    def query(self, sql, params=None):
        cursor = None
        try:
            self.connect()
            cursor = self.connection.cursor()
            cursor.execute(sql, params or ())
            return cursor.fetchall()
        except Error as exc:
            raise RuntimeError(f"database query failed: {exc}") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def execute(self, sql, params=None):
        cursor = None
        try:
            self.connect()
            cursor = self.connection.cursor()
            cursor.execute(sql, params or ())
            self.connection.commit()
            return True
        except Error as exc:
            raise RuntimeError(f"database execute failed: {exc}") from exc
        finally:
            if cursor is not None:
                cursor.close()

    def close(self):
        if self.connection is not None and self.connection.is_connected():
            self.connection.close()
