# 下载用户笔记使用手册

## 前置条件

1. 编译并启动服务（非 headless 模式，首次需要扫码登录）：

```bash
cd /Users/jun.sun/tools/xiaohongshu-mcp

# 编译
/opt/homebrew/Cellar/go/1.26.4/bin/go build -o xiaohongshu-mcp .

# 启动服务
./xiaohongshu-mcp -headless=false -bin="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" -port=:18060
```

2. 首次使用需要登录（扫码）：

```bash
/opt/homebrew/Cellar/go/1.26.4/bin/go run ./cmd/login/ -bin="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

## 步骤一：获取用户 ID 和 xsec_token

通过搜索用户名获取：

```bash
curl -s --max-time 120 -X POST http://localhost:18060/api/v1/feeds/search \
  -H "Content-Type: application/json" \
  -d '{"keyword": "用户昵称"}' | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
for feed in data['data']['feeds'][:5]:
    card = feed['noteCard']
    if card['user']['userId']:
        print(f'用户: {card[\"user\"][\"nickname\"]}')
        print(f'  user_id: {card[\"user\"][\"userId\"]}')
        print(f'  xsec_token: {feed[\"xsecToken\"]}')
        print()
"
```

## 步骤二：下载笔记列表

```bash
curl -s --max-time 600 -X POST http://localhost:18060/api/v1/user/notes/download \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "用户ID",
    "xsec_token": "访问令牌",
    "with_detail": false
  }' -o ~/data/xiaohongshu/用户名_all_notes.json
```

- `with_detail: false` 只获取列表（快，几分钟）
- `with_detail: true` 同时获取每篇详情（慢，不推荐大量笔记使用）

## 步骤三：批量获取笔记详情

使用 `download_notes_detail.py` 脚本逐条获取详情（支持断点续传）：

```bash
python3 scripts/download_notes_detail.py \
  --input ~/data/xiaohongshu/用户名_all_notes.json \
  --output ~/data/xiaohongshu/用户名_notes_detail.jsonl \
  --api http://localhost:18060 \
  --delay-min 8 --delay-max 15
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input` | 必填 | 步骤二生成的笔记列表 JSON |
| `--output` | 必填 | 输出文件路径（JSONL 格式） |
| `--api` | http://localhost:18060 | 服务地址 |
| `--delay-min` | 3.0 | 最小请求间隔（秒） |
| `--delay-max` | 5.0 | 最大请求间隔（秒） |
| `--max-retries` | 3 | 单条失败最大重试次数 |
| `--max-errors` | 20 | 连续失败达到此数则停止 |

### 注意事项

- **避免限流**：建议 `--delay-min 8 --delay-max 15`，间隔越大越安全
- **断点续传**：中断后重新运行同一命令即可，自动跳过已完成的笔记
- **耗时预估**：间隔 10 秒 × 4000 条 ≈ 11 小时
- **建议后台运行**：

```bash
nohup python3 scripts/download_notes_detail.py \
  --input ~/data/xiaohongshu/用户名_all_notes.json \
  --output ~/data/xiaohongshu/用户名_notes_detail.jsonl \
  --api http://localhost:18060 \
  --delay-min 8 --delay-max 15 --max-errors 50 \
  > ~/data/xiaohongshu/download_progress.log 2>&1 &
```

### 查看进度

```bash
# 已完成数量
wc -l ~/data/xiaohongshu/用户名_notes_detail.jsonl

# 最近日志
tail -5 ~/data/xiaohongshu/download_progress.log
```

### 验证限流是否解除

```bash
curl -s --max-time 60 -X POST http://localhost:18060/api/v1/feeds/detail \
  -H "Content-Type: application/json" \
  -d '{"feed_id": "笔记ID", "xsec_token": "令牌", "load_all_comments": false}' \
  | python3 -c "import json,sys; data=json.loads(sys.stdin.read()); print('✅ 限流已解除' if data.get('success') else '❌ 仍被限流')"
```

## 输出数据格式

### 笔记列表 (JSON)

```json
{
  "data": {
    "user_basic_info": {"nickname": "...", "desc": "..."},
    "total_notes": 4752,
    "notes": [
      {"id": "...", "title": "...", "type": "normal", "xsec_token": "...", "likes": "123"}
    ]
  }
}
```

### 笔记详情 (JSONL，每行一条)

```json
{"id": "...", "title": "...", "detail": {"data": {"note": {"title": "...", "desc": "正文内容", "imageList": [...]}, "comments": {...}}}}
```

关键字段：
- `detail.data.note.desc` — 笔记正文
- `detail.data.note.imageList` — 图片列表
- `detail.data.comments.list` — 评论列表
