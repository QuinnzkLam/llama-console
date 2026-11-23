# LlamaDeck 遷移（核彈機 / Windows）

品牌由 NLM 改為 LlamaDeck，exe 名同 icon 都換咗。按以下次序上機：

1. **重建 dist**：喺 `D:\llama-console` 執行
   `.venv\Scripts\pyinstaller.exe --distpath dist --workpath build -y scripts\LlamaDeck_v8.spec`
   完成後確認 `dist\LlamaDeck.exe` 存在（新 icon 已由 spec 由 `assets\LlamaDeck.ico` 嵌入）。

2. **刪舊桌面快捷方式**：移除所有指向 `dist\NLM.exe` 嘅桌面 / 工作列快捷方式。

3. **起新快捷方式**：目標指向 `D:\llama-console\dist\LlamaDeck.exe`，圖標用 `D:\llama-console\assets\LlamaDeck.ico`。

4. **舊 schtask 唔使郁**：已排程嘅工作保持原狀，唔需要改動（另有 W3 卡處理）。
