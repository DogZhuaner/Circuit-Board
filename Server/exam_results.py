from contextlib import closing
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from itsdangerous import BadData, URLSafeSerializer
from mysql.connector import Error

from recording_archive import store_archive
from db import MySQLConnector
from exam_access import ExamEntryError
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


def exam_result(exam_id, student_no, student_name, *, submission=None):
    """Read the committed result, or commit the first verified gateway score."""
    try:
        with closing(MySQLConnector()) as db:
            db.connect()
            with db.connection.cursor() as cursor:
                if submission is not None:
                    # Serialize submissions across server processes without changing legacy result rows.
                    cursor.execute("SELECT test_name FROM exam_test WHERE id=%s FOR UPDATE", (exam_id,))
                    exam = cursor.fetchone()
                    if not exam:
                        raise ExamEntryError("考试不存在", 404)
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
                score, proof = verified_receipt(submission.get("receipt"), student_no, exam_id)
                digest = None
                if "archive_sha256" in proof or "archive" in submission:
                    digest = store_archive(submission.get("archive"), proof)
                cursor.execute(
                    "INSERT INTO exam_result (student_no,student_name,test_id,test_name,test_score) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (str(student_no), student_name, str(exam_id), exam[0], score),
                )
                if digest:
                    cursor.execute(
                        "INSERT INTO exam_recording (result_id, recording_id, sha256) VALUES (%s,%s,%s)",
                        (cursor.lastrowid, proof["recording_id"], digest),
                    )
                db.connection.commit()
                return float(score)
    except Error as exc:
        raise ExamEntryError("无法确认成绩是否已保存，请重试", 503) from exc
