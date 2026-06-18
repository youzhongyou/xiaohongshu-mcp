#!/usr/bin/env python3
"""
搜索真实评测工具：搜索关键词后自动过滤疑似广告内容，只保留真实评测。

广告评分规则：
  - @厂家/品牌: +3分/个
  - 自带链接: +5分
  - hashtag过多(>5): +1分/个（超出部分）
  - emoji过多(>10): +1分/个（超出部分）
  - 广告tag: +10分

总分 ≤ 5 判定为真实评测。

用法:
  python3 scripts/search_authentic_reviews.py \
    --keyword "扫地机器人评测" \
    --api http://localhost:18060 \
    --threshold 5 \
    --with-detail \
    --with-comments \
    --output ~/data/xiaohongshu/reviews/扫地机器人.json
"""

import argparse
import json
import os
import re
import sys
import time
import random
import requests


# 广告相关标识
AD_TAGS = [
    "赞助", "广告", "合作", "品牌合作", "商业合作",
    "推广", "恰饭", "paid", "sponsored", "ad",
    "品牌方", "供稿", "邀请", "体验官", "测评官",
]

# emoji 正则（匹配大部分 Unicode emoji）
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # 表情
    "\U0001F300-\U0001F5FF"  # 符号和图标
    "\U0001F680-\U0001F6FF"  # 交通和地图
    "\U0001F1E0-\U0001F1FF"  # 旗帜
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # 补充表情
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)

# 小红书表情标记 [xxxR] [xxxH]
XHS_EMOJI_PATTERN = re.compile(r"\[[^\]]{1,10}[RH]\]")


def make_note_url(feed_id, xsec_token):
    """生成笔记链接"""
    if not feed_id:
        return ""
    url = f"https://www.xiaohongshu.com/explore/{feed_id}"
    if xsec_token:
        url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"
    return url


def calculate_ad_score(title, desc):
    """计算广告评分，分数越高越可能是广告"""
    text = f"{title}\n{desc}"
    score = 0
    details = []

    # 1. @厂家/品牌
    at_mentions = re.findall(r"@\S+", text)
    if at_mentions:
        points = len(at_mentions) * 3
        score += points
        details.append(f"@提及({len(at_mentions)}个): +{points}")

    # 2. 自带链接
    urls = re.findall(r"https?://\S+|(?:淘宝|京东|拼多多|天猫).*?链接|复制.*?打开|点击.*?购买", text)
    if urls:
        score += 5
        details.append(f"含链接: +5")

    # 3. hashtag 过多
    hashtags = re.findall(r"#[^#\[]+?\[话题\]#|#[^#]+?#", text)
    if len(hashtags) > 5:
        excess = len(hashtags) - 5
        score += excess
        details.append(f"hashtag({len(hashtags)}个,超{excess}): +{excess}")

    # 4. emoji 过多
    unicode_emojis = EMOJI_PATTERN.findall(text)
    xhs_emojis = XHS_EMOJI_PATTERN.findall(text)
    total_emojis = len(unicode_emojis) + len(xhs_emojis)
    if total_emojis > 10:
        excess = total_emojis - 10
        score += excess
        details.append(f"emoji({total_emojis}个,超{excess}): +{excess}")

    # 5. 广告 tag
    text_lower = text.lower()
    found_ad_tags = [tag for tag in AD_TAGS if tag.lower() in text_lower]
    if found_ad_tags:
        score += 10
        details.append(f"广告标识({','.join(found_ad_tags)}): +10")

    return score, details


def search_feeds(api_base, keyword, filters=None, timeout=120):
    """搜索笔记列表"""
    url = f"{api_base}/api/v1/feeds/search"
    payload = {"keyword": keyword}
    if filters:
        payload["filters"] = filters
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_feed_detail(api_base, feed_id, xsec_token, load_comments=False, timeout=120):
    """获取笔记详情（可选加载评论）"""
    url = f"{api_base}/api/v1/feeds/detail"
    payload = {
        "feed_id": feed_id,
        "xsec_token": xsec_token,
        "load_all_comments": load_comments,
    }
    if load_comments:
        payload["comment_config"] = {
            "max_comment_items": 30,
            "scroll_speed": "fast",
        }
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def extract_comments(detail_data):
    """从详情数据中提取评论列表"""
    comments = []
    try:
        comment_list = detail_data.get("data", {}).get("comments", {}).get("list", [])
        for c in comment_list:
            comment = {
                "author": c.get("userInfo", {}).get("nickname", ""),
                "content": c.get("content", ""),
                "likes": c.get("likeCount", "0"),
                "sub_comments": [],
            }
            for sub in c.get("subComments", []):
                comment["sub_comments"].append({
                    "author": sub.get("userInfo", {}).get("nickname", ""),
                    "content": sub.get("content", ""),
                    "likes": sub.get("likeCount", "0"),
                })
            comments.append(comment)
    except (TypeError, AttributeError):
        pass
    return comments


def main():
    parser = argparse.ArgumentParser(description="搜索真实评测（过滤广告）")
    parser.add_argument("--keyword", required=True, help="搜索关键词")
    parser.add_argument("--api", default="http://localhost:18060", help="API 地址")
    parser.add_argument("--threshold", type=int, default=5, help="广告评分阈值，低于此分为真实评测")
    parser.add_argument("--output", help="输出 JSON 文件路径（自动创建目录）")
    parser.add_argument("--with-detail", action="store_true", help="获取正文再评分（更准确但更慢）")
    parser.add_argument("--with-comments", action="store_true", help="抓取评论（评论中有更真实的评价）")
    parser.add_argument("--delay", type=float, default=3.0, help="获取详情时的请求间隔(秒)")
    parser.add_argument("--sort-by", default="", help="排序: 综合|最新|最多点赞|最多评论|最多收藏")
    args = parser.parse_args()

    # with-comments 隐含 with-detail
    if args.with_comments:
        args.with_detail = True

    print(f"🔍 搜索关键词: {args.keyword}")
    print(f"📏 广告阈值: ≤{args.threshold} 为真实评测")
    if args.with_detail:
        print(f"📄 模式: 精准（获取正文{'+ 评论' if args.with_comments else ''}）")
    print()

    # 搜索
    filters = {}
    if args.sort_by:
        filters["sort_by"] = args.sort_by

    try:
        result = search_feeds(args.api, args.keyword, filters if filters else None)
    except Exception as e:
        print(f"❌ 搜索失败: {e}")
        sys.exit(1)

    if not result.get("success"):
        print(f"❌ 搜索失败: {result.get('error', 'unknown')}")
        sys.exit(1)

    feeds = result["data"]["feeds"]
    print(f"📋 搜索到 {len(feeds)} 条笔记")
    print()

    # 评分
    authentic = []
    ads = []

    for i, feed in enumerate(feeds):
        feed_id = feed.get("id", "")
        xsec_token = feed.get("xsecToken", "")
        note_card = feed.get("noteCard", {})
        title = note_card.get("displayTitle", "")
        nickname = note_card.get("user", {}).get("nickname", "")
        likes = note_card.get("interactInfo", {}).get("likedCount", "0")

        desc = ""
        comments = []
        note_url = make_note_url(feed_id, xsec_token)

        # 获取详情和评论
        if args.with_detail and feed_id and xsec_token:
            print(f"  [{i+1}/{len(feeds)}] {title[:30]}...", end=" ", flush=True)
            try:
                detail_result = get_feed_detail(
                    args.api, feed_id, xsec_token,
                    load_comments=args.with_comments,
                )
                if detail_result.get("success"):
                    detail_data = detail_result["data"]
                    note_data = detail_data.get("data", {}).get("note", {})
                    desc = note_data.get("desc", "")
                    if args.with_comments:
                        comments = extract_comments(detail_data)
                    print("✓")
                else:
                    print("✗")
            except Exception as e:
                print(f"⚠️ {e}")

            if i < len(feeds) - 1:
                time.sleep(args.delay + random.uniform(0, 1))

        # 计算广告评分
        score, details = calculate_ad_score(title, desc)

        item = {
            "id": feed_id,
            "title": title,
            "url": note_url,
            "author": nickname,
            "likes": likes,
            "ad_score": score,
            "ad_details": details,
            "desc": desc[:500] if desc else "",
            "xsec_token": xsec_token,
        }

        if comments:
            item["comments"] = comments
            item["comment_count"] = len(comments)

        if score <= args.threshold:
            authentic.append(item)
        else:
            ads.append(item)

    # 输出结果
    print()
    print(f"{'='*60}")
    print(f"✅ 真实评测: {len(authentic)} 条 (广告分 ≤ {args.threshold})")
    print(f"🚫 疑似广告: {len(ads)} 条 (广告分 > {args.threshold})")
    print(f"{'='*60}")
    print()

    if authentic:
        print("✅ 真实评测列表:")
        print("-" * 60)
        for i, item in enumerate(authentic):
            print(f"  {i+1}. {item['title']}")
            print(f"     作者: {item['author']}  👍{item['likes']}  广告分: {item['ad_score']}")
            print(f"     链接: {item['url']}")
            if item["ad_details"]:
                print(f"     评分明细: {'; '.join(item['ad_details'])}")
            if item["desc"]:
                print(f"     摘要: {item['desc'][:100]}...")
            if item.get("comments"):
                print(f"     评论({item['comment_count']}条):")
                for c in item["comments"][:3]:
                    print(f"       - {c['author']}: {c['content'][:60]}")
            print()

    if ads:
        print()
        print("🚫 疑似广告列表:")
        print("-" * 60)
        for i, item in enumerate(ads):
            print(f"  {i+1}. {item['title']}")
            print(f"     作者: {item['author']}  👍{item['likes']}  广告分: {item['ad_score']}")
            print(f"     链接: {item['url']}")
            print(f"     评分明细: {'; '.join(item['ad_details'])}")
            print()

    # 保存结果
    if args.output:
        # 自动创建目录
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        output_data = {
            "keyword": args.keyword,
            "threshold": args.threshold,
            "total": len(feeds),
            "authentic_count": len(authentic),
            "ad_count": len(ads),
            "authentic": authentic,
            "ads": ads,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 结果已保存到: {args.output}")


if __name__ == "__main__":
    main()
