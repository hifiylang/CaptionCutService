# CaptionCutService 开发规范

## 项目边界

- FastAPI 唯一入口为 `caption_cut_service.main:app`，路由只负责协议解析和 HTTP 状态码。
- `services/caption.py` 负责同步 Caption 切分编排，接口等待上传完成后直接返回结果。
- OSS SDK 调用只允许出现在 `storage/oss.py`；结果只允许写入
  `oss://ss-oss-intern/user/mengjun/CaptionCutService/`。
- 凭证只从环境变量或未提交的 `.env` 读取，不得写入源码、日志、响应和提交记录。
- 控制台日志使用单行 JSON；切分成功和失败事件分别写入 `data/logs/success/` 与 `data/logs/failure/`。
- 每次切分使用 `X-Request-ID` 关联日志和响应，日志字段不得包含 AK/SK、Token 或 Authorization。

## Caption 规则

- 外部帧范围为 `[start_frame, end_frame)`，与 Caption 的 1 FPS 时间轴直接对应，不探测源视频 FPS。
- segment 采用区间相交规则；输出范围前扩到首段起点、后扩到末段终点。
- 输出 segments 保留源字段，只把时间重置到首段从 0 秒开始。
- Global 只重新生成 `task.command`、`task.step` 和可选 `task.outcome`；`scene`、`task.domain/type` 保留源值。
- 最终 OSS JSON 只包含 `scene`、`task`、`segments`，来源与切分范围只保存在同步接口响应中。

## 编码与验证

- 核心 Python 模块使用中文模块级 docstring；公开类和关键方法使用准确类型注解与中文 docstring。
- 注释解释 OSS 安全边界和时间轴语义，避免逐行翻译代码。
- 修改 Python 代码后至少执行 `make check` 和 `git diff --check`（若目录已初始化 Git）。
- 测试不得访问真实 OSS、Ark 或生产数据。
