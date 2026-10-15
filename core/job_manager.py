"""Bounded session-owned jobs sharing one GPU/plot/LLM resource worker.

Session expiry removes only in-memory capabilities; saved output remains on disk.
The manager is deliberately process-local: run one ASGI process per GPU instance.
"""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import secrets
import threading
import time
from typing import Callable
from uuid import uuid4


class JobError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Upload:
    path: Path
    ready: bool = False


@dataclass
class Session:
    directory: Path
    last_seen: float
    uploads: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)
    active_uploads: int = 0


@dataclass
class Job:
    job_id: str
    session_id: str
    kind: str
    directory: Path
    work: Callable | None
    status: str = "queued"
    result: dict | None = None
    error: str | None = None


class JobManager:
    def __init__(self, root_dir, *, queue_capacity=32, session_ttl=86400,
                 max_sessions=256, max_jobs_per_session=128,
                 max_uploads_per_session=64, max_pending_per_session=4):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.queue_capacity = queue_capacity
        self.session_ttl = session_ttl
        self.max_sessions = max_sessions
        self.max_jobs_per_session = max_jobs_per_session
        self.max_uploads_per_session = max_uploads_per_session
        self.max_pending_per_session = max_pending_per_session
        self.sessions = {}
        self._pending = deque()
        self._condition = threading.Condition(threading.RLock())
        self._worker = None
        self._closed = False

    @staticmethod
    def _active(session):
        return session.active_uploads or any(
            job.status in ("queued", "running") for job in session.jobs.values()
        )

    def _expire(self):
        now = time.monotonic()
        for key, session in list(self.sessions.items()):
            if now - session.last_seen > self.session_ttl and not self._active(session):
                del self.sessions[key]

    def _session(self, session_id):
        self._expire()
        session = self.sessions.get(session_id)
        if session is None:
            raise JobError(401, "세션이 없거나 만료되었습니다. 페이지를 새로고침하고 파일을 다시 올려주세요.")
        session.last_seen = time.monotonic()
        return session

    def validate_session(self, session_id):
        with self._condition:
            self._session(session_id)
        return session_id

    def create_session(self):
        with self._condition:
            self._expire()
            if self._closed:
                raise JobError(503, "서버가 종료 중입니다.")
            if len(self.sessions) >= self.max_sessions:
                raise JobError(503, "접속 가능한 세션 수를 초과했습니다. 잠시 후 다시 접속해주세요.")
            session_id = secrets.token_urlsafe(32)
            directory = self.root_dir / uuid4().hex
            directory.mkdir()
            self.sessions[session_id] = Session(directory, time.monotonic())
            return session_id

    def begin_upload(self, session_id, suffix):
        with self._condition:
            session = self._session(session_id)
            if len(session.uploads) >= self.max_uploads_per_session:
                raise JobError(429, "이 세션의 업로드 한도에 도달했습니다. 새로고침 후 다시 이용해주세요.")
            upload_id = uuid4().hex
            directory = session.directory / "uploads"
            directory.mkdir(exist_ok=True)
            path = directory / f"{upload_id}{suffix}"
            session.uploads[upload_id] = Upload(path)
            session.active_uploads += 1
            return upload_id, path

    def finish_upload(self, session_id, upload_id, *, success):
        with self._condition:
            session = self._session(session_id)
            if success:
                session.uploads[upload_id].ready = True
            else:
                session.uploads.pop(upload_id, None)
            session.active_uploads -= 1

    def upload_path(self, session_id, upload_id):
        with self._condition:
            upload = self._session(session_id).uploads.get(upload_id)
            if upload is None or not upload.ready:
                raise JobError(404, "업로드한 파일을 찾을 수 없습니다. 파일을 다시 올려주세요.")
            return upload.path

    def submit(self, session_id, kind, work):
        with self._condition:
            session = self._session(session_id)
            if self._closed:
                raise JobError(503, "서버가 종료 중입니다.")
            if len(session.jobs) >= self.max_jobs_per_session:
                raise JobError(429, "이 세션의 작업 한도에 도달했습니다. 새로고침 후 다시 이용해주세요.")
            active = sum(j.status in ("queued", "running") for j in session.jobs.values())
            if active >= self.max_pending_per_session:
                raise JobError(429, "진행 중인 요청이 많습니다. 기존 작업 완료 후 다시 요청해주세요.")
            if len(self._pending) >= self.queue_capacity:
                raise JobError(429, "분석 대기열이 가득 찼습니다. 잠시 후 다시 요청해주세요.")
            job_id = uuid4().hex
            directory = session.directory / job_id
            directory.mkdir()
            job = Job(job_id, session_id, kind, directory, work)
            session.jobs[job_id] = job
            self._pending.append(job)
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run, name="soc-resource-worker", daemon=True
                )
                self._worker.start()
            self._condition.notify()
            return self._snapshot(job)

    def _job(self, session_id, job_id):
        job = self._session(session_id).jobs.get(job_id)
        if job is None:
            raise JobError(404, "요청한 작업을 찾을 수 없습니다.")
        return job

    def _snapshot(self, job):
        position = 0
        if job.status == "queued":
            position = next(i for i, pending in enumerate(self._pending, 1)
                            if pending.job_id == job.job_id)
        data = {"job_id": job.job_id, "kind": job.kind, "status": job.status,
                "queue_position": position}
        if job.result is not None:
            data["result"] = deepcopy(job.result)
        if job.error is not None:
            data["error"] = job.error
        return data

    def get_job(self, session_id, job_id):
        with self._condition:
            return self._snapshot(self._job(session_id, job_id))

    def analysis(self, session_id, analysis_id):
        with self._condition:
            job = self._job(session_id, analysis_id)
            if job.kind != "analyze" or job.status != "completed":
                raise JobError(409, "완료된 분석 결과가 필요합니다.")
            return deepcopy(job.result)

    def analysis_image(self, session_id, analysis_id, filename):
        with self._condition:
            job = self._job(session_id, analysis_id)
            if job.kind != "analyze" or job.status != "completed":
                raise JobError(404, "분석 이미지를 찾을 수 없습니다.")
            if (filename not in job.result.get("images", {})
                    or Path(filename).name != filename
                    or "/" in filename or "\\" in filename):
                raise JobError(404, "분석 이미지를 찾을 수 없습니다.")
            path = job.directory / "images" / filename
            if not path.is_file():
                raise JobError(404, "분석 이미지를 찾을 수 없습니다.")
            return path

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._closed)
                if not self._pending:
                    return
                job = self._pending.popleft()
                job.status = "running"
            try:
                result = job.work(job.job_id, job.directory)
                if not isinstance(result, dict):
                    raise RuntimeError("작업 결과 형식이 올바르지 않습니다.")
                if result.get("error"):
                    raise RuntimeError(result["error"])
                # Persist before publishing completion; partially written files never serve.
                (job.directory / "result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                with self._condition:
                    job.result = result
                    job.status = "completed"
            except Exception as exc:
                logging.exception("SOC %s job %s failed", job.kind, job.job_id)
                with self._condition:
                    job.error = str(exc) or "작업 중 오류가 발생했습니다."
                    job.status = "failed"
            finally:
                with self._condition:
                    job.work = None
                    session = self.sessions.get(job.session_id)
                    if session is not None:
                        session.last_seen = time.monotonic()
                    status = {"job_id": job.job_id, "kind": job.kind,
                              "status": job.status, "error": job.error}
                try:
                    (job.directory / "job.json").write_text(
                        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                except OSError:
                    logging.exception("Cannot persist job status: %s", job.job_id)

    def close(self, wait=True):
        """Stop accepting requests and finish accepted jobs before stopping the worker."""
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if wait and self._worker is not None:
            self._worker.join()
