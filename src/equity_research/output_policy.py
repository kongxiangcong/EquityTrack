from __future__ import annotations

import re
from typing import Pattern


ACTION_LANGUAGE: tuple[tuple[Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z])(?:OUTPERFORM|OVERWEIGHT|ACCUMULATE|ADD)(?![A-Za-z])", re.IGNORECASE), "positive research case"),
    (re.compile(r"(?<![A-Za-z])(?:UNDERPERFORM|UNDERWEIGHT|AVOID|REDUCE)(?![A-Za-z])", re.IGNORECASE), "negative research case"),
    (re.compile(r"(?<![A-Za-z])(?:RECOMMEND|RECOMMENDED|RATING)(?![A-Za-z])", re.IGNORECASE), "research classification"),
    (re.compile(r"(?<![A-Za-z])BUY(?![A-Za-z])", re.IGNORECASE), "positive research case"),
    (re.compile(r"(?<![A-Za-z])SELL(?![A-Za-z])", re.IGNORECASE), "negative research case"),
    (re.compile(r"(?<![A-Za-z])HOLD(?![A-Za-z])", re.IGNORECASE), "ongoing research"),
    (re.compile(r"建议\s*(?:买入|卖出|持有|增持|增仓|减持|回避)"), "条件研究验证"),
    (re.compile("可以买|买入|加仓|增仓|建仓|增持|看多|跑赢大市"), "上行情景验证"),
    (re.compile("不能买|卖出|减仓|清仓|减持|回避|看空|跑输大市"), "下行情景验证"),
    (re.compile("持有"), "持续跟踪"),
    (re.compile("强烈推荐|推荐"), "研究关注"),
    (re.compile("评级"), "研究分类"),
    (re.compile("目标价"), "估值观察区间"),
)


def normalize_action_language(value: str) -> tuple[str, bool]:
    normalized = value
    for pattern, replacement in ACTION_LANGUAGE:
        normalized = pattern.sub(replacement, normalized)
    return normalized, normalized != value


def contains_action_language(value: str) -> bool:
    return any(pattern.search(value) for pattern, _ in ACTION_LANGUAGE)
