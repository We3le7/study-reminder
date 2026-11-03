#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
「进度条」—— 每日学习提醒机器人
--------------------------------
读取 plan.json，按当天日期算出「今天该学什么」，
以飞书群机器人 Webhook 推送一张交互卡片。

本地试跑：
    python3 remind.py --dry-run              # 只看今天会发什么，不发
    python3 remind.py --dry-run --date 2026-11-11
    python3 remind.py                        # 真发（需要 FEISHU_WEBHOOK）

环境变量：
    FEISHU_WEBHOOK  必填，群机器人 Webhook 地址
    FEISHU_SECRET   选填，若开启了「签名校验」则填密钥
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
PLAN_FILE = os.path.join(BASE, "plan.json")

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 阶段 → 卡片主题色
PHASE_COLOR = {
    "A": "blue",
    "B": "turquoise",
    "C": "green",
    "D": "yellow",
    "E": "orange",
    "F": "purple",
}


# ---------------------------------------------------------------- 计划读取

def load_plan():
    with open(PLAN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def progress_bar(done, total, width=12):
    filled = min(width, max(0, int(round(width * done / total)))) if total else 0
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------- 内容组装

def build_pre_phase(plan, d):
    pre = plan["pre_phase"]
    days = {x["date"]: x for x in pre["days"]}
    today = days.get(d.isoformat())
    if not today:
        return None

    order = sorted(days)
    idx = order.index(d.isoformat()) + 1
    total = len(order)

    body = [
        f"**{pre['title']}**",
        f"📌 {pre['goal']}",
        "",
        f"**今天要做（{idx}/{total}）**",
    ]
    body += [f"{i}. {t}" for i, t in enumerate(today["tasks"], 1)]
    body += ["", "**参考资料**"]
    body += [f"· [{m['name']}]({m['url']})" for m in pre["materials"]]
    body += ["", "---", "环境没通就别往下学，这一步省不了。"]

    return {
        "title": f"{plan['meta']['bot_name']} · 预备期 Day {idx}",
        "subtitle": f"{d.isoformat()} {WEEKDAY_CN[d.weekday()]}",
        "color": "grey",
        "body": "\n".join(body),
    }


def build_week(plan, d, week_no, week):
    wd = d.weekday()
    start = date.fromisoformat(plan["meta"]["start_date"])
    total_weeks = plan["meta"]["total_weeks"]

    # 进度：按周计
    elapsed_days = (d - start).days
    done_weeks = min(total_weeks, elapsed_days // 7 + 1)
    pct = int(round(done_weeks / total_weeks * 100))
    bar = progress_bar(done_weeks, total_weeks)

    body = [
        f"🎯 **本周主题**：{week['title']}",
        f"📈 **本周目标**：{week['goal']}",
        "",
    ]

    if wd <= 4:
        tasks = week.get("weekday", [])
        if wd < len(tasks):
            body += ["**今天这一件**", f"{tasks[wd]}", ""]
            if wd + 1 < len(tasks):
                body += [f"*明天预告：{tasks[wd + 1]}*", ""]
        else:
            body += ["**今天这一件**", "本周工作日任务已排完，用今天补齐进度或复盘。", ""]
        body += ["⏱ 建议 45–60 分钟，通勤/午休可以只读资料不动手。"]
    else:
        lab = week.get("weekend", {}).get("sat" if wd == 5 else "sun", "")
        body += ["**周末动手（3–4 小时）**", f"{lab}", ""]
        body += ["⚠️ 周末的价值在于「跑通一次」，别只看文档。"]

    body += ["", "**本周资料**"]
    body += [f"· [{m['name']}]({m['url']})" for m in week.get("materials", [])]
    body += ["", "---", f"{bar} 第 {done_weeks}/{total_weeks} 周（{pct}%）"]

    return {
        "title": f"{plan['meta']['bot_name']} · 第 {week_no} 周",
        "subtitle": f"{d.isoformat()} {WEEKDAY_CN[wd]} · {week['phase']}",
        "color": PHASE_COLOR.get(week["phase"][0], "blue"),
        "body": "\n".join(body),
    }


def build_message(plan, d):
    """返回 (卡片内容 dict, 标签) ；None 表示今天不该发"""
    start = date.fromisoformat(plan["meta"]["start_date"])
    end = start + timedelta(weeks=plan["meta"]["total_weeks"])

    if d < start:
        return build_pre_phase(plan, d), "pre"
    if d >= end:
        return None, "after"

    week_no = (d - start).days // 7 + 1
    week = next((w for w in plan["weeks"] if w["week"] == week_no), None)
    if not week:
        return None, "missing"
    return build_week(plan, d, week_no, week), f"week{week_no}"


# ---------------------------------------------------------------- 卡片渲染

def to_card(msg, bot_name):
    """组装飞书 Webhook 交互卡片（schema 2.0 之前的稳定格式）"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": msg["color"],
            "title": {"tag": "plain_text", "content": msg["title"]},
            "subtitle": {"tag": "plain_text", "content": msg["subtitle"]},
        },
        "elements": [
            {"tag": "markdown", "content": msg["body"]},
        ],
    }


# ---------------------------------------------------------------- 发送

def sign_payload(secret, payload):
    ts = str(int(time.time()))
    key = f"{ts}\n{secret}".encode("utf-8")
    digest = hmac.new(key, digestmod=hashlib.sha256).digest()
    payload["timestamp"] = ts
    payload["sign"] = base64.b64encode(digest).decode("utf-8")
    return payload


def post(webhook, payload, secret=None, timeout=15):
    if secret:
        payload = sign_payload(secret, payload)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return False, raw
    code = body.get("code", body.get("StatusCode", -1))
    return code == 0, raw


# ---------------------------------------------------------------- 应用身份（私聊）

API_BASE = "https://open.feishu.cn/open-apis"


def api_post(url, payload, token=None, timeout=15):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    return json.loads(raw), raw


def get_tenant_token(app_id, app_secret, timeout=15):
    """换取 tenant_access_token，有效期约 2 小时"""
    body, raw = api_post(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    if body.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{raw[:400]}")
    return body["tenant_access_token"]


def send_dm(app_id, app_secret, receive_id, receive_id_type, card):
    """以应用身份发私聊卡片"""
    token = get_tenant_token(app_id, app_secret)
    payload = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        # 注意：content 必须是「JSON 字符串」，不是对象
        "content": json.dumps(card, ensure_ascii=False),
    }
    url = f"{API_BASE}/im/v1/messages?receive_id_type={receive_id_type}"
    body, raw = api_post(url, payload, token=token)
    return body.get("code") == 0, raw



# ---------------------------------------------------------------- 入口

def main():
    ap = argparse.ArgumentParser(description="进度条 —— 每日学习提醒")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不发送")
    ap.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD，用于试跑")
    args = ap.parse_args()

    plan = load_plan()
    d = date.fromisoformat(args.date) if args.date else date.today()

    msg, tag = build_message(plan, d)
    if msg is None:
        print(f"[skip] {d} 不在计划范围内（{tag}）")
        return 0

    card = to_card(msg, plan["meta"]["bot_name"])
    payload = {"msg_type": "interactive", "card": card}

    if args.dry_run:
        print(f"===== [{tag}] {d} =====")
        print(msg["title"])
        print(msg["subtitle"])
        print("-" * 40)
        print(msg["body"])
        print("-" * 40)
        print("payload bytes:", len(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
        return 0

    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()

    try:
        # 优先走「应用私聊」，其次回退到「群机器人 Webhook」
        if app_id and app_secret:
            receive_id = os.environ.get("FEISHU_RECEIVE_ID", "").strip()
            id_type = os.environ.get("FEISHU_RECEIVE_ID_TYPE", "union_id").strip()
            if not receive_id:
                print("[fail] 应用模式需要 FEISHU_RECEIVE_ID", file=sys.stderr)
                return 2
            ok, raw = send_dm(app_id, app_secret, receive_id, id_type, card)
        elif webhook:
            ok, raw = post(
                webhook,
                payload,
                os.environ.get("FEISHU_SECRET", "").strip() or None,
            )
        else:
            print(
                "[fail] 未配置发送方式：需要 FEISHU_APP_ID + FEISHU_APP_SECRET（私聊）"
                " 或 FEISHU_WEBHOOK（群机器人）",
                file=sys.stderr,
            )
            return 2
    except urllib.error.HTTPError as e:
        print(f"[fail] HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[fail] 请求异常：{e}", file=sys.stderr)
        return 1

    if ok:
        print(f"[ok] 已推送 {d} ({tag})")
        return 0
    print(f"[fail] 飞书返回：{raw[:400]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
