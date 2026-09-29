"""验证 FastAPI 对外协议可以稳定生成。"""

from __future__ import annotations

import unittest

from caption_cut_service.main import app


class ApiContractTest(unittest.TestCase):
    """检查提交与查询端点的 OpenAPI 协议。"""

    def test_openapi_contains_async_caption_cut_routes(self) -> None:
        paths = app.openapi()["paths"]

        self.assertEqual(
            paths["/caption-cuts"]["post"]["responses"].get("202", {}).get("description"), "Successful Response"
        )
        self.assertIn("get", paths["/caption-cuts/{task_id}"])


if __name__ == "__main__":
    unittest.main()
