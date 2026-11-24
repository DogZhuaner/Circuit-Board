import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import median

from recording_archive import wiring_rule_weights
from score_feedback import assessment_instructions
from student_webui.model_service import ModelError, model_completion
from tools.config import TEACHER_MODEL


EXAM_SKILL = Path(__file__).resolve().parents[1] / "skills" / "teacher-exam-performance" / "SKILL.md"
BAND_LIMITS = (60, 70, 80, 90)


def exam_score_summary(rows: list, rule_snapshot: str | None) -> dict:
    full = None
    if rule_snapshot:
        weights = wiring_rule_weights(json.loads(rule_snapshot))
        full = sum(value for value in weights.values() if value > 0) or None
    unit = '%' if full else '分'
    labels = [f'低于60{unit}', *(f'{lo}至不足{hi}{unit}' for lo, hi in zip(BAND_LIMITS, BAND_LIMITS[1:])),
              f'90{unit}及以上']
    bands = [dict(label=label, count=0) for label in labels]
    scores = []
    topic_counts = Counter()
    tagged = 0
    for row in rows:
        if row['score'] is None:
            continue
        score = Decimal(str(row['score']))
        scores.append(score)
        if row.get('topics'):
            tagged += 1
            topic_counts.update(set(row['topics']))
        row['candidate'] = f'考生{len(scores):02d}'
        band_value = score * 100 / full if full else score
        index = sum(band_value >= cutoff for cutoff in BAND_LIMITS)
        bands[index]['count'] += 1
        row['band'] = labels[index]
    return {
        'count': len(scores), 'missing': len(rows) - len(scores), 'full_score': full,
        'average': float(round(sum(scores) / len(scores), 2)) if scores else None,
        'median': float(median(scores)) if scores else None,
        'min': float(min(scores)) if scores else None, 'max': float(max(scores)) if scores else None,
        'band_basis': f'按得分率分段（满分 {full} 分）' if full else '按原始分数分段（满分未知）',
        'bands': bands,
        'tagged': tagged,
        'topic_counts': dict(sorted(topic_counts.items(), key=lambda item: (-item[1], item[0]))),
    }


def exam_comment(name: str, rows: list, summary: dict) -> str:
    if not TEACHER_MODEL['chat']:
        raise ModelError('请在服务端配置教师点评模型 TEACHER_MODEL_CHAT_NAME。', 503)
    data = {
        '考试名称': name, '有效成绩人数': summary['count'], '无成绩人数': summary['missing'],
        '满分': summary['full_score'], '均分': summary['average'], '中位数': summary['median'],
        '最低分': summary['min'], '最高分': summary['max'], '分段口径': summary['band_basis'],
        '区间人数': {band['label']: band['count'] for band in summary['bands']},
        '有易错点记录的人数': summary['tagged'], '各易错点涉及的考生人数': summary['topic_counts'],
        '逐人成绩': [{'编号': row['candidate'], '得分': row['score'], '区间': row['band'],
                    '已记录易错点': row.get('topics') or None}
                   for row in rows if row['score'] is not None],
    }
    peak = max(band['count'] for band in summary['bands'])
    peaks = [band['label'] for band in summary['bands'] if band['count'] == peak]
    data['人数最多的区间'] = peaks
    advice = model_completion(TEACHER_MODEL, TEACHER_MODEL['chat'], json.dumps(data, ensure_ascii=False),
                              instructions=assessment_instructions(EXAM_SKILL)).strip()
    # The prose and the table use the same numbers even when a small model struggles with counting.
    scale = f"满分 {summary['full_score']} 分" if summary['full_score'] else "满分未知"
    overview = (f"本场有 {summary['count']} 人取得成绩，{summary['missing']} 人无成绩。"
                f"平均 {summary['average']:.12g} 分，中位数 {summary['median']:.12g} 分（{scale}）。")
    peak_text = (f"{peaks[0]}区间人数最多，共 {peak} 人。" if len(peaks) == 1 else
                 f"{'、'.join(peaks)}区间并列最多，各有 {peak} 人。")
    candidates = data['逐人成绩']
    low = min(candidates, key=lambda row: row['得分'])
    high = max(candidates, key=lambda row: row['得分'])
    if low['得分'] == high['得分']:
        examples = (f"{low['编号']}得 {low['得分']:.12g} 分。" if len(candidates) == 1 else
                    f"全部有效成绩均为 {low['得分']:.12g} 分。")
    else:
        examples = (f"例如，{low['编号']}得 {low['得分']:.12g} 分，位于{low['区间']}区间。"
                    f"{high['编号']}得 {high['得分']:.12g} 分，位于{high['区间']}区间。")
    return f"本场表现\n{overview}\n\n成绩区间\n{peak_text}{examples}\n\n教学建议\n{advice}"
