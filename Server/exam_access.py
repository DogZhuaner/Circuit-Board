from typing import Optional

from itsdangerous import URLSafeSerializer

from db import MySQLConnector
from tools.config import STUDENT_WEB_CONFIG


# Only successful student login issues a ticket for the selected exam.
exam_ticket = URLSafeSerializer(STUDENT_WEB_CONFIG["secret_key"], salt="student-exam-entry")


class ExamEntryError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def open_exams(exam_id: Optional[int] = None) -> list[dict]:
    sql = """
        SELECT id, test_name, deadline_time
        FROM exam_test
        WHERE publish_time <= NOW() AND NOW() < deadline_time
    """
    params = ()
    if exam_id is not None:
        sql += " AND id = %s"
        params = (exam_id,)
    connector = MySQLConnector()
    try:
        rows = connector.query(sql + " ORDER BY deadline_time, id", params)
    except RuntimeError as exc:
        raise ExamEntryError("暂时无法查询考试，请稍后重试", 503) from exc
    finally:
        connector.close()
    return [{"id": row[0], "name": row[1], "deadline": str(row[2])} for row in rows]


def require_open_exam(raw_id: object) -> dict:
    try:
        exam_id = int(str(raw_id))
    except (TypeError, ValueError):
        raise ExamEntryError("请先选择考试", 400) from None
    exams = open_exams(exam_id)
    if not exams:
        raise ExamEntryError("所选考试当前未开放，请返回选择其他考试或练习", 409)
    return exams[0]
