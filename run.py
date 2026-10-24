"""
具身智能看板 - 统一入口

用法:
    python run.py collect          # 采集最新数据
    python run.py backfill 90      # 爬取过去 N 天数据
    python run.py html             # 生成 HTML 展示页
    python run.py weekly           # 生成周报
    python run.py all              # 一键：采集 + 合并 + 生成HTML + 周报
    python run.py health           # 数据源健康检查
    python run.py summaries 20     # 给前 N 篇论文生成 AI 摘要
"""
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def run(cmd: str):
    """运行命令"""
    print(f"\n{'='*60}")
    print(f"运行: {cmd}")
    print('='*60)
    result = subprocess.run(cmd, shell=True, cwd=PROJECT_ROOT)
    if result.returncode != 0:
        print(f"命令失败: {cmd}")
        sys.exit(1)


def collect():
    """采集最新数据"""
    run("python pipeline/run_daily.py")


def backfill(days: int = 90):
    """爬取历史数据"""
    run(f"python pipeline/backfill.py {days}")


def gen_html():
    """生成 HTML 展示页"""
    run("python generate_html.py")


def weekly():
    """生成周报"""
    run("python pipeline/weekly_report.py")


def summaries(n: int = 20):
    """生成 AI 摘要"""
    run(f"python pipeline/gen_summaries.py {n}")


def all_pipeline():
    """一键运行完整 pipeline"""
    collect()
    run("python pipeline/merge_sources.py")
    gen_html()
    weekly()
    print("\n✅ 全部完成！")
    print(f"   HTML: {PROJECT_ROOT / 'output' / 'index.html'}")
    print(f"   周报: {PROJECT_ROOT / 'output' / 'weekly_*.md'}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "collect":
        collect()
    elif command == "backfill":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 90
        backfill(days)
    elif command == "html":
        gen_html()
    elif command == "merge":
        run("python pipeline/merge_sources.py")
    elif command == "health":
        run("python pipeline/health_check.py")
    elif command == "quality":
        run("python pipeline/data_quality.py")
    elif command == "weekly":
        weekly()
    elif command == "summaries":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        summaries(n)
    elif command == "all":
        all_pipeline()
    else:
        print(f"未知命令: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
