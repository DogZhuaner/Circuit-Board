import hashlib
import json
import re
from collections import Counter
from contextlib import closing
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, session

from db import MySQLConnector
from recording_archive import archive_path
from student_webui.model_service import ModelError, completion


feedback = Blueprint("score_feedback", __name__)
ASSESSMENT_SKILL = Path(__file__).resolve().parent / "skills" / "student-self-assessment" / "SKILL.md"


def split_knowledge_points(value: str | None) -> list[str]:
    return [s.strip() for s in re.split(r"[,，、;；]", value or "") if s.strip()]


def score_rows(db: MySQLConnector, student_no: str) -> list:
    return db.query(
        "SELECT r.id,r.test_id,r.test_name,r.test_score,r.knowledge,w.sha256,r.created_at,s.facts "
        "FROM exam_result r LEFT JOIN exam_recording w ON w.result_id=r.id "
        "LEFT JOIN exam_result_summary s ON s.result_id=r.id "
        "WHERE r.student_no=%s AND r.test_score IS NOT NULL ORDER BY r.created_at,r.id",
        (student_no,),
    )


def recent_results(rows: list) -> list[dict]:
    exams = []
    seen = set()
    for result_id, exam_id, name, score, knowledge, digest, created_at, raw_facts in reversed(rows):
        if exam_id in seen or exam_id.upper().startswith("DEMO"):
            continue
        facts = json.loads(raw_facts) if raw_facts else {}
        simulated = facts.get("simulated")
        if digest and simulated is None:
            # Older recordings only kept their simulation flag in the archive.
            try:
                metadata = json.loads(archive_path(digest).read_bytes())["metadata"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            simulated = metadata.get("simulated") is True
        if simulated and facts.get("include_in_feedback") is not True:
            continue
        seen.add(exam_id)
        exams.append({
            "result_id": result_id, "考试": name, "成绩记录时间": str(created_at), "得分": float(score),
            "规则总正分": facts.get("available_points"), "正分接线项数": facts.get("positive_pairs"),
            "最终命中正分项数": facts.get("matched_positive_pairs"),
            "最终未匹配规则的接线数": facts.get("unmatched_pairs"),
            "已记录易错点": sorted(set(split_knowledge_points(knowledge))) or None,
        })
        if simulated:
            exams[-1]["回顾来源"] = "模拟接线回顾，得分采用成绩表记录"
        if len(exams) == 20:
            break
    return exams[::-1]


def assessment_instructions(skill_file: Path = ASSESSMENT_SKILL) -> str:
    try:
        source = skill_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        current_app.logger.exception("读取点评规则失败：%s", skill_file)
        raise ModelError("点评规则暂时不可用，请稍后重试。", 503) from exc
    if source.startswith("---\n"):
        _, _, source = source[4:].partition("\n---\n")
    if not source.strip():
        raise ModelError("点评规则内容为空或格式有误。", 503)
    return source.strip()


def commentary_data(exams: list[dict]) -> str:
    counts = Counter(point for exam in exams for point in (exam["已记录易错点"] or []))
    data = {
        "逐场成绩（从早到晚）": [{k: v for k, v in exam.items() if k != "result_id"} for exam in exams],
        "有易错点标签的场数": sum(bool(exam["已记录易错点"]) for exam in exams),
        "各易错点出现的场数": dict(counts),
    }
    return json.dumps(data, ensure_ascii=False)


@feedback.post("/scores/ai-comment")
def generate_comment():
    student = session.get("student")
    if not student:
        return jsonify(message="登录已过期，请重新登录。"), 401
    if not request.is_json:
        return jsonify(message="请求格式有误，请刷新页面重试。"), 415
    student_no = student["id"]
    # A connection-scoped lock also covers concurrent requests from other tabs/workers.
    lock = "score:" + hashlib.sha256(str(student_no).encode()).hexdigest()[:48]
    try:
        with closing(MySQLConnector()) as db:
            if db.query("SELECT GET_LOCK(%s,0)", (lock,))[0][0] != 1:
                return jsonify(message="另一页面正在生成点评，请稍后重试。"), 409
            exams = recent_results(score_rows(db, student_no))
            if not exams:
                return jsonify(message="暂无可用于点评的考试成绩。"), 422
            answer = completion("chat", commentary_data(exams), instructions=assessment_instructions()).strip()
        return jsonify(comment=answer, count=len(exams)), 200, {"Cache-Control": "no-store"}
    except ModelError as exc:
        return jsonify(message=str(exc)), exc.status
    except RuntimeError:
        current_app.logger.exception("读取点评所需成绩失败")
        return jsonify(message="暂时无法读取考试成绩，请稍后重试。"), 503
