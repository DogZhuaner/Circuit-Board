import json
from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from itsdangerous import BadData, URLSafeSerializer
from mysql.connector import Error

from recording_archive import store_archive
from db import MySQLConnector
from exam_access import CLASS_ELIGIBILITY, ExamEntryError
from tools.config import EXAM_SCORE_KEY


def verified_receipt(token, student_no, exam_id):
    if not EXAM_SCORE_KEY:
        raise ExamEntryError("服务端尚未配置考试成绩签名密钥", 503)
    try:
        proof = URLSafeSerializer(EXAM_SCORE_KEY, salt="wiring-exam-score-v1").loads(token)
        if str(proof["student_no"]) != str(student_no) or str(proof["exam_id"]) != str(exam_id):
            raise ValueError
        score = Decimal(str(proof["score"]))
        if not score.is_finite():
            raise ValueError
        score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if abs(score) >= 100000:
            raise ValueError
        return score, proof
    except (BadData, KeyError, TypeError, ValueError, InvalidOperation):
        raise ExamEntryError("成绩凭据无效或与本次考试不符", 400) from None


def exam_result(exam_id, student_no, student_name, *, submission=None, check_open=False):
    """Read the committed result, or commit the first verified gateway score."""
    try:
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cursor:
                if submission is not None or check_open:
                    # Submissions and deletion take the same exam lock.
                    lock = " FOR UPDATE" if submission is not None else ""
                    cursor.execute(f"SELECT test_name,rule_snapshot,publish_time,deadline_time,{CLASS_ELIGIBILITY} "
                                   f"FROM exam_test e WHERE e.id=%s{lock}", (student_no, exam_id))
                    exam = cursor.fetchone()
                    if not exam:
                        raise ExamEntryError("考试已结束", 410)
                    cursor.execute("SELECT NOW()")
                    now = cursor.fetchone()[0]
                    if now >= exam[3]:
                        raise ExamEntryError("考试已结束", 410)
                    if now < exam[2] or not exam[4]:
                        raise ExamEntryError("此考试未向你开放", 403)
                    if submission is not None and not isinstance(submission.get("receipt"), str):
                        raise ExamEntryError("缺少网关的最终检查结果", 400)
                cursor.execute(
                    "SELECT test_score FROM exam_result WHERE student_no=%s AND test_id=%s "
                    "AND test_score IS NOT NULL ORDER BY id LIMIT 1",
                    (str(student_no), str(exam_id)),
                )
                existing = cursor.fetchone()
                if existing:
                    return float(existing[0])
                if submission is None:
                    return None
                if not exam[1]:
                    raise ExamEntryError("本场考试尚未指定接线规则，无法提交成绩", 409)
                score, proof = verified_receipt(submission.get("receipt"), student_no, exam_id)
                if not proof.get("archive_sha256"):
                    raise ExamEntryError("请使用支持指定考试规则的网关重新检测", 409)
                digest = store_archive(submission.get("archive"), proof, expected_rules=json.loads(exam[1]))
                cursor.execute(
                    "INSERT INTO exam_result (student_no,student_name,test_id,test_name,test_score) "
                    "SELECT %s,%s,%s,%s,%s FROM exam_test WHERE id=%s AND deadline_time>NOW()",
                    (str(student_no), student_name, str(exam_id), exam[0], score, exam_id),
                )
                if not cursor.rowcount:
                    raise ExamEntryError("考试已结束", 410)
                cursor.execute(
                    "INSERT INTO exam_recording (result_id, recording_id, sha256) VALUES (%s,%s,%s)",
                    (cursor.lastrowid, proof["recording_id"], digest),
                )
                db.connection.commit()
                return float(score)
    except Error as exc:
        raise ExamEntryError("无法确认成绩是否已保存，请重试", 503) from exc
