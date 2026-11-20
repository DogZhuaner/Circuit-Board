import json
from typing import Optional

from itsdangerous import URLSafeSerializer, URLSafeTimedSerializer

from db import MySQLConnector
from tools.config import EXAM_SCORE_KEY, STUDENT_WEB_CONFIG


# Only successful student login issues a ticket for the selected exam.
exam_ticket = URLSafeSerializer(STUDENT_WEB_CONFIG["secret_key"], salt="student-exam-entry")


class ExamEntryError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


CLASS_ELIGIBILITY = """(e.class_restricted = FALSE OR EXISTS (
    SELECT 1 FROM exam_class ec JOIN class_student cs ON cs.class_id = ec.class_id
    WHERE ec.exam_id = e.id AND cs.student_no = %s
))"""


def open_exam_rows(student_no, fields, exam_id=None):
    sql = f"""SELECT {fields} FROM exam_test e
              WHERE e.publish_time <= NOW() AND NOW() < e.deadline_time AND {CLASS_ELIGIBILITY}"""
    params = [student_no]
    if exam_id is not None:
        sql += " AND e.id = %s"
        params.append(exam_id)
    connector = MySQLConnector()
    try:
        return connector.query(sql + " ORDER BY e.deadline_time, e.id", params)
    except RuntimeError as exc:
        raise ExamEntryError("暂时无法查询考试，请稍后重试", 503) from exc
    finally:
        connector.close()


def open_exams(student_no, exam_id: Optional[int] = None) -> list[dict]:
    fields = "e.id, e.test_name, e.deadline_time"
    if exam_id is not None:
        fields += ", e.exam_content, e.rule_filename"
    rows = open_exam_rows(student_no, fields, exam_id)
    exams = [{"id": row[0], "name": row[1], "deadline": str(row[2])} for row in rows]
    if exam_id is not None and rows:
        exams[0].update(content=rows[0][3], rule_filename=rows[0][4])
    return exams


def require_open_exam(raw_id: object, student_no) -> dict:
    try:
        exam_id = int(str(raw_id))
    except (TypeError, ValueError):
        raise ExamEntryError("请先选择考试", 400) from None
    exams = open_exams(student_no, exam_id)
    if not exams:
        raise ExamEntryError("此考试当前未向你开放，请返回选择其他考试或练习", 409)
    return exams[0]


def exam_rule_ticket(exam_id, student_no):
    rows = open_exam_rows(student_no, "e.rule_filename, e.rule_snapshot", exam_id)
    if not rows:
        raise ExamEntryError("考试当前未开放", 409)
    filename, snapshot = rows[0]
    if not filename or not snapshot:
        raise ExamEntryError("本场考试尚未指定接线规则，请联系教师", 409)
    if not EXAM_SCORE_KEY:
        raise ExamEntryError("考试网关签名密钥尚未配置", 503)
    try:
        rules = json.loads(snapshot)
    except (TypeError, ValueError):
        rules = None
    if not isinstance(rules, list) or not rules:
        raise ExamEntryError("本场考试的接线规则副本无效，请联系教师", 409)
    signer = URLSafeTimedSerializer(EXAM_SCORE_KEY, salt="wiring-exam-rule-v1")
    return signer.dumps({"exam": str(exam_id), "student": str(student_no),
                         "filename": filename, "rules": rules})
