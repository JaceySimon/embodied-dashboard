"""
通用工具：重试、缓存、日志
"""
import time
import json
import logging
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Optional

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("embodied_dashboard")


def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    重试装饰器
    :param max_retries: 最大重试次数
    :param delay: 初始延迟
    :param backoff: 延迟倍数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(
                            f"{func.__name__} 失败 (attempt {attempt + 1}/{max_retries}): {e}, "
                            f"{current_delay:.1f}s 后重试"
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"{func.__name__} 重试 {max_retries} 次后仍然失败: {e}")

            raise last_exception

        return wrapper
    return decorator


class SimpleCache:
    """简单的文件缓存"""

    def __init__(self, cache_dir: str = "data/cache", ttl_hours: int = 24):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_hours * 3600

    def _get_cache_path(self, key: str) -> Path:
        """生成缓存文件路径"""
        safe_key = key.replace("/", "_").replace(":", "_")
        return self.cache_dir / f"{safe_key}.json"

    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None

        # 检查是否过期
        age = time.time() - cache_path.stat().st_mtime
        if age > self.ttl_seconds:
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def set(self, key: str, value: Any):
        """设置缓存"""
        cache_path = self._get_cache_path(key)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, default=str)
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    def clear(self):
        """清空缓存"""
        for f in self.cache_dir.glob("*.json"):
            f.unlink()


def safe_get(data: dict, key: str, default: Any = None) -> Any:
    """安全获取字典值"""
    try:
        return data.get(key, default)
    except Exception:
        return default


def chunk_list(lst: list, chunk_size: int) -> list:
    """把列表分块"""
    for i in range(0, len(lst), chunk_size):
        yield lst[i:i + chunk_size]


def find_latest_file(directory: Path, pattern: str) -> Optional[Path]:
    """
    找目录下匹配 pattern 的最新文件（按修改时间）
    例如 find_latest_file(data/backfill, "arxiv_backfill_*.json")
    """
    directory = Path(directory)
    if not directory.exists():
        return None

    files = list(directory.glob(pattern))
    if not files:
        return None

    return max(files, key=lambda f: f.stat().st_mtime)
