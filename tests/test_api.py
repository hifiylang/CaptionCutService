"""验证 FastAPI 对外协议可以稳定生成。"""

from __future__ import annotations

import unittest

from caption_cut_service.main import app


class ApiContractTest(unittest.TestCase):
    """检查提交与查询端点的 OpenAPI 协议。"""

    def test_openapi_contains_async_caption_cut_routes(self) -> None:
        openapi = app.openapi()
        paths = openapi["paths"]

        self.assertEqual(
            paths["/api/caption-cuts"]["post"]["responses"].get("202", {}).get("description"),
            "Successful Response",
        )
        self.assertIn("get", paths["/api/caption-cuts/{task_id}"])
        request_schema = openapi["components"]["schemas"]["CaptionCutRequest"]
        self.assertEqual(
            set(request_schema["required"]),
            {"start_frame", "end_frame", "source_oss_uri"},
        )
        submission_schema = openapi["components"]["schemas"]["CaptionCutSubmission"]
        self.assertEqual(
            set(submission_schema["properties"]),
            {"task_id", "status", "start_frame", "end_frame"},
        )
        task_schema = openapi["components"]["schemas"]["CaptionCutTask"]
        self.assertEqual(
            set(task_schema["properties"]),
            {"task_id", "status", "start_frame", "end_frame", "result", "error"},
        )
        result_schema = openapi["components"]["schemas"]["CaptionCutResult"]
        self.assertEqual(
            set(result_schema["properties"]),
            {"source_video_oss_uri", "result_oss_uri", "start_frame", "end_frame"},
        )
        self.assertNotIn("/api/v1/caption-cuts", paths)


if __name__ == "__main__":
    unittest.main()
