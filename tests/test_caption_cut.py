"""验证 segment 边界扩展、时间重置与最终结构。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from caption_cut_service.config import Settings
from caption_cut_service.schemas import CaptionCutRequest, CaptionCutResult, JobStatus
from caption_cut_service.services.caption import CaptionCutService, select_segments
from caption_cut_service.services.jobs import CaptionCutJobs
from caption_cut_service.storage.oss import OssStorage, _bucket


def _segments() -> list[dict[str, Any]]:
    return [
        {"start_time": 0.0, "end_time": 2.0, "caption": {"overall": {"en": "A", "zh": "甲"}}},
        {"start_time": 2.0, "end_time": 4.0, "caption": {"overall": {"en": "B", "zh": "乙"}}},
        {"start_time": 4.0, "end_time": 6.0, "caption": {"overall": {"en": "C", "zh": "丙"}}},
    ]


class FakeStorage:
    """记录上传内容的最小 OSS 测试桩。"""

    def __init__(self) -> None:
        self.uploaded: dict[str, Any] | None = None

    def object_exists(self, uri: str) -> bool:
        return True

    def read_json(self, uri: str) -> dict[str, Any]:
        return {
            "video_oss_uri": "oss://source/path/video.mp4",
            "scene": {"domain": "household", "scenario": "kitchen"},
            "task": {
                "command": {"en": "Original", "zh": "原任务"},
                "step": {"en": "Original step", "zh": "原步骤"},
                "domain": "food",
                "type": "food_drink_preparation",
            },
            "segments": _segments(),
        }

    def list_rich_captions(self, uri: str) -> list[str]:
        return []

    def probe_video_fps(self, video_uri: str) -> float:
        return 10.0

    def upload_json(self, value: dict[str, Any], uri: str, staging_path: Path) -> str:
        self.uploaded = value
        return uri


class CaptionCutTest(unittest.TestCase):
    """覆盖区间语义和对外结果元数据。"""

    def test_equal_boundaries_do_not_select_adjacent_segments(self) -> None:
        selected, expanded_start, expanded_end = select_segments(
            _segments(),
            requested_start=2.0,
            requested_end=4.0,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual((expanded_start, expanded_end), (2.0, 4.0))
        self.assertEqual((selected[0]["start_time"], selected[0]["end_time"]), (0.0, 2.0))

    def test_partial_overlap_expands_to_complete_segments(self) -> None:
        selected, expanded_start, expanded_end = select_segments(
            _segments(),
            requested_start=1.5,
            requested_end=4.5,
        )

        self.assertEqual(len(selected), 3)
        self.assertEqual((expanded_start, expanded_end), (0.0, 6.0))
        self.assertEqual(selected[-1]["end_time"], 6.0)

    def test_service_rebuilds_global_and_uploads_fixed_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), data_dir=Path(directory))
            storage = FakeStorage()

            def summarize(source_task: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
                self.assertEqual(len(segments), 1)
                return {
                    "command": {"en": "Do B.", "zh": "执行乙。"},
                    "step": {"en": "Complete B.", "zh": "完成乙。"},
                    "outcome": "success_without_recovery",
                }

            service = CaptionCutService(settings, storage, summarize)
            result = service.cut(
                CaptionCutRequest(
                    start_frame=20,
                    end_frame=40,
                    source_oss_uri="oss://source/path/video.mp4",
                ),
                "task123",
            )

        self.assertEqual(result.expanded_start_frame, 20)
        self.assertEqual(result.expanded_end_frame, 40)
        self.assertEqual(result.segment_count, 1)
        assert storage.uploaded is not None
        self.assertEqual(set(storage.uploaded), {"scene", "task", "segments"})
        self.assertEqual(storage.uploaded["task"]["type"], "food_drink_preparation")
        self.assertEqual(storage.uploaded["segments"][0]["start_time"], 0.0)

    def test_video_fallback_listing_is_limited_to_source_stem(self) -> None:
        settings = Settings(oss_access_key_id="key", oss_access_key_secret="secret")
        bucket = MagicMock()
        item = MagicMock(key="path/video_rich_caption.json")
        _bucket.cache_clear()
        try:
            with (
                patch("caption_cut_service.storage.oss.oss2.Bucket", return_value=bucket) as bucket_factory,
                patch("caption_cut_service.storage.oss.oss2.ObjectIteratorV2", return_value=[item]) as iterator,
            ):
                result = OssStorage(settings).list_rich_captions("oss://source/path/video.mp4")
        finally:
            _bucket.cache_clear()

        self.assertEqual(result, ["oss://source/path/video_rich_caption.json"])
        self.assertEqual(iterator.call_args.kwargs["prefix"], "path/video")
        self.assertEqual(bucket_factory.call_args.kwargs["connect_timeout"], 15)

    def test_job_state_is_process_local(self) -> None:
        cutter = MagicMock()
        cutter.cut.return_value = CaptionCutResult(
            result_oss_uri="oss://result/caption.json",
            source_caption_oss_uri="oss://source/video_rich_caption.json",
            source_video_oss_uri="oss://source/video.mp4",
            source_fps=25.0,
            requested_start_frame=1,
            requested_end_frame=2,
            expanded_start_frame=0,
            expanded_end_frame=25,
            segment_count=1,
        )
        request = CaptionCutRequest(
            start_frame=1,
            end_frame=2,
            source_oss_uri="oss://source/video.mp4",
        )
        jobs = CaptionCutJobs(cutter, concurrency=1)

        submitted = jobs.submit(request)
        jobs.close()
        completed = jobs.get(submitted.task_id)

        self.assertEqual(completed.status, JobStatus.SUCCEEDED)
        self.assertEqual(completed.result.result_oss_uri, "oss://result/caption.json")
        restarted = CaptionCutJobs(cutter, concurrency=1)
        try:
            self.assertIsNone(restarted.get(submitted.task_id))
        finally:
            restarted.close()


if __name__ == "__main__":
    unittest.main()
