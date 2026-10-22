"""
LLM 打标器 - 用 LLM 替代规则打标
支持：DeepSeek / Gemini Flash
从 .env 文件读取配置
"""
import json
import os
from pathlib import Path
from typing import List, Optional
from models.paper import Paper


# 从 .env 文件加载配置
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()


# 打标 prompt
TAG_PROMPT = """你是一个具身智能/机器人领域的研究助手。请给以下论文打标签。

论文标题：{title}
论文摘要：{abstract}

请输出 JSON 格式，包含以下字段：
- tags: 标签列表，从以下选项中选：
  VLA, diffusion_policy, world_model, imitation_learning, reinforcement_learning,
  sim2real, teleoperation, grasping, manipulation, locomotion, navigation, humanoid,
  dexterous_hand, multimodal, foundation_model, 3d_vision
- has_real_robot: 是否有真机实验（true/false）
- is_open_source: 是否开源（true/false）
- robot_platforms: 使用的机器人平台列表（如 Franka, UR5, Unitree, Allegro 等，没有则空列表）
- datasets: 使用的数据集列表（如 LIBERO, CALVIN, DROID 等，没有则空列表）

只输出 JSON，不要其他内容。"""


class LLMTagger:
    """用 LLM 给论文打标签"""

    def __init__(self, provider: str = "hunyuan", api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        self.base_urls = {
            "hunyuan": "https://hunyuan.tencentcloudapi.com",
            "deepseek": "https://api.deepseek.com/v1",
            "gemini": "https://generativelanguage.googleapis.com/v1beta",
        }

    def _call_llm(self, prompt: str) -> Optional[str]:
        """调用 LLM API"""
        if not self.api_key:
            return None

        try:
            import requests
            if self.provider == "deepseek":
                url = f"{self.base_urls['deepseek']}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                }
                resp = requests.post(url, headers=headers, json=data, timeout=30)
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
            elif self.provider == "gemini":
                url = f"{self.base_urls['gemini']}/models/gemini-1.5-flash:generateContent"
                headers = {"Content-Type": "application/json"}
                data = {
                    "contents": [{"parts": [{"text": prompt}]}],
                }
                resp = requests.post(f"{url}?key={self.api_key}", headers=headers, json=data, timeout=30)
                if resp.status_code == 200:
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"  [LLM] 调用失败: {e}")
        return None

    def tag_paper(self, paper: Paper) -> Paper:
        """给单篇论文打标签"""
        prompt = TAG_PROMPT.format(
            title=paper.title,
            abstract=(paper.abstract or "")[:1000],
        )

        response = self._call_llm(prompt)
        if not response:
            return paper  # 失败就用规则打标的结果

        try:
            # 解析 JSON
            # 去掉 markdown 代码块标记
            response = response.strip()
            if response.startswith("```"):
                response = response.split("```")[1]
                if response.startswith("json"):
                    response = response[4:]
                response = response.strip()

            result = json.loads(response)
            paper.tags = result.get("tags", paper.tags)
            paper.has_real_robot = result.get("has_real_robot", paper.has_real_robot)
            paper.is_open_source = result.get("is_open_source", paper.is_open_source)
            paper.robot_platforms = result.get("robot_platforms", paper.robot_platforms)
            paper.datasets = result.get("datasets", paper.datasets)
        except Exception as e:
            print(f"  [LLM] 解析失败: {e}")

        return paper

    def tag_papers(self, papers: List[Paper]) -> List[Paper]:
        """批量打标"""
        if not self.api_key:
            print("  [LLM] 未设置 API key，跳过 LLM 打标")
            return papers

        print(f"  [LLM] 开始打标 {len(papers)} 篇论文...")
        tagged = []
        for i, p in enumerate(papers):
            p = self.tag_paper(p)
            tagged.append(p)
            if (i + 1) % 10 == 0:
                print(f"  [LLM] 已打标 {i+1}/{len(papers)}")
        return tagged


def build_llm_tagger_from_config(config: dict) -> Optional[LLMTagger]:
    """从配置构建 LLM 打标器"""
    # 从环境变量读配置
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    api_key = os.environ.get("LLM_API_KEY")

    if not api_key:
        return None

    return LLMTagger(provider=provider, api_key=api_key)
