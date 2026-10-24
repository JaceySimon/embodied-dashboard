"""
GitHub 采集器
捕获两类一手开源动态：
1. 重点公司/实验室组织的开源仓库（新开源 / 重要项目更新）
2. 重点框架（MuJoCo / IsaacLab / IsaacSim）的版本发布

免费 API：未认证 60 次/小时；设置 GITHUB_TOKEN 后 5000 次/小时。
"""
import os
import re
import time
from datetime import datetime, timezone
from typing import List, Optional

import requests

from collectors.base import BaseCollector
from models.paper import Paper, SourceLevel, SourceType
from pipeline.clean import normalize_url, title_hash
from pipeline.llm_tagger import load_env

load_env()


def _parse_dt(s):
    """ISO 时间字符串 -> naive datetime"""
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return datetime.utcnow()


def _is_patch(tag):
    """判断版本号是否仅为 patch（如 3.17.1），major/minor 保留"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", tag.lstrip("v"))
    if not m:
        return False
    return m.group(3) not in (None, "0")


# 机器人/具身相关性关键词（用于大组织过滤；命中 name/description/topics 之一）
ROBOT_KEYWORDS = [
    "robot", "robotic", "manipulation", "locomotion", "humanoid", "mujoco",
    "isaac", "embodied", "grasp", "gripper", "dexterous", "teleoperat",
    "quadruped", "sim2real", "sim-to-real", "vision-language-action",
    "robot learning", "legged", "bimanual", "end-effector", "end effector",
    "manipulator", "actuator", "ros2", "imu", "motion planning",
    "机械臂", "机器人", "具身", "人形", "仿真", "抓取", "足式", "灵巧手", "双足",
]


def _is_relevant(repo) -> bool:
    """判断仓库是否与具身/机器人相关"""
    name = (repo.get("name") or "").lower()
    desc = (repo.get("description") or "").lower()
    topics = " ".join(repo.get("topics") or []).lower()
    blob = f"{name} {desc} {topics}"
    return any(k in blob for k in ROBOT_KEYWORDS)


class GitHubCollector(BaseCollector):
    """从 GitHub 组织/仓库采集开源动态"""

    def __init__(self, organizations=None, release_repos=None,
                 window_days=90, new_repo_min_stars=1):
        self.organizations = organizations or []
        self.release_repos = release_repos or []
        self.window_days = window_days
        self.new_repo_min_stars = new_repo_min_stars
        self.token = os.environ.get("GITHUB_TOKEN")
        self.api = "https://api.github.com"

    def _headers(self):
        h = {"Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, path, params=None, retries=2):
        for attempt in range(retries + 1):
            try:
                r = requests.get(f"{self.api}{path}", headers=self._headers(),
                                 params=params, timeout=20)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (403, 429):
                    reset = r.headers.get("X-RateLimit-Reset")
                    if reset and not self.token:
                        print(f"  [GitHub] 未认证速率限制耗尽，建议在 .env 配置 GITHUB_TOKEN "
                              f"(免费,5000次/小时)；reset={reset}")
                        return None
                    time.sleep(15)
                else:
                    return None
            except Exception:
                time.sleep(3)
        return None

    def _repo_paper(self, repo, org_label):
        full = repo["full_name"]
        name = repo.get("name", "")
        desc = (repo.get("description") or "").strip()
        stars = repo.get("stargazers_count", 0)
        date_str = repo.get("created_at", "")
        title = f"{name}: {desc}" if desc else name
        url = repo.get("html_url", "")
        tags = ["open_source"]
        text = (name + " " + desc).lower()
        if any(k in text for k in ["sim", "isaac", "mujoco", "gym"]):
            tags.append("sim2real")
        if any(k in text for k in ["vla", "vision-language", "policy"]):
            tags.append("VLA")
        return Paper(
            id=f"github:{full}",
            source_id=f"github:{full}",
            source_level=SourceLevel.L0,
            source_type=SourceType.GITHUB,
            source_name=f"{org_label} · GitHub",
            title=title,
            abstract=desc or None,
            authors=[],
            institutions=[],
            url=url,
            code_url=url,
            published_at=_parse_dt(date_str),
            updated_at=_parse_dt(repo.get("pushed_at", "")),
            categories=[],
            tags=tags,
            is_open_source=True,
            title_hash=title_hash(title),
            raw_metadata={
                "stars": stars,
                "created_at": repo.get("created_at", "")[:10],
                "pushed_at": repo.get("pushed_at", "")[:10],
                "new_open_source": True,
            },
        )

    def _release_paper(self, full_name, release, repo_label):
        tag = release.get("tag_name", "")
        title = f"{full_name.split('/')[-1]} {tag} 发布"
        body = release.get("body", "") or ""
        # markdown 链接 [text](url) -> text
        body = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", body)
        # 去图片、HTML 标签、标题/加粗/代码标记
        body = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", body)
        body = re.sub(r"<[^>]+>", " ", body)
        body = body.replace("#", "").replace("**", "").replace("`", "")
        body = re.sub(r"\s+", " ", body).strip()
        url = release.get("html_url", "")
        return Paper(
            id=f"github:{full_name}:{tag}",
            source_id=f"github:{full_name}:{tag}",
            source_level=SourceLevel.L0,
            source_type=SourceType.GITHUB,
            source_name=f"{repo_label} · Release",
            title=title,
            abstract=body[:1500] if body else None,
            authors=[],
            institutions=[],
            url=url,
            code_url=f"https://github.com/{full_name}",
            published_at=_parse_dt(release.get("published_at", "")),
            categories=[],
            tags=["open_source"],
            is_open_source=True,
            title_hash=title_hash(title),
            raw_metadata={"tag": tag, "repo": full_name},
        )

    def collect(self, lookback_days: Optional[int] = None) -> List[Paper]:
        window = lookback_days or self.window_days
        cutoff = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        cutoff_dt = (datetime.now(timezone.utc)).timestamp() - window * 86400
        papers = []
        seen = set()

        # 1) 组织新开源仓库（只收"新仓库"这一明确事件；日常 commit 是弱信号，不收）
        for org in self.organizations:
            name = org["name"]
            label = org.get("label", name)
            kind = org.get("kind", "orgs")
            relevant_only = org.get("relevant_only", False)
            whitelist = set(org.get("repos", []))
            path = f"/{kind}/{name}/repos"
            repos = self._get(path, params={"sort": "updated", "per_page": 100})
            if not repos:
                continue
            for repo in repos:
                full = repo["full_name"]
                short = repo.get("name", "")
                if full in seen or repo.get("fork"):
                    continue
                # 跳过 GitHub 组织默认配置仓库（不是真实项目）
                if short in (".github", ".github-private"):
                    continue
                created = _parse_dt(repo.get("created_at", "")).replace(tzinfo=timezone.utc).timestamp()
                stars = repo.get("stargazers_count", 0)
                has_desc = bool((repo.get("description") or "").strip())
                if created < cutoff_dt:
                    continue
                if stars < self.new_repo_min_stars and not has_desc:
                    continue
                # 大组织（如 google-deepmind）只收机器人相关或显式白名单仓库
                if relevant_only and short not in whitelist and not _is_relevant(repo):
                    continue
                seen.add(full)
                papers.append(self._repo_paper(repo, label))

        # 2) 框架 releases（过滤 patch）
        for full_name in self.release_repos:
            label = full_name.split("/")[-1]
            releases = self._get(f"/repos/{full_name}/releases",
                                 params={"per_page": 20})
            if not releases:
                continue
            for rel in releases:
                tag = rel.get("tag_name", "")
                pub = _parse_dt(rel.get("published_at", "")).replace(tzinfo=timezone.utc).timestamp()
                if pub < cutoff_dt:
                    continue
                if _is_patch(tag):
                    continue
                gid = f"{full_name}:{tag}"
                if gid in seen:
                    continue
                seen.add(gid)
                papers.append(self._release_paper(full_name, rel, label))

        papers.sort(key=lambda p: p.published_at, reverse=True)
        print(f"  [GitHub] {len(papers)} 条开源动态")
        return papers


def build_github_collector_from_config(config: dict) -> Optional[GitHubCollector]:
    gh = config.get("l0", {}).get("github", {})
    if not gh.get("enabled", False):
        return None
    return GitHubCollector(
        organizations=gh.get("organizations", []),
        release_repos=gh.get("release_repos", []),
        window_days=gh.get("window_days", 90),
        new_repo_min_stars=gh.get("new_repo_min_stars", 1),
    )
