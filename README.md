# CaptionCutService

基于 FastAPI 的常驻 rich caption 切分服务。调用方提交 `startframe`、`endframe`、`osspath` 后立即获得
`202 Accepted` 和 `task_id`；后台通过 OSS 内网读取源 rich caption，按 segment 边界扩展范围，重新生成当前片段的
Global task 信息，并把新 JSON 上传到：

```text
oss://ss-oss-intern/user/mengjun/CaptionCutService/
```

## 处理流程

```text
POST /caption-cuts
  -> 进程内登记 queued
  -> 202 + task_id
  -> 定位源 rich caption
  -> 通过 OSS 内网签名 URL + ffprobe 读取真实 FPS
  -> frame 区间换算为秒
  -> 选择所有相交 segment
  -> 起点前扩到首个 segment.start_time
  -> 终点后扩到末个 segment.end_time
  -> segment 时间轴重置为从 0 秒开始
  -> Ark 根据所选 segments 重写 task.command/task.step/outcome
  -> 保留源 scene 与 task.domain/type，拼接所选 segments
  -> 本机原子写入并上传固定 OSS 前缀
  -> GET /caption-cuts/{task_id} 返回结果地址和实际边界
```

`startframe` 包含，`endframe` 按右开区间处理，即 `[startframe, endframe)`。segment 使用区间相交规则，边界
刚好相等时不会额外包含相邻 segment。输出 segments 保留原有内容，只调整 `start_time/end_time` 使首段从 0 开始。

`osspath` 支持三种形式：

- 源视频 OSS URI：优先寻找同目录 `<视频文件名 stem>_rich_caption.json`，再按 `video_oss_uri` 匹配。
- rich caption JSON URI：直接读取，但 JSON 必须包含 `video_oss_uri`，用于探测真实 FPS。
- OSS 目录 URI：目录中只能有一个 rich caption 候选，且该 JSON 必须包含 `video_oss_uri`。

## API

提交任务：

```bash
curl -i -X POST http://127.0.0.1:8010/caption-cuts \
  -H 'Content-Type: application/json' \
  -d '{
    "startframe": 300,
    "endframe": 900,
    "osspath": "oss://bucket/path/video.mp4"
  }'
```

响应：

```json
{
  "task_id": "7fdb...",
  "status": "queued",
  "status_url": "http://127.0.0.1:8010/caption-cuts/7fdb..."
}
```

查询任务：

```bash
curl http://127.0.0.1:8010/caption-cuts/7fdb...
```

成功后的 `result` 包含 `result_oss_uri`、源 caption/video URI、源 FPS、请求帧范围、扩展后的实际帧范围和
segment 数量。失败后的 `error` 保存可对外定位的错误，不包含密钥、Token 或 OSS 签名 URL。

## 配置与启动

本地开发会优先读取本项目 `.env`；本项目没有 `.env` 时，会读取同级 `VideoCaptionService/.env` 中已有的
OSS 与 Ark 凭证。部署环境应直接注入 `.env.example` 中的变量，不依赖同级目录。

```bash
make install-dev
make check
caption-cut-api
```

也可以使用 Docker：

```bash
docker compose up --build -d
```

服务地址为 `http://127.0.0.1:8010`，OpenAPI 文档位于 `/docs`。任务状态只保存在当前服务进程内，重启后
原 task ID 不再可查询；上传前的本机暂存结果保存在 `data/tasks/`。
