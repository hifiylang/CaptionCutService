"""验证 FastAPI 对外协议可以稳定生成。"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from caption_cut_service.main import app
from caption_cut_service.schemas import CaptionCutResult


class ApiContractTest(unittest.TestCase):
    """检查同步切分端点的 OpenAPI 协议。"""

    def test_openapi_contains_sync_caption_cut_route(self) -> None:
        openapi = app.openapi()
        paths = openapi["paths"]

        self.assertEqual(
            paths["/api/caption-cuts"]["post"]["responses"].get("200", {}).get("description"),
            "Successful Response",
        )
        self.assertNotIn("/api/caption-cuts/{task_id}", paths)
        request_schema = openapi["components"]["schemas"]["CaptionCutRequest"]
        self.assertEqual(
            set(request_schema["required"]),
            {"start_frame", "end_frame", "source_oss_uri"},
        )
        response_schema = openapi["components"]["schemas"]["CaptionCutResponse"]
        self.assertEqual(
            set(response_schema["properties"]),
            {"start_frame", "end_frame", "result"},
        )
        result_schema = openapi["components"]["schemas"]["CaptionCutResult"]
        self.assertEqual(
            set(result_schema["properties"]),
            {"source_video_oss_uri", "result_oss_uri", "start_frame", "end_frame"},
        )
        self.assertNotIn("CaptionCutTask", openapi["components"]["schemas"])

    def test_post_waits_for_service_and_returns_result(self) -> None:
        service = MagicMock()
        service.cut.return_value = CaptionCutResult(
            source_video_oss_uri="oss://source/video.mp4",
            result_oss_uri="oss://result/video_rich_caption_1_2.json",
            start_frame=0,
            end_frame=3,
        )
        app.state.caption_cut_service = service

        with TestClient(app, raise_server_exceptions=True) as client:
            app.state.caption_cut_service = service
            response = client.post(
                "/api/caption-cuts",
                json={
                    "start_frame": 1,
                    "end_frame": 2,
                    "source_oss_uri": "oss://source/video.mp4",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "start_frame": 1,
                "end_frame": 2,
                "result": {
                    "source_video_oss_uri": "oss://source/video.mp4",
                    "result_oss_uri": "oss://result/video_rich_caption_1_2.json",
                    "start_frame": 0,
                    "end_frame": 3,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
