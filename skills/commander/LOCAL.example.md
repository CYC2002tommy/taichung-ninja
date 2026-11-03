# 台中黑哥：本機層（範本）

安裝程式會把這份複製成 `~/.claude/skills/commander/LOCAL.md`。那份只留在你的電腦，不要推上 git。
它會覆蓋 `SKILL.md` 裡不一樣的地方，所以個人化的東西都寫在這裡。

## 常設派工規則

寫成「什麼情況 → 叫哪個技能」，一行一條。例如：

1. 遙測研究 → `hermes-domain:remote-sensing-agentic-workflow`。
2. 機器學習問題 → `k-dense-science:scikit-learn`。

## 人設（選用）

如果你替某些技能取了暱稱（例如審稿人、領域顧問），在這裡列出暱稱和技能 ID 的對應。
同時點名好幾個人設時，就當成顧問小組：每個人用自己的技能給意見，Claude 整合後再決定。

## 授權（不用 grill 的範圍）

列出你授權 Claude 直接決定的專案或情境。
例如：「X 專案，除非我自己提，否則你直接決定」。
對應的 regex 寫在 `~/.claude/commander/config.json` 的 `delegated_regex`。

## 路徑

- 非 git 專案的規格放哪裡（例如筆記軟體的專案資料夾）。
- 其他本機路徑。
