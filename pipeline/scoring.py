"""
论文重要性评分（generate_html 与 gen_weekly_intro 共用，避免逻辑重复）。

- calc_score：学术论文（arXiv / OpenReview / 模型）重要性
- calc_industry_score：工业界一手发布（公司 / 实验室博客）重要性
"""


def calc_score(p):
    score = 0
    # 标签权重：VLA、world_model、sim2real 是重点
    weight_map = {
        "VLA": 10,
        "world_model": 8,
        "sim2real": 7,
        "diffusion_policy": 6,
        "foundation_model": 6,
        "manipulation": 4,
        "locomotion": 3,
        "navigation": 3,
    }
    for t in p.get("tags", []):
        score += weight_map.get(t, 1)
    # 有真机实验加分
    if p.get("has_real_robot", False):
        score += 5
    # 已开源加分
    if p.get("is_open_source", False):
        score += 3
    # 作者数量（多人合作通常更重要）
    score += min(len(p.get("authors", [])), 5)
    return score


def calc_industry_score(p):
    score = 0
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    # 重大技术信号：权重向模型/开源/数据集/基准/世界模型倾斜
    signals = [
        ("world model", 10), ("vision-language-action", 10), ("vla", 9),
        ("foundation model", 9), ("open-source", 8), ("open source", 8), ("opensources", 8),
        ("dataset", 7), ("benchmark", 7), ("simulator", 7), ("imitation", 6),
        ("reinforcement learning", 6), ("introducing", 6), ("launches", 5), ("unveils", 5),
        ("humanoid", 5), ("deploys", 4), ("generalist", 4), ("manipulation", 4),
        ("robot model", 4), ("policy", 3), ("robot", 2),
    ]
    for kw, w in signals:
        if kw in text:
            score += w
    # 中文技术信号（中国公司一手源标题为中文，避免英文词表导致系统性低估）
    signals_zh = [
        ("世界模型", 10), ("视觉语言动作", 9), ("vla", 9), ("具身大模型", 9),
        ("基础模型", 8), ("大模型", 7), ("开源", 8), ("数据集", 7), ("基准", 7),
        ("端到端", 6), ("后训练", 6), ("模仿学习", 6), ("强化学习", 6),
        ("具身智能", 5), ("人形机器人", 5), ("真机", 4), ("部署", 4),
        ("操作", 4), ("抓取", 3), ("策略", 3),
    ]
    for kw, w in signals_zh:
        if kw in text:
            score += w
    if p.get("is_open_source"):
        score += 5
    if p.get("has_real_robot"):
        score += 3
    if p.get("code_url"):
        score += 3
    # 头部源加权（模型型公司/实验室）
    top_sources = {"Google DeepMind Research": 4, "Physical Intelligence": 4,
                   "Figure AI": 3, "Skild AI": 3, "NVIDIA Research Blog": 3,
                   "智元机器人 AgiBot": 3, "逐际动力 LimX": 2, "1X Technologies": 2,
                   "Sanctuary AI": 2, "Boston Dynamics": 2,
                   "银河通用 Galbot": 2, "星动纪元 RobotEra": 2,
                   "宇树科技 Unitree": 2, "众擎机器人 EngineAI": 2}
    score += top_sources.get(p.get("source_name", ""), 0)
    return score
