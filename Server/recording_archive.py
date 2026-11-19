import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from exam_access import ExamEntryError


def archive_path(digest):
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("无效的归档摘要")
    root = Path(os.environ.get("WIRING_ARCHIVE_DIR") or Path(__file__).parent / "data" / "recordings")
    return root / digest[:2] / (digest + ".json")


def store_archive(raw, proof):
    if not isinstance(raw, str):
        raise ExamEntryError("缺少接线回顾文件", 400)
    content = raw.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if digest != proof.get("archive_sha256"):
        raise ExamEntryError("接线文件与成绩凭据不匹配", 400)
    try:
        record = json.loads(raw)
        valid = (record["schema_version"] == 1 and record["status"] == "completed"
                 and record["recording_id"] == proof["recording_id"]
                 and re.fullmatch(r"[a-f0-9]{32}", record["recording_id"])
                 and str(record["metadata"]["student_no"]) == str(proof["student_no"])
                 and str(record["metadata"]["test_id"]) == str(proof["exam_id"])
                 and record["latest_state"]["score"] == proof["score"]
                 and len(record["events"]) == record["last_seq"])
        if not valid:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ExamEntryError("接线文件格式或考试归属有误", 400) from None
    path = archive_path(digest)
    temp = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temp = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
    except OSError as exc:
        raise ExamEntryError("接线回顾文件保存失败，请重试", 503) from exc
    finally:
        if temp:
            temp.unlink(missing_ok=True)
    return digest
