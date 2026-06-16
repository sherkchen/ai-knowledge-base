import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from pipeline.model_client import chat, tracker

# 做两次调用
result1 = chat('用一句话介绍 Python')
print(f'回复 1: {result1["content"][:80]}')

result2 = chat('用一句话介绍 JavaScript')
print(f'回复 2: {result2["content"][:80]}')

# 打印成本报告
tracker.report()
