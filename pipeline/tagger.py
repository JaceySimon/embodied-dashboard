"""
规则打标器 - 用关键词规则给 Paper 打标签
v1：不接 LLM，纯规则
改进：用词边界匹配，避免误标
"""
import re
from typing import List, Dict
from models.paper import Paper


# 标签规则：关键词 -> 标签
# 用 \b 词边界匹配，避免误标
TAG_RULES: Dict[str, List[str]] = {
    # 技术方向
    "VLA": [r"\bvision-language-action\b", r"\bVLA\b", r"\bvision language action\b"],
    "diffusion_policy": [r"\bdiffusion policy\b", r"\bdiffusion-policy\b"],
    "world_model": [r"\bworld model\b", r"\bworld models\b"],
    "imitation_learning": [r"\bimitation learning\b", r"\bbehavior cloning\b", r"\bbehaviour cloning\b"],
    "reinforcement_learning": [r"\breinforcement learning\b", r"\bdeep RL\b", r"\bRL\b"],
    "sim2real": [r"\bsim-to-real\b", r"\bsim2real\b", r"\bsim to real\b"],
    "teleoperation": [r"\bteleoperation\b", r"\bteleop\b", r"\btele-operated\b"],
    "grasping": [r"\bgrasping\b", r"\bgrasp\b"],
    "manipulation": [r"\bmanipulation\b", r"\bmanipulate\b", r"\bbimanual\b"],
    "locomotion": [r"\blocomotion\b", r"\bquadruped\b", r"\blegged\b"],
    "navigation": [r"\bnavigation\b", r"\bSLAM\b", r"\bpath planning\b"],
    "humanoid": [r"\bhumanoid\b"],
    "dexterous_hand": [r"\bdexterous hand\b", r"\bdexterous manipulation\b", r"\bAllegro\b"],
    "3d_vision": [r"\bpoint cloud\b", r"\bNeRF\b", r"\b3D reconstruction\b"],
    "multimodal": [r"\bmultimodal\b", r"\bvision-language\b", r"\bcross-modal\b"],
    "foundation_model": [r"\bfoundation model\b", r"\bbase model\b"],

    # 机器人平台（更精确）
    "UR5": [r"\bUR5\b", r"\bUR-5\b", r"\bUniversal Robots\b"],
    "Franka": [r"\bFranka\b", r"\bFranka Panda\b"],
    "Allegro": [r"\bAllegro hand\b", r"\bAllegro\b"],
    "Shadow_Hand": [r"\bShadow hand\b", r"\bShadow Hand\b"],
    "Optimus": [r"\bTesla Optimus\b", r"\bOptimus\b"],
    "Unitree": [r"\bUnitree\b", r"\bGo1\b", r"\bGo2\b", r"\bH1 robot\b", r"\bG1 robot\b"],
    "Figure": [r"\bFigure 01\b", r"\bFigure 02\b", r"\bFigure AI\b"],
    "AgiBot": [r"\bAgiBot\b", r"\bAgibot\b", r"\b智元机器人\b"],
    "Galbot": [r"\bGalbot\b", r"\b银河通用\b"],
    "Pi": [r"\bπ0\b", r"\bPi0\b", r"\bPhysical Intelligence\b"],
    "Skild": [r"\bSkild AI\b", r"\bSkild\b"],
    "1X": [r"\b1X Technologies\b", r"\b1X robot\b", r"\bNEO robot\b"],

    # 数据集
    "DROID": [r"\bDROID\b", r"\bDROID dataset\b"],
    "OpenX": [r"\bOpen X-Embodiment\b", r"\bOpen X\b", r"\bOXE\b"],
    "RLBench": [r"\bRLBench\b"],
    "LIBERO": [r"\bLIBERO\b"],
    "CALVIN": [r"\bCALVIN\b"],
    "RoboNet": [r"\bRoboNet\b"],

    # 其他
    "real_robot": [r"\breal robot\b", r"\breal-world\b", r"\breal world\b", r"\bphysical robot\b", r"\bon a real\b"],
    "open_source": [r"\bopen source\b", r"\bopensource\b", r"\bgithub\b", r"\bcode available\b"],
}


def tag_paper(paper: Paper) -> Paper:
    """给 Paper 打标签"""
    text = (paper.title + " " + (paper.abstract or "")).lower()
    tags = []
    robot_platforms = []
    datasets = []

    for tag, patterns in TAG_RULES.items():
        for pattern in patterns:
            # 词边界匹配
            if re.search(pattern.lower(), text):
                tags.append(tag)
                break

    # 单独分类
    platform_tags = ["UR5", "Franka", "Allegro", "Shadow_Hand", "Optimus", "Unitree",
                     "Figure", "AgiBot", "Galbot", "Pi", "Skild", "1X"]
    dataset_tags = ["DROID", "OpenX", "RLBench", "LIBERO", "CALVIN", "RoboNet"]

    robot_platforms = [t for t in tags if t in platform_tags]
    datasets = [t for t in tags if t in dataset_tags]

    # 判断是否有真机
    has_real_robot = "real_robot" in tags

    # 判断是否开源
    is_open_source = "open_source" in tags or bool(paper.code_url)

    paper.tags = list(set(tags))
    paper.robot_platforms = robot_platforms
    paper.datasets = datasets
    paper.has_real_robot = has_real_robot
    paper.is_open_source = is_open_source

    return paper


def tag_papers(papers: List[Paper]) -> List[Paper]:
    """批量打标"""
    return [tag_paper(p) for p in papers]
