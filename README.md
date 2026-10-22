# Embodied Dashboard

> 具身智能 / VLA 方向的动态知识导航看板
> 帮你少读 80% 垃圾，半小时看清谁在真做、谁在刷榜

## 这是什么？

一个面向具身智能研究者的**事件级**信息聚合器——把散在 arXiv、公司博客、X 线程、HuggingFace、GitHub 上的**同一件事**聚合成一条"事件"，按原始度和权威性排序，让研究者 5 分钟看完本周领域发生了什么。

## 和 Awesome List 有什么区别？

| | Awesome List | Embodied Dashboard |
|---|---|---|
| 内容 | 静态列表 | 动态时间线 |
| 更新 | 手动维护 | 自动每日抓取 |
| 去重 | 无 | 同一事件多来源自动聚合 |
| 搜索 | 无 | 全文搜索 + 标签筛选 |
| 时效 | 季度更新 | 每日更新 |
| 价值 | 收藏夹 | 信息过滤器 |

**一句话：Awesome List 是"工具箱"，Embodied Dashboard 是"雷达"。**

## 定位（收窄后的范围）

**只收三类实体：**
1. **VLA（Vision-Language-Action）模型**：π0、RT-2、Octo 等
2. **世界模型（World Model）**：Genie、Dreamer、W\^A 等
3. **仿真器（Simulator）**：Isaac Sim、MuJoCo、SAPIEN 等

**不收：**
- 纯导航、纯抓取、纯硬件（太泛）
- 非具身的纯 NLP/CV 论文
- 新闻媒体、博客（只做来源链接，不做内容）

## Open-Core 策略

**开源版（免费）：**
- 核心爬虫（arXiv / RSS / X）
- 事件聚合 + 去重
- 基础标签系统
- 静态 HTML 展示页

**托管版（付费）：**
- 高级检索（语义搜索）
- AI 摘要（每篇论文自动生成 3 句话摘要）
- 监控告警（关注的论文/公司有更新时通知）
- 导出报告（PDF / 简报）
- 团队协作（多人协作、私有源）

## 技术栈

- **数据采集**：Python + arxiv + feedparser
- **数据处理**：规则打标 + DeepSeek LLM 打标
- **存储**：SQLite（本地）→ Supabase（云端）
- **前端**：Next.js + Tailwind CSS
- **部署**：Cloudflare Pages + GitHub Actions

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制 .env.example 为 .env，填入 API key）
cp .env.example .env

# 跑每日采集
python pipeline/run_daily.py

# 跑历史数据（90 天）
python pipeline/backfill.py 90

# 生成静态 HTML 展示页
python generate_html.py
```

## 项目结构

```
embodied-dashboard/
├── collectors/          # 采集器
│   ├── arxiv_collector.py
│   ├── rss_collector.py
│   └── x_api_collector.py
├── pipeline/            # 数据处理
│   ├── run_daily.py
│   ├── aggregate.py
│   ├── tagger.py
│   └── llm_tagger.py
├── models/              # 数据模型
├── config/              # 配置
│   └── sources.yaml
├── web/                # Next.js 前端
└── data/                # 数据（不提交 Git）
```

## 路线图

- [x] v0.1：采集器 + 事件聚合 + 规则打标
- [x] v0.2：DeepSeek LLM 打标
- [ ] v0.3：Next.js 前端
- [ ] v0.4：X API 采集
- [ ] v0.5：语义搜索
- [ ] v1.0：AI 摘要 + 监控告警

## License

MIT
