"""Track an exam page's gateway connection and persist submissions after page exit."""
import logging
import threading
import time
from contextlib import contextmanager


class ExamExitQueue:
    reconnect_seconds = 45

    def __init__(self, store, submit):
        self.store = store
        self.submit = submit
        self.clients = {}
        self.lock = threading.RLock()
        self.wake = threading.Event()
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS exam_exit_jobs (
                token TEXT PRIMARY KEY, session TEXT NOT NULL, recording TEXT NOT NULL UNIQUE,
                destination TEXT NOT NULL, ticket TEXT NOT NULL, state TEXT NOT NULL,
                due REAL NOT NULL, detail TEXT NOT NULL DEFAULT '')""")

    def arm(self, token, session, recording, destination, ticket):
        with self.store.connection() as db:
            db.execute("INSERT INTO exam_exit_jobs(token,session,recording,destination,ticket,state,due) "
                       "VALUES (?,?,?,?,?,'armed',?)",
                       (token, session, recording, destination, ticket, time.time() + self.reconnect_seconds))
        self.wake.set()

    def state(self, token):
        with self.store.connection() as db:
            row = db.execute("SELECT state,detail FROM exam_exit_jobs WHERE token=?", (token,)).fetchone()
        if row and row['state'] == 'submitted':
            return {'state': 'submitted', 'score': float(row['detail'])}
        return dict(row) if row else None

    def leave(self, token):
        with self.lock, self.store.connection() as db:
            db.execute("UPDATE exam_exit_jobs SET state='queued',due=0 WHERE token=? AND state='armed'", (token,))
        self.wake.set()

    def release(self, token):
        with self.lock, self.store.connection() as db:
            db.execute("DELETE FROM exam_exit_jobs WHERE token=? AND state='armed'", (token,))
            return not db.execute("SELECT 1 FROM exam_exit_jobs WHERE token=? AND state='queued'", (token,)).fetchone()

    @contextmanager
    def connected(self, token):
        with self.lock:
            self.clients[token] = self.clients.get(token, 0) + 1
        try:
            yield
        finally:
            with self.lock:
                self.clients[token] -= 1
                if not self.clients[token]:
                    del self.clients[token]
                    with self.store.connection() as db:
                        db.execute("UPDATE exam_exit_jobs SET due=? WHERE token=? AND state='armed'",
                                   (time.time() + self.reconnect_seconds, token))

    def process_due(self):
        with self.lock, self.store.connection() as db:
            rows = db.execute("SELECT * FROM exam_exit_jobs WHERE state IN ('armed','queued') AND due<=?",
                              (time.time(),)).fetchall()
            jobs = [r for r in rows if r['state'] == 'queued' or r['token'] not in self.clients]
            db.executemany("UPDATE exam_exit_jobs SET state='queued' WHERE token=?", [(r['token'],) for r in jobs])
        for job in jobs:
            try:
                state, detail = self.submit(job)
            except Exception:
                logging.exception("关闭页面后交卷失败，将重试，记录 %s", job['recording'])
                state, detail = 'queued', '暂时无法提交，网关将重试'
            with self.store.connection() as db:
                db.execute("UPDATE exam_exit_jobs SET state=?,detail=?,due=?,ticket=CASE WHEN ?='queued' "
                           "THEN ticket ELSE '' END WHERE token=?",
                           (state, detail, time.time() + 5, state, job['token']))

    def run(self):
        while True:
            try:
                self.process_due()
            except Exception:
                logging.exception("读取自动交卷队列失败，将重试")
            self.wake.wait(2)
            self.wake.clear()
