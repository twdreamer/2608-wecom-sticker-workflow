# WeCom Sticker Workflow for macOS

將透明靜態 PNG 或 APNG 動圖整理成較容易被 macOS 企業微信收藏的貼圖格式。

這是依實際測試整理的非官方工作流程，不使用企業微信內部 API，也不包含任何第三方貼圖素材。

## 已驗證的核心方法

企業微信的「本地上傳貼圖」可能拒絕自行產生的 APNG／GIF；較穩定的做法是：

1. 先把圖片轉成下方建議格式。
2. 在企業微信中開啟**自己的對話**。
3. 以一般聊天圖片傳送檔案。
4. 對剛送出的圖片按右鍵，選擇「新增到貼圖」。
5. 打開個人收藏貼圖，確認圖片、透明背景與動畫。

> 請先用一張測試。企業微信版本、macOS、手機平台和伺服器端處理方式都可能改變。

## 格式策略

### 靜態透明 PNG

將 palette PNG 包裝成一個內容靜止的有限 APNG：

- 6 個 APNG frame。
- 每輪 1 秒。
- 播放 4 次，總播放 4 秒。
- 保留原始第一格的 PNG 壓縮資料、色盤和 `tRNS` 透明度。
- 使用與常見 LINE APNG 相近的 disposal 結構。
- 最後加入 1×1 透明 frame。

在已測試的 macOS 企業微信版本中，這種檔案經「聊天圖片 → 新增到貼圖」可保留透明背景。手機版通常能保留透明背景，但可能只顯示靜態畫面。

來源目前必須是：

- PNG color type 3（索引色／palette）。
- 含有 `tRNS`，且至少一個色盤索引為完全透明。
- 尚未是 APNG。

### APNG 動圖

將 APNG 轉成較保守的透明 GIF：

- 240×240 透明畫布。
- GIF89a。
- 保留原始影格數與近似播放節奏。
- 保留一個透明色盤索引。
- disposal method 2。
- `loop=0`，無限循環。

透明 GIF 通常比自製 APNG 更適合跨端測試，但手機企業微信的實際播放能力仍須逐版本驗證。

## 安裝

需要 Python 3.9 以上。靜態 PNG 工具只使用標準函式庫；動圖工具需要 Pillow。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 靜態圖片

轉換單一檔案：

```sh
python scripts/static_png_to_apng.py input.png output.png
```

轉換整個資料夾：

```sh
python scripts/static_png_to_apng.py source_folder output_folder
```

資料夾模式會：

- 跳過名稱以 `_thumbnail` 結尾的 PNG。
- 以去除 `@2x` 後的檔名作為貼圖 ID。
- 拒絕同 ID 的重複檔案。
- 逐張驗證 APNG frame、播放時間及透明度。
- 產生 `manifest.csv` 和 SHA-256。

## 動態圖片

轉換單一 APNG：

```sh
python scripts/animated_png_to_gif.py input.png output.gif
```

轉換整個資料夾：

```sh
python scripts/animated_png_to_gif.py source_folder output_folder
```

可調整畫布及透明 Alpha 門檻：

```sh
python scripts/animated_png_to_gif.py source_folder output_folder \
  --canvas 240 \
  --alpha-threshold 127
```

資料夾模式同樣會建立 `manifest.csv`，包含影格數、播放週期、透明度、檔案大小和 SHA-256。

## 檢查輸出

```sh
python scripts/inspect_sticker.py output.png
python scripts/inspect_sticker.py output.gif
python scripts/inspect_sticker.py output_folder
```

輸出為 JSON Lines，適合人工檢查或接到其他批次工具。

## 加入企業微信

1. 開啟 macOS 企業微信。
2. 明確選取自己的對話或檔案傳輸用途的私人對話。
3. 再次查看聊天標題，避免把測試貼圖傳到同事或群組。
4. 傳送一張轉換後的圖片。
5. 對聊天中的圖片按右鍵。
6. 點「新增到貼圖」。
7. 開啟貼圖面板的個人收藏分類。
8. 確認新貼圖出現在最前方，而且透明背景正常。
9. 動圖請同時在 Mac 與手機上測試。

若直接從貼圖面板的「＋」選擇檔案得到「貼圖新增失敗」，改用上述聊天圖片路徑。

## 批次處理的安全原則

如果要另外製作 GUI 自動化，建議至少遵守：

- 每次送出前都驗證聊天頂部的精確對話名稱。
- 先測一張，確認收藏面板真的增加後才批次。
- 每完成一張就寫入 manifest，不要等整批結束才記錄。
- 遇到找不到按鈕、選單或成功提示時立即停止。
- 不要把螢幕絕對座標當作跨機器穩定介面。
- 不要用剪貼簿傳遞檔案路徑，以免干擾使用者工作。
- 新貼圖通常插在收藏最前面，匯入後的可見順序可能與處理順序相反。
- 來源旁若出現 `ID_thumbnail.jpg`，先把它視為「可能已處理」的訊號，再比對 ID 與 manifest。
- 不要自動刪除舊貼圖；刪除前應建立完整視覺基線並取得明確確認。

## 已知限制

- 這不是企業微信官方支援的格式規格。
- macOS 企業微信可播放的 APNG，在手機版可能只顯示靜態影格。
- 透明背景成功不代表動畫一定會播放。
- 伺服器可能依檔案雜湊或內容去重。
- 不同企業微信版本的右鍵選單名稱與行為可能不同。
- GIF 使用索引色，複雜漸層可能產生量化色差。
- 半透明邊緣會依 `--alpha-threshold` 轉成透明或不透明像素。

## 隱私與著作權

- 不要把私人聊天截圖、帳號資料庫、聯絡人姓名或本機絕對路徑提交到公開 repository。
- 只處理你有權使用的圖片。
- 本 repository 的 MIT License 只涵蓋程式碼與文件，不授權任何第三方貼圖素材。

## 專案內容

```text
scripts/static_png_to_apng.py  靜態透明 PNG → 有限 APNG
scripts/animated_png_to_gif.py APNG 動圖 → 透明無限 GIF
scripts/inspect_sticker.py     PNG/APNG/GIF 結構檢查
```

## License

MIT
