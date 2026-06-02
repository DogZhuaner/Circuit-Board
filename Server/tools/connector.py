# connector.py

import mysql.connector
from mysql.connector import Error
from tools.config import DB_CONFIG

class MySQLConnector:
    def __init__(self, config=DB_CONFIG):
        self.config = config
        self.connection = None

    def connect(self):
        try:
            self.connection = mysql.connector.connect(**self.config)
            if self.connection.is_connected():
                print("✅ 数据库连接成功")
        except Error as e:
            print(f"❌ 数据库连接失败：{e}")

    def query(self, sql, params=None):
        """
        执行 SELECT 查询
        """
        try:
            if self.connection is None or not self.connection.is_connected():
                self.connect()
            cursor = self.connection.cursor()
            cursor.execute(sql, params or ())
            results = cursor.fetchall()
            return results
        except Error as e:
            print(f"❌ 查询出错：{e}")
            return []
        finally:
            cursor.close()

    def execute(self, sql, params=None):
        """
        执行 INSERT、UPDATE、DELETE 操作
        返回 True 表示成功，False 表示失败
        """
        try:
            if self.connection is None or not self.connection.is_connected():
                self.connect()
            cursor = self.connection.cursor()
            cursor.execute(sql, params or ())
            self.connection.commit()
            print("✅ SQL 执行成功")
            return True
        except Error as e:
            print(f"❌ SQL 执行失败：{e}")
            return False
        finally:
            cursor.close()

    def close(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            print("🔌 数据库连接已关闭")
