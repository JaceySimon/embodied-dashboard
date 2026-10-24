"""
Hugging Face 采集器（模型/权重一手发布）
捕获白名单机构（NVIDIA GR00T、LeRobot/π0、PI 等）正式发布的具身机器人模型。

设计要点：
- 只收白名单组织（机构发布的正式模型），不按 robotics 标签全量拉——
  那样会混入大量个人开发者的微调/checkpoint（实测每天数十个 0♥ 噪声模型）。
- 大组织（nvidia）用 pipeline_tag=robotics 或强具身词过滤；
  机器人专注组织（lerobot）整组织收，仅排除 checkpoint。
- 国内直连 huggingface.co 超时，默认走 hf-mirror.com 镜像取数据；
  链接仍指向官方站。
"""
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

import requests

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import title_hash
from pipeline.llm_tagger import load_env

load_env()

# 强具身词（用于大组织过滤；命中模型 id 或 tags）
ROBOT_MODEL_TERMS = [
    "gr00t", "groot", "openpi", "pi0", "pi05", "smolvla", "vla",
    "embodied", "robot", "robotic", "manipulation", "locomotion",
    "humanoid", "droid", "dexterous", "teleoperat", "lerobot",
    "cosmos-policy", "cosmos-nano-sim", "policy",
]
# 训练中间产物 / 数据导出命名（排除）
NOISE_PATTERNS = ["checkpoint", "ckpt", "-step", "_step", "gradients",
                  "sdg-export", "sft-export", "-export-", "libero10-sdg"]


def _parse_dt(s):
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return datetime.utcnow()


class HuggingFaceCollector(BaseCollector):
    """从 Hugging Face 白名单组织采集具身机器人模型发布"""

    def __init__(self, organizations=None, window_days=90,
                 base_url="https://hf-mirror.com"):
        self.organizations = organizations or []
        self.window_days = window_days
        self.base_url = base_url.rstrip("/")
        self.token = os.environ.get("HF_TOKEN")

    def _headers(self):
        h = {"User-Agent": "embodied-dashboard", "Accept": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, path, params=None, retries=2):
        for attempt in range(retries + 1):
            try:
                r = requests.get(f"{self.base_url}{path}", headers=self._headers(),
                                 params=params, timeout=25)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 403):
                    time.sleep(10)
                else:
                    return None
            except Exception:
                time.sleep(4)
        return None

    @staticmethod
    def _is_noise(mid: str) -> bool:
        low = mid.lower()
        return any(p in low for p in NOISE_PATTERNS)

    @staticmethod
    def _is_robot(m: dict) -> bool:
        if m.get("pipeline_tag") == "robotics":
            return True
        tags = " ".join(m.get("tags") or []).lower()
        mid = m.get("id", "").lower()
        blob = f"{mid} {tags}"
        return any(t in blob for t in ROBOT_MODEL_TERMS)

    def _model_paper(self, m, org_label):
        full = m["id"]
        name = full.split("/")[-1]
        likes = m.get("likes", 0)
        downloads = m.get("downloads", 0)
        tags = ["open_source", "hf_model"]
        blob = (full + " " + " ".join(m.get("tags") or [])).lower()
        if any(k in blob for k in ["sim", "gr00t", "groot", "droid"]):
            tags.append("sim2real")
        if any(k in blob for k in ["vla", "pi0", "pi05", "policy", "embodied"]):
            tags.append("VLA")
        return Paper(
            id=f"hf:{full}",
            source_id=f"hf:{full}",
            source_level=SourceLevel.L0,
            source_type=SourceType.HUGGINGFACE,
            source_name=f"{org_label} · Hugging Face",
            title=f"{name}（模型权重）",
            abstract=None,
            authors=[],
            institutions=[org_label],
            url=f"https://huggingface.co/{full}",
            code_url=None,
            published_at=_parse_dt(m.get("createdAt")),
            updated_at=_parse_dt(m.get("lastModified")),
            categories=[],
            tags=tags,
            is_open_source=True,
            title_hash=title_hash(full),
            raw_metadata={
                "likes": likes,
                "downloads": downloads,
                "pipeline_tag": m.get("pipeline_tag"),
                "created_at": (m.get("createdAt") or "")[:10],
            },
        )

    def collect(self, lookback_days: Optional[int] = None) -> List[Paper]:
        window = lookback_days or self.window_days
        cutoff_dt = datetime.now(timezone.utc).timestamp() - window * 86400
        papers = []
        seen = set()

        for org in self.organizations:
            name = org["name"]
            label = org.get("label", name)
            relevant_only = org.get("relevant_only", False)
            models = self._get("/api/models", params={
                "author": name, "sort": "createdAt",
                "direction": -1, "limit": 1000,
            })
            if not models:
                print(f"  [HF] {name}: 无数据或无法访问")
                continue
            kept = 0
            for m in models:
                mid = m.get("id", "")
                if mid in seen or self._is_noise(mid):
                    continue
                created = _parse_dt(m.get("createdAt")).replace(tzinfo=timezone.utc).timestamp()
                if created < cutoff_dt:
                    continue  # 按创建时间倒序，理论上可 break，但保守起见 continue
                if relevant_only and not self._is_robot(m):
                    continue
                seen.add(mid)
                papers.append(self._model_paper(m, label))
                kept += 1
            print(f"  [HF] {name}: {kept} 个近 {window} 天机器人模型")

        papers.sort(key=lambda p: p.published_at, reverse=True)
        print(f"  [HuggingFace] {len(papers)} 个模型发布")
        return papers


def build_hf_collector_from_config(config: dict) -> Optional[HuggingFaceCollector]:
    hf = config.get("l0", {}).get("huggingface", {})
    if not hf.get("enabled", False):
        return None
    return HuggingFaceCollector(
        organizations=hf.get("organizations", []),
        window_days=hf.get("window_days", 90),
        base_url=hf.get("base_url", "https://hf-mirror.com"),
    )
