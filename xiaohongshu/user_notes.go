package xiaohongshu

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"time"

	"github.com/go-rod/rod"
	"github.com/sirupsen/logrus"
)

// UserNotesAction 获取用户所有笔记（通过滚动加载）
type UserNotesAction struct {
	page *rod.Page
}

func NewUserNotesAction(page *rod.Page) *UserNotesAction {
	pp := page.Timeout(15 * time.Minute)
	return &UserNotesAction{page: pp}
}

// GetAllNotes 获取用户所有笔记列表（通过滚动分页加载）
func (u *UserNotesAction) GetAllNotes(ctx context.Context, userID, xsecToken string) (*UserProfileResponse, error) {
	page := u.page.Context(ctx)

	profileURL := makeUserProfileURL(userID, xsecToken)
	page.MustNavigate(profileURL)
	page.MustWaitStable()
	page.MustWait(`() => window.__INITIAL_STATE__ !== undefined`)

	// 提取用户基本信息
	userDataResult := page.MustEval(`() => {
		if (window.__INITIAL_STATE__ &&
		    window.__INITIAL_STATE__.user &&
		    window.__INITIAL_STATE__.user.userPageData) {
			const userPageData = window.__INITIAL_STATE__.user.userPageData;
			const data = userPageData.value !== undefined ? userPageData.value : userPageData._value;
			if (data) {
				return JSON.stringify(data);
			}
		}
		return "";
	}`).String()

	if userDataResult == "" {
		return nil, fmt.Errorf("user.userPageData.value not found in __INITIAL_STATE__")
	}

	var userPageData struct {
		Interactions []UserInteractions `json:"interactions"`
		BasicInfo    UserBasicInfo      `json:"basicInfo"`
	}
	if err := json.Unmarshal([]byte(userDataResult), &userPageData); err != nil {
		return nil, fmt.Errorf("解析用户信息失败: %w", err)
	}

	// 滚动加载所有笔记
	feeds, err := u.scrollLoadAllNotes(page)
	if err != nil {
		return nil, fmt.Errorf("加载笔记列表失败: %w", err)
	}

	return &UserProfileResponse{
		UserBasicInfo: userPageData.BasicInfo,
		Interactions:  userPageData.Interactions,
		Feeds:         feeds,
	}, nil
}

// scrollLoadAllNotes 滚动到底部加载用户所有笔记，从 DOM 中提取数据
func (u *UserNotesAction) scrollLoadAllNotes(page *rod.Page) ([]Feed, error) {
	const (
		maxStagnant = 15
		maxAttempts = 2000
	)

	var lastCount int
	stagnant := 0

	for i := 0; i < maxAttempts; i++ {
		currentCount := u.getNoteCount(page)

		if currentCount > lastCount {
			if currentCount%100 < 30 || currentCount-lastCount > 10 {
				logrus.Infof("笔记加载: %d -> %d (+%d)", lastCount, currentCount, currentCount-lastCount)
			}
			lastCount = currentCount
			stagnant = 0
		} else {
			stagnant++
		}

		// 检测是否到底
		if u.checkNotesEnd(page) {
			logrus.Infof("已到达用户笔记底部，共 %d 条", currentCount)
			break
		}

		if stagnant >= maxStagnant {
			// 尝试多种滚动方式
			page.MustEval(`() => {
				// 方式1: 滚动到最后一个笔记元素
				const items = document.querySelectorAll('section.note-item');
				if (items.length > 0) {
					items[items.length - 1].scrollIntoView({behavior: 'instant', block: 'end'});
				}
				// 方式2: window 滚动到底
				window.scrollTo(0, document.body.scrollHeight);
			}`)
			time.Sleep(2 * time.Second)

			newCount := u.getNoteCount(page)
			if newCount > lastCount {
				lastCount = newCount
				stagnant = 0
				continue
			}
			logrus.Infof("笔记数量不再增加，停止滚动，共 %d 条", currentCount)
			break
		}

		// 触发滚动：使用多种方式确保触发懒加载
		page.MustEval(`() => {
			// 滚动 window
			window.scrollBy(0, window.innerHeight);

			// 同时触发滚轮事件到可能的滚动容器
			const containers = [
				document.querySelector('.user-profile-container'),
				document.querySelector('#userPostedNotes'),
				document.querySelector('[class*="note-container"]'),
				document.documentElement,
			];
			for (const container of containers) {
				if (!container) continue;
				const evt = new WheelEvent('wheel', {
					deltaY: 500,
					deltaMode: 0,
					bubbles: true,
					cancelable: true,
					view: window
				});
				container.dispatchEvent(evt);
			}
		}`)
		time.Sleep(time.Duration(400+rand.Intn(200)) * time.Millisecond)
	}

	// 从 __INITIAL_STATE__ 提取所有已加载的笔记
	return u.extractAllNotes(page)
}

// getNoteCount 获取 __INITIAL_STATE__ 中已加载的笔记数量（虚拟列表只渲染可视区域内的 DOM）
func (u *UserNotesAction) getNoteCount(page *rod.Page) int {
	count := page.MustEval(`() => {
		if (window.__INITIAL_STATE__ &&
		    window.__INITIAL_STATE__.user &&
		    window.__INITIAL_STATE__.user.notes) {
			const notes = window.__INITIAL_STATE__.user.notes;
			const data = notes.value !== undefined ? notes.value : notes._value;
			if (Array.isArray(data)) {
				let total = 0;
				for (const group of data) {
					if (Array.isArray(group)) total += group.length;
				}
				return total;
			}
		}
		return 0;
	}`).Int()
	return count
}

// checkNotesEnd 检查是否已加载完所有笔记（不依赖滚动位置，只检查 DOM 中的明确标识）
func (u *UserNotesAction) checkNotesEnd(page *rod.Page) bool {
	result := page.MustEval(`() => {
		// 检查明确的"到底"标识元素
		const endSigns = document.querySelectorAll('.note-container .end-container, .reds-cursor-end');
		for (const el of endSigns) {
			if (el.offsetHeight > 0) return true;
		}
		return false;
	}`).Bool()

	return result
}

// extractAllNotes 从 __INITIAL_STATE__ 中提取所有已加载的笔记数据
func (u *UserNotesAction) extractAllNotes(page *rod.Page) ([]Feed, error) {
	notesResult := page.MustEval(`() => {
		if (window.__INITIAL_STATE__ &&
		    window.__INITIAL_STATE__.user &&
		    window.__INITIAL_STATE__.user.notes) {
			const notes = window.__INITIAL_STATE__.user.notes;
			const data = notes.value !== undefined ? notes.value : notes._value;
			if (data) {
				return JSON.stringify(data);
			}
		}
		return "";
	}`).String()

	if notesResult == "" {
		return nil, fmt.Errorf("无法提取笔记数据")
	}

	var notesFeeds [][]Feed
	if err := json.Unmarshal([]byte(notesResult), &notesFeeds); err != nil {
		return nil, fmt.Errorf("解析笔记数据失败: %w", err)
	}

	// 去重
	seen := make(map[string]bool)
	var feeds []Feed
	for _, group := range notesFeeds {
		for _, feed := range group {
			if !seen[feed.ID] {
				seen[feed.ID] = true
				feeds = append(feeds, feed)
			}
		}
	}

	logrus.Infof("从 __INITIAL_STATE__ 提取到 %d 条唯一笔记", len(feeds))
	return feeds, nil
}
