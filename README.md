# CaptionCutService

基于 FastAPI 的常驻 rich caption 切分服务。调用方提交 `start_frame`、`end_frame`、`source_oss_uri` 后，接口等待
OSS 内网读取、segment 边界匹配、Global task 重建与结果上传全部完成，再直接返回结果：

```text
oss://ss-oss-intern/user/mengjun/CaptionCutService/
```

## 处理流程

```text
POST /api/caption-cuts
  -> 定位源 rich caption
  -> frame 区间直接映射到 Caption 的 1 FPS 时间轴
  -> 起点和终点在 1.5 秒内吸附到最近 segment 边界
  -> 超过 1.5 秒时保留请求边界并裁剪首尾 segment
  -> segment 时间轴按最终起点重置
  -> Ark 根据所选 segments 重写 task.command/task.step/outcome
  -> 保留源 scene 与 task.domain/type，拼接所选 segments
  -> 本机原子写入并上传固定 OSS 前缀
  -> 200 直接返回结果地址和实际切分范围
```

`start_frame` 包含，`end_frame` 按右开区间处理，即 `[start_frame, end_frame)`；接口按 Caption 的 1 FPS
时间轴直接匹配，不探测源视频 FPS。每个端点只在距离最近 segment 边界不超过 1.5 秒时吸附，边界可能位于端点之前或之后；
超过阈值或与两个边界等距时不移动。segment 使用区间相交规则，边界刚好相等时不会额外包含相邻 segment，输出只调整首尾时间并按最终起点重置。

`source_oss_uri` 支持三种形式：

- 源视频 OSS URI：优先寻找同目录 `<视频文件名 stem>_rich_caption.json`，再按 `video_oss_uri` 匹配。
- rich caption JSON URI：直接读取，但 JSON 必须包含 `video_oss_uri`，用于记录来源。
- OSS 目录 URI：目录中只能有一个 rich caption 候选，且该 JSON 必须包含 `video_oss_uri`。

## API

同步切分：

```bash
curl -i -X POST http://127.0.0.1:8010/api/caption-cuts \
  -H 'Content-Type: application/json' \
  -d '{
    "start_frame": 300,
    "end_frame": 900,
    "source_oss_uri": "oss://bucket/path/video.mp4"
  }'
```

处理完成后的响应：

```json
{
  "start_frame": 300,
  "end_frame": 900,
  "result": {
    "source_video_oss_uri": "oss://bucket/path/video.mp4",
    "result_oss_uri": "oss://ss-oss-intern/user/mengjun/CaptionCutService/video_rich_caption_300_900.json",
    "start_frame": 299,
    "end_frame": 901
  }
}
```

外层 `start_frame/end_frame` 原样返回请求值，`result.start_frame/end_frame` 是实际截取值。结果文件名固定为
`<源视频名>_rich_caption_<请求 start_frame>_<请求 end_frame>.json`。输入或匹配错误返回 `400`，外部服务错误返回 `502`。
接口接受或生成 `X-Request-ID`，并在成功和错误响应头中原样返回，便于关联日志。

## 配置与启动

服务只读取本项目 `.env`，不再依赖同级目录。`.env.example` 包含服务地址、日志、OSS 和 Ark 等部署环境配置；
真实 `.env` 已写入本项目并由 Git 忽略，部署时也可以通过系统环境变量覆盖。

```bash
make install-dev
make check
caption-cut-api
```

也可以使用 Docker：

```bash
docker compose up --build -d
```

服务地址为 `http://127.0.0.1:8010`，OpenAPI 文档位于 `/docs`。上传过程使用 `data/staging/` 临时暂存，完成后自动清理。

## 日志

控制台统一输出单行 JSON。每次切分记录请求 ID、请求与实际帧范围、耗时、HTTP 状态和结果 OSS 地址，凭证字段自动脱敏。
业务终态日志按 UTC 每日轮转并保留 30 份：

- 成功：`data/logs/success/caption-cut-success.log`
- 失败：`data/logs/failure/caption-cut-failure.log`
