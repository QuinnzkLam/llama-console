# Hedanji-Llama-Start 降權：根治停服 UAC 彈窗

## 背景（UAC 根因）

- 舊 `Hedanji-Llama-Start`（唔喺倉庫）用 `RunLevel=HighestAvailable` 起 llama-server → 進程屬 **High integrity**。
- GUI `LlamaDeck.exe` 以普通用戶 **Medium integrity** 運行。
- Windows 完整性機制：Medium 嘅 `taskkill /F` 對 High 進程返 `Access Denied`。
- `src/llama_console_v2/backend/llama_cpp.py::stop()` 先做普通 taskkill，輪詢 ~8s，仍有殘留先 call `_elevated_kill_llama()`（`Start-Process -Verb RunAs`）→ **彈 UAC**。呢段邏輯唔改。
- llama-server 只綁 `127.0.0.1:18605`（高端口，非特權）同讀寫 `D:\llama-console`，根本唔需要 admin。
- **根治** = 排程工作降權做 `LeastPrivilege`：llama-server 落 Medium integrity，GUI 可直接 taskkill，`stop()` 8s 內正常關停，唔再行 elevated fallback。

## 執行步驟（核弹机，管理員）

> XML 無 `<UserId>`：`schtasks /Create` 會用執行 bat 嗰個管理員會話嘅身份註冊 — 必須喺 **Quinn 帳戶**下執行（LogonTrigger 只會喺該帳戶登入時觸發）。

1. 先手動清一次舊嘅 High integrity llama-server 殘留進程（見驗證清單第 4 點）。
2. **以管理員**執行 `scripts/register_schtask_limited.bat`：
   - `schtasks /End` + `schtasks /Delete /F` 舊 `Hedanji-Llama-Start`（舊 task High，刪除需提權，所以 bat 要管理員）。
   - `schtasks /Create /TN Hedanji-Llama-Start /XML scripts\ops\Hedanji-Llama-Start-Limited.xml`。
   - `schtasks /Query /XML` 驗證。
3. 重新登出/登入（或直接 `schtasks /Run /TN Hedanji-Llama-Start`）讓 LogonTrigger 重新起 llama-server。

> 提權只係為咗「刪除/重建 task 這一次」；重建後個 task 本身跑 `LeastPrivilege`。

## 驗證清單

- [ ] `schtasks /Query /TN Hedanji-Llama-Start /XML` 輸出含 `<LogonType>InteractiveToken</LogonType>` + `<RunLevel>LeastPrivilege</RunLevel>`。
- [ ] llama-server 正常起：`tasklist /FI "IMAGENAME eq llama-server.exe"` 見到進程。
- [ ] health 200：`curl http://127.0.0.1:18605/health` 返 200。
- [ ] GUI 點停服：**無 UAC 彈窗**，llama-server 退出（`stop()` 8s 內普通 taskkill 成功）。
- [ ] 舊 elevated 殘留進程要**先手動清一次**：管理員執行 `taskkill /F /IM llama-server.exe /T`，再重新起 task；否則新 Medium llama 同舊 High llama 並存，`18605` 端口衝突，且 Medium GUI 仍殺唔到舊 High 進程。

## 回滾（恢復 HighestAvailable）

1. 管理員執行：
   ```
   schtasks /End /TN Hedanji-Llama-Start
   schtasks /Delete /TN Hedanji-Llama-Start /F
   ```
2. 用舊 XML（或工作排程器 GUI）重新註冊 `Hedanji-Llama-Start`，Principal 設 `RunLevel=HighestAvailable`（GUI：「以最高權限執行」）。
3. 回滾後 `stop()` 會重新出現 UAC 彈窗 — 屬預期行為。

## 編碼／版本說明

- `scripts/ops/Hedanji-Llama-Start-Limited.xml` 用 **UTF-8 with BOM**，宣告 `encoding="UTF-8"`，方便 `grep` / `git diff` 正常顯示文字（亦通過 `xml.etree.ElementTree.parse()`）。
- `schtasks /XML` 嘅 Windows 標準係 **UTF-16LE + BOM**；若本機 `schtasks /Create /XML` 報「XML 格式不正確」，用記事本「另存新檔 → 編碼 Unicode (UTF-16LE)」重新存檔即可，內容唔使改。
- XML 放 `scripts/ops/`（入 git 追蹤）：`.gitignore` 排除 `crontab/`，放嗰度會變 untracked、merge 時流失；部署到核弹機時跟 `scripts\` 一齊 Copy 過去即可。
