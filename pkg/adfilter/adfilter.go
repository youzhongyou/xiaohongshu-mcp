package adfilter

import (
	"regexp"
	"strings"
)

// 广告标识关键词
var adTags = []string{
	"赞助", "广告", "合作", "品牌合作", "商业合作",
	"推广", "恰饭", "paid", "sponsored",
	"品牌方", "供稿", "邀请", "体验官", "测评官",
}

var (
	atMentionRegex = regexp.MustCompile(`@\S+`)
	urlRegex       = regexp.MustCompile(`https?://\S+`)
	buyLinkRegex   = regexp.MustCompile(`(?:淘宝|京东|拼多多|天猫|购买|下单|链接|复制.*打开)`)
	hashtagRegex   = regexp.MustCompile(`#[^#\[\]]+?\[话题\]#|#[^#]+?#`)
	emojiRegex     = regexp.MustCompile(`[\x{1F600}-\x{1F64F}]|[\x{1F300}-\x{1F5FF}]|[\x{1F680}-\x{1F6FF}]|[\x{1F1E0}-\x{1F1FF}]|[\x{1F900}-\x{1F9FF}]|[\x{1FA00}-\x{1FAFF}]|[\x{2600}-\x{26FF}]|[\x{2700}-\x{27BF}]`)
	xhsEmojiRegex  = regexp.MustCompile(`\[[^\]]{1,10}[RH]\]`)
)

// ScoreDetail 评分明细
type ScoreDetail struct {
	Dimension   string `json:"dimension"`
	Points      int    `json:"points"`
	Description string `json:"description"`
}

// AdScore 广告评分结果
type AdScore struct {
	Score   int           `json:"score"`
	Details []ScoreDetail `json:"details"`
}

// Calculate 计算广告评分
func Calculate(title, desc string) AdScore {
	text := title + "\n" + desc
	var score int
	var details []ScoreDetail

	// 1. @提及 (+3/个)
	atMentions := atMentionRegex.FindAllString(text, -1)
	if len(atMentions) > 0 {
		points := len(atMentions) * 3
		score += points
		details = append(details, ScoreDetail{
			Dimension:   "at_mention",
			Points:      points,
			Description: strings.Join(atMentions, ", "),
		})
	}

	// 2. 链接 (+5)
	hasURL := urlRegex.MatchString(text) || buyLinkRegex.MatchString(text)
	if hasURL {
		score += 5
		details = append(details, ScoreDetail{
			Dimension:   "link",
			Points:      5,
			Description: "含购买链接或URL",
		})
	}

	// 3. hashtag过多 (>5时 +1/个超出部分)
	hashtags := hashtagRegex.FindAllString(text, -1)
	if len(hashtags) > 5 {
		excess := len(hashtags) - 5
		score += excess
		details = append(details, ScoreDetail{
			Dimension:   "hashtag",
			Points:      excess,
			Description: strings.Join(hashtags, " "),
		})
	}

	// 4. emoji过多 (>10时 +1/个超出部分)
	unicodeEmojis := emojiRegex.FindAllString(text, -1)
	xhsEmojis := xhsEmojiRegex.FindAllString(text, -1)
	totalEmojis := len(unicodeEmojis) + len(xhsEmojis)
	if totalEmojis > 10 {
		excess := totalEmojis - 10
		score += excess
		details = append(details, ScoreDetail{
			Dimension:   "emoji",
			Points:      excess,
			Description: "emoji数量过多",
		})
	}

	// 5. 广告tag (+10)
	textLower := strings.ToLower(text)
	var foundTags []string
	for _, tag := range adTags {
		if strings.Contains(textLower, strings.ToLower(tag)) {
			foundTags = append(foundTags, tag)
		}
	}
	if len(foundTags) > 0 {
		score += 10
		details = append(details, ScoreDetail{
			Dimension:   "ad_tag",
			Points:      10,
			Description: strings.Join(foundTags, ", "),
		})
	}

	return AdScore{Score: score, Details: details}
}
