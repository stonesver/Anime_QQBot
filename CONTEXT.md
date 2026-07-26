# 群聊追番

本上下文描述群成员通过聊天机器人查询番剧、建立追番订阅，并接收预计放送和资源发布提醒时使用的统一语言。

## 番剧目录

**Anime（番剧）**:
系统内部唯一的一部动画作品；它独立于任何外部数据源的条目身份。
_Avoid_: Subject、Media、Bangumi 条目

**External Entry（外部条目）**:
Bangumi、AniList 或 Mikan 对一部作品的来源侧记录；在确认关联前不等同于 Anime。
_Avoid_: Anime、统一条目

**Source Link（来源映射）**:
一个 External Entry 与一个 Anime 之间经过确认或等待确认的关系。
_Avoid_: 标题猜测、ID 替换

**Airing Occurrence（预计放送）**:
某部 Anime 的某一集在数据源记录的预计放送日期或时刻；它不表示字幕或资源已经发布。
_Avoid_: 更新、上线、出资源

**Resource Release（资源发布）**:
Mikan 记录的一次字幕或压制资源发布，包含字幕组、语言、规格和发布时间等信息。
_Avoid_: Airing Occurrence、开播

## 追番与提醒

**Follow Subscription（追番订阅）**:
某位 QQ 用户在某个群中表达的追踪一部 Anime 的意愿；它不跨群共享。
_Avoid_: 全局订阅、Mikan 订阅

**Resource Filter（资源筛选）**:
Follow Subscription 对 Resource Release 的语言、字幕组和分辨率偏好。
_Avoid_: 下载规则

**Release Batch（资源聚合）**:
同一部 Anime、同一集在一个短时间窗口内发现的一组 Resource Release。
_Avoid_: 单条 RSS、下载队列

**Notification Job（通知任务）**:
系统准备向一个群发送一次开播提醒或资源聚合提醒的持久化意图。
_Avoid_: 定时器、即时发送

**Delivery Attempt（投递尝试）**:
系统为一个 Notification Job 实际请求聊天平台发送消息的一次结果记录。
_Avoid_: Notification Job、提醒
