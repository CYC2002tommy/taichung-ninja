# 台中黑哥 (Taichung Ninja)

Claude Code 的常駐指揮官。他一直在場，看你交代的任務和 Claude 正要做的動作，自動把對的技能派上場，一次可以派好幾個。他也會攔住 Claude，不讓它替你做你沒授權的決定。

*An always-on commander for Claude Code. It dispatches skills from what you ask and from what Claude is about to do, gates decisions you have not delegated through a grilling interview, chains spec → tickets → implement → review, has every output file reviewed first, and sizes agent fan-outs from live quota.*

## 他會做什麼

前四項由 hook 強制執行；第 5、6 項是寫在技能裡的指示，要靠 Claude 自己照做，hook 不會強制。

1. **每一回合都提醒他出場**（hook）：每則訊息都會注入黑哥那一行，要求回覆第一行寫 `黑哥派工：…`、`黑哥：這題我自己顧`、`黑哥算過：…` 或 `黑哥攔下：…`。要不要照寫還是看 Claude，不過實務上很穩。
2. **看你的話派工**（hook）：你的訊息命中 `skill_routes.json` 裡的關鍵字，就會點名對應的技能，最多 5 個。
3. **看 Claude 的動作派工**（hook）：Claude 要寫 sklearn、統計檢定或畫圖程式、改 `.tex`、跑 MATLAB 匯出、讀 PDF 時，會先提醒它帶上對應的技能。
   - 會先擋一次的只有兩類：讀 PDF（暫存資料夾裡自己的渲染檔除外），以及新建 docx／pptx 產生器。
   - 其他都只提醒。
4. **檔案輸出前先審**（hook）：Claude 要輸出 docx、pptx、xlsx、pdf，或把檔案複製到 Downloads 時，會先擋一次，要求載入審稿技能。
   - 審稿技能在設定檔的 `output_review_skill` 設定，預設 `hermes-research:remi`，填 `null` 就關掉這道關。
   - 同一個對話只擋第一次。
5. **不讓 Claude 替你拍板**（偵測靠 hook，後續靠技能指示）：Claude 說出「我先採用預設」「我選了」「我先替你決定」這類話時，下一個動作會被擋一次。Claude 接下來有兩條路：
   - 這件事已經授權過，就用一行說明依據，然後重試放行。授權來源有三種：設定檔 `delegated_regex` 命中的專案、你在對話中說過「你決定／照建議」、專案記憶。
   - 沒有授權，就改用 `grilling` 問你。問完之後依技能指示接 to-spec → to-tickets → implement → code-review。
6. **看額度決定開幾個代理**（技能指示）：開代理之前先讀即時額度。每個代理估 5 小時額度的 12%，最多開 4 個。
   - 即時額度只有 **Claude 桌面版**讀得到（`get_usage`）。
   - CLI 讀不到額度，技能會改成最多開 2 個。

## 需求

- Claude Code（桌面版或 CLI）。
- Python 3.9 以上，只用標準函式庫。
- 選用但建議裝的技能：`grilling`、`to-spec`、`to-tickets`、`implement`、`implement-spec`、`tdd`、`markitdown`，以及審稿技能。
- `SKILL.md` 裡的技能表與 `hooks/skill_routes.example.json`，用的是作者自己的技能組，例如 `hermes-*`、`k-dense-science:*`。沒裝的技能，黑哥點名了也不會發生任何事。請把派工規則改成你自己有的技能。

## 安裝

```bash
git clone https://github.com/CYC2002tommy/taichung-ninja.git
```

```bash
cd taichung-ninja
```

```bash
python install.py
```

裝完後：

1. 完全關掉 Claude Code 再打開。
2. 驗收：最後應該出現 `0 failure(s)`。`WARN` 是你沒裝的技能，可以忽略。macOS／Linux：

```bash
python ~/.claude/hooks/test_commander_dispatch.py
```

Windows（PowerShell）：

```powershell
python "$env:USERPROFILE\.claude\hooks\test_commander_dispatch.py"
```

- **兩個帳號或多個 Claude 設定資料夾**：用 `python install.py --claude-dir <資料夾>`，每個資料夾裝一次。
- **先看會改什麼**：加上 `--dry-run`。
- **安裝程式會做的事**：
  - 原有的 `settings.json` 會先備份成 `settings.json.bak-<時間>`。
  - 只會加入三個 hook（UserPromptSubmit、PreToolUse、Stop），另外設定 `SLASH_COMMAND_TOOL_CHAR_BUDGET=65000`。這個預算很重要：技能清單預設上限約 30,000 字，技能一多，大部分技能的說明會被默默截掉，自動觸發就變差。
  - 會在 `CLAUDE.md` 尾端加一段有標記的黑哥區塊，讓他在開新對話和壓縮上下文後都在場。重複安裝不會重複加。加上 `--no-claude-md` 可以跳過。

## 個人化（三個檔，都只留在你的電腦）

| 檔案 | 放什麼 |
|---|---|
| `~/.claude/commander/config.json` | `owner`：訊息裡怎麼稱呼你。`output_review_skill`：輸出前用哪個審稿技能，填 `null` 就關掉這道關。`delegated_regex`：授權專案，命中就不 grill。`router_line`：每回合黑哥那一行的內容。`private_terms`：絕不能出現在共用檔案裡的字，測試會檢查。 |
| `~/.claude/skills/commander/LOCAL.md` | 你的常設派工規則、人設暱稱、授權範圍、路徑。範本是 `skills/commander/LOCAL.example.md`。 |
| `~/.claude/hooks/skill_routes.json` | 關鍵字路由。範本是 `hooks/skill_routes.example.json`。改成你自己的技能和講話習慣。 |

`.gitignore` 已經排除這三種檔案。

## 檔案

```
skills/commander/SKILL.md          黑哥的方法（公開）
skills/commander/LOCAL.example.md  本機層範本
hooks/commander_dispatch.py        動作派工、輸出審稿關、決定關卡（PreToolUse + Stop）
hooks/skill_router.py              關鍵字路由＋每回合的黑哥那一行（UserPromptSubmit）
hooks/skill_routes.example.json    路由範例
hooks/test_commander_dispatch.py   測試
hooks/replay_commander_dispatch.py 用你過去的對話回放，看會提醒、會擋幾次
install.py                         安裝程式
config.example.json                設定範例
```

## 設計重點

- **出錯就放行**：hook 內部出任何錯，都不輸出、直接放行，不會卡住你的工作。
- **輸出是純 ASCII JSON**：用 `\u` 跳脫，Windows 的任何編碼頁都不會出現亂碼。
- **狀態分開記**：依對話紀錄的路徑加上子代理 ID 分開，子代理不會互相干擾。子代理也不跑決定關卡。
- **提醒有上限**：同一個技能在同一個對話只提醒一次；每次呼叫最多提醒 2 個技能，每個對話最多 6 個。
- **作者實測**：回放 26,000 次工具呼叫，只提醒的有 0.31%，擋一次的有 0.13%。決定關卡在 9,000 段回覆裡命中 0.15%。

## 授權

尚未指定開源授權。歡迎實驗室成員安裝使用；要轉載或改作發布，請先聯絡作者。

## 移除

- **拿掉 hook**：刪掉 `settings.json` 裡指向 `commander_dispatch.py` 和 `skill_router.py` 的 hook，或用安裝時留下的 `.bak` 還原。
- **拿掉技能**：刪掉 `~/.claude/skills/commander/`。
- **拿掉 CLAUDE.md 區塊**：刪掉 `CLAUDE.md` 裡 `<!-- taichung-ninja:start -->` 到 `<!-- taichung-ninja:end -->` 之間的內容。
