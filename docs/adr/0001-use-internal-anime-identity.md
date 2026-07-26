---
status: accepted
---

# 使用独立的内部番剧身份

系统使用自身生成的 Anime ID 作为订阅、放送和资源发布的稳定身份，不把 Bangumi、AniList 或 Mikan 的任何 ID 当作主键。直接采用 Bangumi ID 虽然能减少首版映射工作，但会让 AniList 与 Mikan 数据覆盖、冲突或重复；使用 `provider + external_id` 作为业务身份又会让同一部番产生多份订阅。独立身份增加了来源映射和未解析记录的成本，但能保留各来源证据，并允许未来增加或替换数据源而不破坏用户订阅。
