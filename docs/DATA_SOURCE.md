# 数据源接口

本项目接收每日快照，输出周/月报告。尚未内置可直接抓取真实微博的采集器。

## JSON 格式

完整可运行样例见 [examples/snapshots.json](../examples/snapshots.json)。

```json
{
  "schema_version": 1,
  "is_demo": false,
  "snapshots": [
    {
      "observed_at": "2026-09-01T23:30:00+08:00",
      "posts": [
        {
          "id": "post-id",
          "rank": 1,
          "created_at": "2026-09-01T10:00:00+08:00",
          "text": "事件原文",
          "event_id": "stable-event-id",
          "event_title": "事件名称",
          "source_url": "https://weibo.com/",
          "engagement": {"likes": 200, "comments": 100, "reposts": 50},
          "comments": [
            {
              "id": "comment-id",
              "text": "这件事情很暖心，支持。",
              "created_at": "2026-09-01T10:10:00+08:00",
              "engagement": {"likes": 88}
            }
          ]
        }
      ]
    }
  ]
}
```

- 每天一个快照，`observed_at` 是实际采样时间；同一天的完全相同快照自动去重，冲突快照拒绝导入。
- 数据源应每天固定时间保存 Top 30 微博和 Top 100 高赞评论，或提供能够查询上述历史快照的服务。
- `created_at` 是发布时刻，可以早于统计窗口，但不能晚于采样时间；评论不能早于微博发布。
- 不带时区的时间按北京时间处理，UTC 等带时区时间会转换至北京时间。
- `rank` 从 1 开始，互动计数必须是非负整数；空评论被跳过。
- `event_id`、`event_title`、`source_url`、`topics` 和互动计数可省略。未提供事件 ID 时按单条微博聚合。事件 ID 应由数据源编辑或事件聚类流程提供。
- 不需要用户名、用户主页或用户画像。公开报告只包含事件摘要、情绪分布、样本统计与微博来源链接。
- `is_demo` 必须显式填写；演示与真实快照不能混合。

## HTTP 归档适配器

设置环境变量 `DATA_SOURCE_URL`，可选 `DATA_SOURCE_TOKEN`（Bearer 鉴权）。

```console
weibo-mood-radar sync --output data/snapshots/provider.json
weibo-mood-radar publish --input data/snapshots/provider.json
```

程序请求 `GET <DATA_SOURCE_URL>?start=YYYY-MM-DD&end=YYYY-MM-DD`，已有查询参数会保留。`start` 为上月 1 日，`end` 为运行当天北京时间日期，区间左闭右开。响应为上述 JSON，需要返回区间内的每日快照，最大 128 MiB；HTTPS 必需，重定向不会携带密钥继续请求。

此接口是本项目定义的数据适配协议，不是微博官方 API。接入已有服务时，请在服务端转换为该格式。仅有当前榜单的接口不能满足历史周报需求。

源文件写入被 Git 忽略的 `data/snapshots/`。每次下载会原子替换同名快照文件，聚合成功后只发布报告。API 返回部分天数时报告明确标为缺失；拒绝用较少覆盖天数的结果覆盖已有较完整报告。

## 本地导入

可将不同日期的 JSON 放进 `data/snapshots/`，运行 `publish --input data/snapshots`。该路径不会上传到 GitHub，自动任务需要通过服务端归档接口再次获得历史快照。
