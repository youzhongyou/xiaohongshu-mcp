#!/usr/bin/env python3
"""
逐个获取小红书用户所有笔记的详情内容。
支持断点续传，中断后重新运行即可从上次位置继续。

用法:
  python3 scripts/download_notes_detail.py \
    --input /tmp/wufugui_all_notes.json \
    --output /tmp/wufugui_notes_detail.jsonl \
    --api http://localhost:18060

输出格式: JSONL (每行一条笔记详情)
"""

import argparse
import json
import os
import sys
import time
import random
import requests


def load_notes(input_path):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    notes = data["data"]["notes"]
    print(f"加载 {len(notes)} 条笔记")
    return notes


def load_progress(output_path):
    """读取已完成的笔记ID"""
    done = set()
    if not os.path.exists(output_path):
        return done
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                done.add(record["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def fetch_detail(api_base, feed_id, xsec_token, timeout=120):
    """调用 API 获取笔记详情"""
    url = f"{api_base}/api/v1/feeds/detail"
    payload = {
        "feed_id": feed_id,
        "xsec_token": xsec_token,
        "load_all_comments": False,
    }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="逐个下载小红书笔记详情")
    parser.add_argument("--input", required=True, help="笔记列表 JSON 文件路径")
    parser.add_argument("--output", required=True, help="输出 JSONL 文件路径")
    parser.add_argument("--api", default="http://localhost:18060", help="API 地址")
    parser.add_argument("--delay-min", type=float, default=3.0, help="最小请求间隔(秒)")
    parser.add_argument("--delay-max", type=float, default=5.0, help="最大请求间隔(秒)")
    parser.add_argument("--max-retries", type=int, default=3, help="单条失败最大重试次数")
    parser.add_argument("--max-errors", type=int, default=20, help="连续失败达到此数则停止")
    args = parser.parse_args()

    notes = load_notes(args.input)
    done = load_progress(args.output)
    print(f"已完成: {len(done)} 条, 剩余: {len(notes) - len(done)} 条")

    pending = [n for n in notes if n["id"] not in done]
    if not pending:
        print("全部完成!")
        return

    consecutive_errors = 0
    success_count = len(done)
    error_count = 0

    with open(args.output, "a", encoding="utf-8") as out_f:
        for i, note in enumerate(pending):
            feed_id = note["id"]
            xsec_token = note.get("xsec_token", "")
            title = note.get("title", "")

            progress = f"[{success_count + error_count + 1}/{len(notes)}]"
            print(f"{progress} 获取: {title[:30]}... (ID: {feed_id})", end=" ", flush=True)

            if not xsec_token:
                record = {"id": feed_id, "title": title, "error": "missing xsec_token"}
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()
                error_count += 1
                print("⚠️ 缺少 xsec_token")
                continue

            # 请求详情
            detail = None
            last_err = None
            for attempt in range(args.max_retries):
                try:
                    result = fetch_detail(args.api, feed_id, xsec_token)
                    if result.get("success"):
                        detail = result["data"]
                        break
                    else:
                        last_err = result.get("error", "unknown error")
                except requests.exceptions.Timeout:
                    last_err = "timeout"
                except requests.exceptions.ConnectionError:
                    last_err = "connection_error"
                except Exception as e:
                    last_err = str(e)

                if attempt < args.max_retries - 1:
                    time.sleep(5)

            if detail:
                record = {"id": feed_id, "title": title, "detail": detail}
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()
                success_count += 1
                consecutive_errors = 0
                print("✓")
            else:
                record = {"id": feed_id, "title": title, "error": last_err}
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()
                error_count += 1
                consecutive_errors += 1
                print(f"✗ ({last_err})")

            if consecutive_errors >= args.max_errors:
                print(f"\n连续 {args.max_errors} 次失败，停止运行。")
                print("请检查服务状态后重新运行脚本（自动续传）。")
                break

            # 请求间隔
            if i < len(pending) - 1:
                delay = random.uniform(args.delay_min, args.delay_max)
                time.sleep(delay)

    print(f"\n完成! 成功: {success_count}, 失败: {error_count}, 总计: {len(notes)}")
    print(f"结果保存在: {args.output}")


if __name__ == "__main__":
    main()
