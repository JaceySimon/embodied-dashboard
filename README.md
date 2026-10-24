# Embodied Dashboard

> 具身智能 / VLA 方向的动态知识导航看板
> 帮你少读 80% 垃圾，5 分钟看完本周关键进展

## 这是什么？

一个面向具身智能研究者的**事件级**信息聚合器——把散在 arXiv、公司/实验室博客、垂直媒体、GitHub、Hugging Face 上的**同一件事**聚合成一条（论文 + 官方公告 + 媒体报道 + 开源代码 + 模型权重），按重要性排序，并用 LLM 生成带引用的方向综述，让你 5 分钟看完本周领域发生了什么。

## 为什么比搜索引擎 / arXiv 列表更好？

| 痛点 | 搜索引擎 / arXiv | Embodied Dashboard |
|---|---|---|
| 信息分散 | 论文、博客、媒体、代码分散在各平台 | 同一事件跨源聚合，一处看全 |
| 工业界信号 | 公司 tech report 不易发现 | 一手官网 + 博客 + 开源仓库直接收录 |
| 选择困难 | 几千篇论文无从下手 | 本周必看 + 重要性评分 + 真机/开源标记 |
| 缺总结 | 要自己读 | AI 方向综述（VLA/世界模型/Sim2Real/策略学习），带可点击引用 |
| 二次搬运 | 大量二手转述 | 白名单一手源，聚合时一手源优先 |
| 重复刷屏 | 同一进展多平台各发一遍 | 事件去重，只看一次 |

## 核心功能

### 信息聚合
- **跨源事件专区**：把同一进展的论文、官方博客、媒体报道、开源仓库、模型权重聚合成一张事件卡，多源可分别跳转
- **事件 AI 解读**：每个跨源事件自动生成"30 秒看懂"——一句话定位 + 方法/看点（可展开），只基于多源材料、不编造
- **学术 + 工业界 + 开源 + 模型**：arXiv 分层召回、公司/实验室官网、垂直媒体 RSS、GitHub 组织新仓库与框架版本发布、Hugging Face 机构模型权重（白名单制，过滤个人 checkpoint 噪声）
- **AI 方向综述**：按 VLA / 世界模型 / Sim2Real / 策略学习 4 个方向，取近 90 天 Top 论文，LLM 生成技术路线与趋势判断，引用可点击直达原文
- **AI 本周导读**：顶部执行摘要，30 秒给出本周态势、3 条跨方向必看（附 why、可点击）和一句趋势判断，paper_id 白名单校验防幻觉

### 发现与阅读
- **本周必看**：学术 Top7 + 工业界一手 Top3，按重要性评分排序
- **信息源分级**：L0 一手锚点（arXiv/官方/GitHub）→ L1 深度博客 → L2 媒体 → L3 社交
- **领域脉搏**：近 7 天方向热度 + 近 30 天机构活跃榜，点击条形下钻；另附近 12 周方向趋势折线图（图例可点击切换，一眼看出哪个方向在升温/降温），一眼看清领域在往哪走、谁在发力
- **智能资源直达**：自动从论文 comment / 摘要提取代码仓库（GitHub）、项目主页、数据集链接，彩色徽章一键直达，不用再翻论文找
- **智能搜索**：多关键词 AND 匹配、多词高亮、关键词命中标签；AND 无结果自动降级 OR 并提示，避免"一搜就空"；配合标签/时间/真机/开源筛选与 `/` 快捷键

### 订阅与个人工具
- **RSS 订阅**：站点输出主 feed `feed.xml`（事件 + 精选），并提供方向级 feed：`feed-vla.xml`、`feed-world-model.xml`、`feed-industry.xml`；头部"RSS 订阅 ▾"按需订阅，只收自己关心的方向
- **自上次访问以来**：回访时自动提示新增事件与更新数
- **已读 / 未读追踪**：点原文即自动标记已读（淡化），可一键只看未读，持续追踪不重不漏
- **收藏**：本地保存、刷新不丢失、一键导出 Markdown
- **相关论文推荐**：基于标签相似度
- **每周简报**：自动生成 Markdown 周报
- **死链检测**：`linkcheck` 批量校验链接，保证跳转不出错

### 数据质量
- 分层 arXiv 召回（避免大查询被截断），型号指纹强匹配做事件聚合
- 规则打标 + DeepSeek LLM 打标 / 摘要
- 自动去噪（过滤不相关论文）、去重（URL 规范化 + 标题哈希 + 相似度）
- 采集器带重试与缓存；一键 `health` / `quality` 自检

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（可选：AI 摘要 / 综述、X、GitHub 提高配额）
cp .env.example .env

# 3. 一键运行（推荐）
python run.py all
```

打开 `output/index.html` 即可使用。

## 常用命令

```bash
python run.py collect          # 采集最新数据（RSS/HTML/GitHub/X）
python run.py backfill 90      # 分层爬取过去 90 天 arXiv
python run.py merge            # 合并各源到 data/combined.json
python run.py html             # 生成 HTML + RSS feed
python run.py weekly           # 生成 Markdown 周报
python run.py summaries 20     # 给前 N 篇生成 AI 摘要
python run.py linkcheck all    # 校验所有链接
python run.py health           # 健康检查（文件、数量、覆盖）
python run.py quality          # 数据质量抽检
python run.py all              # 完整 pipeline
```

AI 方向综述单独生成：

```bash
python -m pipeline.gen_briefing
```

## 信息源分级

| 级别 | 来源 | 特点 |
|---|---|---|
| L0 | arXiv、公司官网、官方 GitHub | 一手锚点，最权威 |
| L1 | DeepMind / NVIDIA / BAIR 等研究博客 | 深度技术解读 |
| L2 | IEEE Spectrum、TechCrunch、量子位等媒体 | 行业信号、发布会报道 |
| L3 | X/Twitter（需 API） | 最快，需筛选 |

> 原则：白名单一手源优先；同一事件聚合时按 L0 → L3 排序，避免二手搬运淹没一手信息。

## 配置信息源

所有信息源在 `config/sources.yaml` 中配置（白名单制，不硬编码）：

- `html_companies`：无 RSS 的公司官网，支持 `detail / list / nuxt_payload / json_api` 四种抓取模式
- `rss`：博客与媒体 RSS
- `l0.github`：追踪的 GitHub 组织（新开源仓库 + 高 star 项目动态）与核心框架 release
- `l0.huggingface`：追踪的 HF 机构模型（LeRobot/π0、NVIDIA GR00T 等）；国内默认走 `hf-mirror.com` 镜像，只收白名单机构、排除个人 checkpoint/数据导出
- `arxiv`：分层 query 组 + 定向公司/系统名

## 项目结构

```
embodied-dashboard/
├── run.py                    # 统一入口
├── generate_html.py          # 静态 HTML + RSS feed 生成器
├── utils.py                  # 重试、缓存、日志
├── collectors/
│   ├── arxiv_collector.py        # 分层 arXiv 召回
│   ├── rss_collector.py          # 博客/媒体 RSS
│   ├── company_html_collector.py # 无 RSS 官网（4 种抓取模式）
│   ├── github_collector.py       # GitHub 开源仓库与 release
│   ├── huggingface_collector.py  # Hugging Face 机构模型权重
│   └── x_api_collector.py        # X/Twitter（需 Bearer Token）
├── pipeline/
│   ├── run_daily.py
│   ├── backfill.py
│   ├── merge_sources.py
│   ├── event_merger.py       # 跨源事件聚合（型号指纹 + 相似度）
│   ├── tagger.py / llm_tagger.py
│   ├── gen_briefing.py       # AI 方向综述
│   ├── gen_summaries.py      # AI 摘要
│   ├── weekly_report.py
│   ├── link_check.py
│   ├── data_quality.py
│   └── health_check.py
├── models/
├── config/sources.yaml
├── docs/
└── output/
    ├── index.html
    ├── feed.xml                 # 主 feed（事件+精选）
    ├── feed-vla.xml             # 方向级 feed
    ├── feed-world-model.xml
    ├── feed-industry.xml
    └── weekly_*.md
```

## 环境变量

| 变量 | 用途 | 必需 |
|---|---|---|
| `LLM_API_KEY` | DeepSeek 打标 / 摘要 / 方向综述 | 可选 |
| `GITHUB_TOKEN` | GitHub 采集提高配额（未认证 60 次/小时，有 token 5000 次/小时，无需勾选权限） | 可选 |
| `HF_TOKEN` | Hugging Face 采集提高配额（可选，无 token 也能采白名单机构） | 可选 |
| `X_BEARER_TOKEN` | X/Twitter 采集 | 可选 |

## 技术栈

- **采集**：Python + requests + feedparser + arXiv API + GitHub API
- **处理**：规则打标 + DeepSeek LLM；事件聚合（型号指纹 + 标题相似度）
- **前端**：原生 HTML/JS/CSS，零依赖单文件，可直接 GitHub Pages 托管
- **自动化**：GitHub Actions 每日定时采集、生成、部署

## 版本路线

- [x] v0.x – v1.x：arXiv 采集、事件聚合、LLM 打标、收藏/搜索/筛选、周报
- [x] v2.0：信息源分级 + 工业界源
- [x] v2.1：arXiv 分层召回 + 强型号事件聚合
- [x] v2.2：跨源事件专区（论文 + 官方 + 媒体）
- [x] v2.3：RSS 订阅 + 自上次访问提示
- [x] v2.4：AI 方向综述（带引用）
- [x] v2.5：GitHub 开源动态（新仓库 + 框架 release）
- [x] v2.6：Hugging Face 模型权重（白名单机构 + 镜像，参与事件聚合）
- [x] v2.7：事件 AI 解读（30 秒看懂跨源事件）
- [x] v2.8：领域脉搏（方向热度 + 机构活跃榜）
- [x] v2.9：已读 / 未读追踪（持续回访不重不漏）
- [x] v3.0：智能资源直达（代码 / 项目主页 / 数据集自动提取）
- [x] v3.1：AI 本周导读（顶部执行摘要，30 秒抓住 3 件必看）
- [x] v3.2：修复公司博客文章 id 跨进程随机（事件解读缓存/已读不再失效）
- [x] v3.3：方向级 RSS（VLA / 世界模型 / 工业界，精准订阅）
- [x] v3.4：相关推荐升级（同事件优先 + 标题/标签综合打分）
- [x] v3.5：近 12 周方向趋势图（升温/降温一眼可见）
- [x] v3.6：智能搜索（多词 AND + 高亮，无结果自动降级 OR）
- [ ] 后续：X 接入、LLM 语义归并、HF 数据集采集、更聪明的个性化推送

## Open-Core 策略

**开源版（MIT）**：核心爬虫、事件聚合、规则打标、静态看板、AI 摘要/综述、RSS
**托管版（未来）**：语义搜索、监控告警、团队协作、私有源

## License

MIT
