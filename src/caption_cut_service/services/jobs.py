"""使用进程内状态和受控线程池执行异步 Caption 切分任务。"""

from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from caption_cut_service.schemas import CaptionCutRequest, CaptionCutTask, JobStatus
from caption_cut_service.services.caption import CaptionCutService

LOGGER = logging.getLogger(__name__)


class CaptionCutJobs:
    """在当前服务进程内保存并执行异步任务。"""

    def __init__(self, cutter: CaptionCutService, concurrency: int) -> None:
        self.cutter = cutter
        self.executor = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="caption-cut")
        self.tasks: dict[str, CaptionCutTask] = {}
        self._closed = False
        self._lock = threading.Lock()

    def submit(self, request: CaptionCutRequest) -> CaptionCutTask:
        """登记 queued 状态，并把任务交给受控线程池。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("Caption cut job service is closed")
            task_id = uuid.uuid4().hex
            task = CaptionCutTask(
                task_id=task_id,
                status=JobStatus.QUEUED,
                start_frame=request.start_frame,
                end_frame=request.end_frame,
            )
            # ponytail: 任务历史只保留到进程退出；高吞吐运行时再增加 TTL 清理。
            self.tasks[task_id] = task
            self.executor.submit(self._run, task_id, request)
            return task.model_copy(deep=True)

    def get(self, task_id: str) -> CaptionCutTask | None:
        """读取当前进程内的单个任务快照。"""
        with self._lock:
            task = self.tasks.get(task_id)
            return task.model_copy(deep=True) if task is not None else None

    def _update(self, task_id: str, **changes: object) -> None:
        """在同一把锁下替换任务快照，避免查询读到半更新状态。"""
        with self._lock:
            self.tasks[task_id] = self.tasks[task_id].model_copy(update=changes)

    def _run(self, task_id: str, request: CaptionCutRequest) -> None:
        self._update(task_id, status=JobStatus.RUNNING, error=None)
        try:
            result = self.cutter.cut(request, task_id)
        except Exception as exc:  # noqa: BLE001 - 后台异常必须转换为可查询的失败状态
            LOGGER.exception("caption_cut_failed task_id=%s error_type=%s", task_id, type(exc).__name__)
            self._update(task_id, status=JobStatus.FAILED, error=str(exc)[:1000])
            return
        self._update(
            task_id,
            status=JobStatus.SUCCEEDED,
            result=result,
        )

    def close(self) -> None:
        """停止接收任务，并等待进程内已经开始的交付完成。"""
        with self._lock:
            self._closed = True
        self.executor.shutdown(wait=True)
