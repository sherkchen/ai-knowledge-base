# 技能：tech-summary

## 技能描述

当需要对采集的技术内容进行深度分析总结时使用此技能。对 当前项目`knowledge/raw/` 中的原始采集条目逐条进行深度分析，提炼技术亮点，评估质量，发现共性趋势，最终输出结构化分析报告。

## 权限配置

### 允许

- **Read** — 读取 当前项目`knowledge/raw/` 目录下的原始采集数据文件
- **Grep** — 在已有分析结果中搜索，辅助去重和一致性校验
- **Glob** — 按文件名模式查找原始数据文件（如 `knowledge/raw/*.json`）
- **WebFetch** — 访问原始链接阅读项目 README 或文章全文，确保分析基于一手资料

### 禁止

- **Write** — 禁止直接写入文件，分析结果通过标准输出返回，由调用方统一落盘
- **Edit** — 禁止修改已有文件，防止意外覆盖历史数据
- **Bash** — 禁止执行任意 shell 命令，分析阶段仅做信息加工

## 执行步骤

### 第一步：读取最新采集文件

1. 使用 Glob 扫描 `knowledge/raw/` 目录，找到最新的原始采集 JSON 文件
2. 使用 Read 加载文件内容，确认条目总数和结构完整性
3. 若同时存在 GitHub Trending 和 Hacker News 两份来源数据，合并处理

### 第二步：逐条深度分析

对每一条原始条目，逐项完成以下分析，必须访问 `url`（使用 WebFetch）阅读原文以获取事实依据：

| 分析项 | 要求 |
|--------|------|
| **摘要** | 中文简洁摘要，**≤50 字**，一句话点明项目做什么、解决什么问题 |
| **技术亮点** | 2-3 条，每条用事实说话，引用 README 或文章中的具体技术点、数据或结论 |
| **评分** | 1-10 整数，附 1-2 句评分理由（评分标准见下文） |
| **标签建议** | 推荐 2-5 个标签，包含分类和领域关键词 |

**评分标准：**

| 分数 | 含义 | 判定依据 |
|------|------|----------|
| 9-10 | 改变格局 | AI/LLM/Agent 领域重大突破或范式级创新，可能影响行业方向 |
| 7-8 | 直接有帮助 | 可落地使用或直接启发当前工作，有明确的实用价值 |
| 5-6 | 值得了解 | 在 AI 领域有参考价值，但短期内不直接可用 |
| 1-4 | 可略过 | 相关性低、信息量不足或同质化严重 |

**评分约束：** 在 15 个项目中，9-10 分的条目**不超过 2 个**。宁缺毋滥，仅当有充分事实依据时才给到 9 分以上。

### 第三步：趋势发现

综合分析完所有条目后，提炼趋势洞察：

1. **共同主题** — 找出 2-4 个反复出现的技术主题或方向（如"Agent 框架多模态化""小模型端侧部署加速"），附上相关条目名称佐证
2. **新概念** — 标记 1-3 个首次出现或值得注意的新概念/新范式，说明其创新之处

### 第四步：输出分析结果 JSON

按下方格式输出完整的分析结果，写入 `knowledge/raw/github-trending-{YYYY-MM-DD}.json`

## 输出格式

```json
{
  "meta": {
    "source_file": "knowledge/raw/trending_2026-05-30.json",
    "analyzed_at": "2026-05-30T12:00:00Z",
    "total_items": 15,
    "score_distribution": {
      "9-10": 1,
      "7-8": 6,
      "5-6": 5,
      "1-4": 3
    }
  },
  "trends": {
    "common_themes": [
      {
        "theme": "Agent 框架多模态化",
        "evidence": ["aider", "gpt-pilot", "crewAI"]
      }
    ],
    "new_concepts": [
      {
        "concept": "Speculative Decoding",
        "description": "通过小模型预生成、大模型校验的方式加速推理",
        "related_items": ["llama.cpp"]
      }
    ]
  },
  "items": [
    {
      "id": "uuid",
      "title": "原始标题",
      "source": "github_trending | hacker_news",
      "source_url": "https://",
      "summary": "<=50 字中文摘要",
      "highlights": [
        "基于事实的技术亮点 1",
        "基于事实的技术亮点 2",
        "基于事实的技术亮点 3"
      ],
      "relevance_score": 8,
      "score_reason": "评分理由 1-2 句",
      "tags": ["Agent", "RAG", "tool"],
      "category": "paper | tool | news | tutorial"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `meta.source_file` | string | 分析所依据的原始数据文件路径 |
| `meta.analyzed_at` | string | 分析完成时间，ISO 8601 格式 |
| `meta.total_items` | int | 分析的条目总数 |
| `meta.score_distribution` | object | 各分数段的条目数量分布 |
| `trends.common_themes` | array | 共同主题列表，每条含主题名和相关条目佐证 |
| `trends.new_concepts` | array | 新概念列表，每条含概念名、描述和相关条目 |
| `items[].id` | string | 与原始条目 id 保持一致 |
| `items[].title` | string | 原始标题，不做修改 |
| `items[].source` | string | 数据来源：`github_trending` 或 `hacker_news` |
| `items[].source_url` | string | 原始链接 |
| `items[].summary` | string | 中文摘要，**≤50 字** |
| `items[].highlights` | string[] | 2-3 条技术亮点，基于事实，非虚构 |
| `items[].relevance_score` | int | 1-10，需遵守评分约束 |
| `items[].score_reason` | string | 评分理由 1-2 句 |
| `items[].tags` | string[] | 2-5 个标签 |
| `items[].category` | string | 严格限定：`paper` / `tool` / `news` / `tutorial` |

## 质量自查清单

在输出结果前，必须逐项确认：

- [ ] 已通过 Glob 找到最新采集文件并通过 Read 完整加载
- [ ] 对每条条目已通过 WebFetch 访问 `source_url` 阅读原文，分析结论有事实依据
- [ ] `summary` 使用**简体中文**，长度 **≤50 字**，不空洞、不虚构
- [ ] `highlights` 为 2-3 条，每条基于原文具体事实，非泛泛而谈
- [ ] `relevance_score` 为 1-10 整数，9-10 分条目不超过 2 个，每个分数附 `score_reason`
- [ ] `tags` 包含分类和领域关键词，`category` 取值严格限定在规定范围内
- [ ] `trends.common_themes` 包含 2-4 个主题，每个有条目佐证
- [ ] `trends.new_concepts` 包含 1-3 个新概念
- [ ] 所有字段齐全，无 `null` 或空值
- [ ] **绝不编造内容**——摘要、亮点和趋势发现必须基于实际阅读的原文
