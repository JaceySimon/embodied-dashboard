# 具身智能看板

> 动态知识导航看板 - 具身智能 / VLA 方向
> v1 阶段：数据 pipeline，先把数据跑通

## 项目结构

```
embodied-dashboard/
├── config/
│   └── sources.yaml          # 白名单源清单（L0/L1/L2）
├── collectors/
│   ├── base.py               # 采集器基类
│   └── arxiv_collector.py    # arXiv 采集器
├── pipeline/
│   ├── run_daily.py          # 主 pipeline
│   └── clean.py              # 清洗与去重
├── models/
│   └── paper.py              # 数据模型（Paper / Event）
├── data/
│   ├── raw/                  # 原始采集 JSON
│   ├── processed/            # 去重后 JSON
│   └── db/                   # SQLite（v2）
└── output/                   # 最终输出
```

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 跑每日 pipeline
cd embodied-dashboard
python pipeline/run_daily.py
```

## v1 阶段目标

1. ✅ 方案文档（见 `F:\StartUp\solution_v1.md`）
2. ✅ 项目骨架
3. ✅ arXiv 采集器
4. 🔄 跑通采集，验证数据质量
5. ⬜ RSS 采集器
6. ⬜ 事件聚合（相似度聚类）
7. ⬜ LLM 打标
8. ⬜ Next.js 前端

## 设计原则

- **白名单制**：只收白名单源，不在清单内的不收
- **事件聚合**：同一件事在多个平台的发布，聚合成一个事件
- **L0 锚定**：L0（论文/tech report）是主源，L1/L2 挂在事件下
- **全托管**：v1 本地跑，v2 上 Cloudflare + Supabase
- **博士时间优先**：维护时间 < 每周 4 小时
