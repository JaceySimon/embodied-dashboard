# Embodied Dashboard

> 具身智能 / VLA 方向的动态知识导航看板
> 帮你少读 80% 垃圾，5 分钟看完本周关键进展

## 这是什么？

一个面向具身智能研究者的**事件级**信息聚合器——把散在 arXiv、公司博客、X 线程、GitHub 上的同一件事聚合成一条，按重要性排序，让你 5 分钟看完本周领域发生了什么。

## 核心功能

### 信息获取
- **本周必看 10 篇**：按重要性自动排序（标签权重 + 真机 + 开源 + 合作作者）
- **信息源分级**：L0 学术（arXiv） / L1 工业界研究博客 / L2 公司动态 / L3 社交媒体
- **聚焦三个方向**：VLA / 世界模型 / 仿真器

### 筛选与搜索
- 全文搜索（标题、作者、摘要），搜索关键词高亮
- 按标签筛选（VLA / 世界模型 / Sim2Real / Diffusion Policy）
- 按时间筛选（今天 / 本周 / 本月 / 全部）
- 按是否有真机实验 / 是否开源筛选
- 快捷键：按 `/` 快速搜索，按 `ESC` 关闭弹窗

### 个人工具
- **收藏**：点击 ☆ 收藏，本地保存，刷新不丢失
- **相关论文推荐**：基于标签相似度自动推荐
- **导出收藏**：一键导出 Markdown 格式
- **每周简报**：自动生成 Markdown 周报，可用于邮件/微信推送

### 数据质量
- 规则打标 + DeepSeek LLM 打标
- 自动去噪（过滤不相关论文）
- 自动去重（URL + 标题相似度）
- 采集器带重试和缓存

## 和 Awesome List 有什么区别？

| | Awesome List | arXiv 搜索 | Embodied Dashboard |
|---|---|---|---|
| 聚焦 | 全领域 | 全领域 | 只收 VLA/世界模型/仿真器 |
| 更新 | 手动 | 每天 | 每天 |
| 去重 | 无 | 无 | 自动去重 |
| 排序 | 无 | 时间 | 重要性评分 |
| 搜索 | 无 | 简单 | 全文 + 高亮 |
| 摘要 | 无 | 无 | AI 3 句话摘要 |
| 收藏 | 无 | 无 | 本地收藏 |
| 周报 | 无 | 无 | 自动生成 |

**一句话：Awesome List 是"工具箱"，Embodied Dashboard 是"雷达"。**

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量（可选，用于 AI 摘要）
cp .env.example .env
# 在 .env 中填入 DeepSeek API key

# 3. 一键运行（推荐）
python run.py all

# 或分步运行
python run.py backfill 90    # 爬取过去 90 天数据
python run.py html           # 生成 HTML 展示页
python run.py weekly         # 生成周报
python run.py summaries 20   # 给前 20 篇生成 AI 摘要
```

打开 `output/index.html` 即可使用。

## 常用命令

```bash
python run.py collect          # 采集最新数据
python run.py backfill 90      # 爬取过去 90 天
python run.py html             # 生成 HTML
python run.py weekly           # 生成 Markdown 周报
python run.py summaries 20     # AI 摘要（前 20 篇）
python run.py all              # 完整 pipeline
```

## 项目结构

```
embodied-dashboard/
├── run.py                    # 统一入口
├── generate_html.py          # 生成静态 HTML
├── utils.py                  # 工具：重试、缓存、日志
├── collectors/               # 采集器
│   ├── arxiv_collector.py
│   ├── rss_collector.py
│   └── x_api_collector.py
├── pipeline/                 # 数据处理
│   ├── run_daily.py
│   ├── backfill.py
│   ├── aggregate.py
│   ├── tagger.py
│   ├── llm_tagger.py
│   ├── quality.py            # 去噪、质量评分
│   ├── gen_summaries.py      # AI 摘要
│   └── weekly_report.py      # 周报
├── models/                   # 数据模型
├── config/
│   └── sources.yaml          # 白名单信息源
├── docs/
│   ├── source_tiers.md       # 信息源分级
│   └── product_analysis.md   # 产品分析
├── web/                      # Next.js 前端（v2）
└── output/                   # 生成结果
    ├── index.html
    └── weekly_*.md
```

## 信息源分级

| 级别 | 来源 | 特点 |
|---|---|---|
| L0 | arXiv、OpenReview | 同行评审，最权威 |
| L1 | DeepMind、NVIDIA、PI 博客 | 工业界研究，有落地背景 |
| L2 | 公司新闻、融资 | 行业信号 |
| L3 | X、GitHub | 最快，需要筛选 |

详见 `docs/source_tiers.md`。

## 技术栈

- **数据采集**：Python + arxiv + feedparser
- **数据处理**：规则打标 + DeepSeek LLM
- **存储**：JSON 文件（v1）→ SQLite（v2）
- **前端**：原生 HTML/JS（v1，零依赖）→ Next.js（v2）
- **LLM**：DeepSeek（便宜，效果好），也支持 Gemini

## Open-Core 策略

**开源版（MIT）**：核心爬虫、事件聚合、规则打标、静态 HTML
**托管版（未来）**：语义搜索、AI 摘要、监控告警、团队协作、私有源

## 路线图

- [x] v0.1：arXiv 采集 + 事件聚合 + 规则打标
- [x] v0.2：DeepSeek LLM 打标 + AI 摘要
- [x] v0.3：收藏、搜索、筛选、相关推荐
- [x] v0.4：本周必看 10 篇 + 周报 + 时间筛选
- [x] v0.5：重试缓存、数据去噪、首次引导
- [ ] v0.6：RSS 工业界博客接入
- [ ] v0.7：X API 采集
- [ ] v0.8：Next.js 前端 + 语义搜索
- [ ] v1.0：监控告警 + 订阅推送

## License

MIT
