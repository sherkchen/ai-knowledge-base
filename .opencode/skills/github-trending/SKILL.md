---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# GitHub Trending 采集技能

## 使用场景

当需要获取 GitHub 上 AI/LLM/Agent 领域的热门开源项目时，使用此技能自动采集、过滤、去重、摘要并输出结构化 JSON 数据。

## 执行步骤

### 1. 搜索热门仓库

通过 GitHub Search API 搜索近期创建或活跃的 AI/LLM/Agent 相关仓库。

```
GET https://api.github.com/search/repositories?q=topic:llm+topic:agent+topic:ai&sort=stars&order=desc&per_page=100
```

### 2. 提取仓库信息

从 API 响应中提取每个仓库的关键字段：名称、Star 数、描述、编程语言、话题标签。

### 3. 过滤

- **纳入**：与 AI、LLM、Agent、RAG、ML/DL 直接相关的项目
- **排除**：
  - `awesome-*` 开头的 Awesome 列表型仓库
  - 纯教程类仓库（如教程合集、课程笔记）
  - 与 AI 无关的通用工具/框架

### 4. 去重

多次搜索或跨关键词搜索可能产生重复结果，以仓库全名（`owner/repo`）为唯一标识，仅保留一条记录。

### 5. 撰写一句话中文摘要

按公式撰写：**做什么 + 为什么值得关注**，控制在 50 字以内。

### 6. 排序取 Top 15

按 Star 数降序排列，截取前 15 个项目。

### 7. 输出 JSON

将结果写入 当前项目的 `knowledge/raw/github-trending-YYYY-MM-DD.json`，文件名为当前日期。

## 注意事项

- 遵守 GitHub API 速率限制，必要时使用 Token 提高限额
- 过滤逻辑需严谨，避免漏掉新兴但尚未打标签的项目（可结合仓库描述和 README 判断）
- 去重时名称匹配需不区分大小写
- 摘要必须为中文，且避免机械翻译，应提炼核心亮点

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-05-30T00:00:00Z",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "一个基于 LLM 的自动化测试框架，支持自然语言编写测试用例并自动生成代码执行，大幅降低测试编写门槛",
      "topic": ["AI", "Testing", "LLM"],
      "create_at": "2026-05-10T12:00:00Z",
      "push_at": "2026-05-29T18:30:00Z",
      "stars": 5280
    }
  ]
}
```
