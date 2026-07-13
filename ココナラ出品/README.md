# ココナラ出品パッケージ（朝刊厳選）

このフォルダが **出品作業の本体** です。`docs/` 配下にも同内容の控えがありますが、普段はここを開いてください。

## フォルダ構成

| パス | 用途 |
|------|------|
| `出品文.md` | タイトル／キャッチ／本文／FAQ／注意／出品者メッセージ（コピペ用） |
| `images/thumbnail-asahan-main.png` | **メインサムネイル**（検索一覧に出る画像） |
| `images/gallery-priority-abc.png` | ギャラリー①：重要度 A/B/C の説明 |
| `images/gallery-free-vs-paywall.png` | ギャラリー②：無料見出し／会員壁の開示 |
| `images/screenshot-asahan-curated.png` | 実UI：デスクトップ上部（「厳選」枠） |
| `images/screenshot-asahan-full.png` | 実UI：デスクトップ全文（厳選＋網羅） |
| `images/screenshot-asahan-mobile.png` | 実UI：モバイル（390×844） |
| `README.md` | 本ファイル（アップロード手順） |

価格: **100円 / 月**（定期購入）  
公開サンプル: https://jumkita.github.io/asahan/

## ココナラ画面での貼り付け手順

1. **サービス出品** → テキストチャット・データ納品 など該当カテゴリを選択
2. **提供内容（タイトル）** … `出品文.md` の推奨タイトルを1つ貼る（語尾「ます」）
3. **キャッチコピー** … 推奨キャッチを1つ貼る
4. **サービス内容** … 「サービス内容」「やらないこと」「公開範囲・会員壁」「FAQ」「注意事項」を本文に貼る
5. **価格** … 100円。**定期購入可能**にする
6. **画像**（※リポジトリから自動反映されません。**手動アップロード必須**）
   - メイン画像／サムネイル: `images/thumbnail-asahan-main.png`
   - 追加画像1: `images/gallery-priority-abc.png`
   - 追加画像2: `images/gallery-free-vs-paywall.png`
   - （任意）実UIスクショ: `images/screenshot-asahan-curated.png` / `full` / `mobile`
7. 購入者へのお願い・注意に、会員壁・全文再配信しない旨があることを確認して公開

## 実UIスクリーンショットについて

`site/index.html` をローカル配信し、Playwright（Chromium）で撮影した実画面です（AIモックではありません）。

| ファイル | 内容 |
|----------|------|
| `images/screenshot-asahan-curated.png` | 1280×900・上部の「厳選」見出しが見える範囲 |
| `images/screenshot-asahan-full.png` | 同幅・フルページ（厳選〜網羅） |
| `images/screenshot-asahan-mobile.png` | 390×844・モバイル上部 |

再撮影例: `python -m morning_news.digest --no-ai` の後、`site/` で `python -m http.server`、Playwright で `http://127.0.0.1:PORT/` を開いて保存。

## 必ず伝わるようにする開示（要約）

- ダイジェストは **無料の見出し・リード** 中心
- リンク先は日経など **会員が必要な場合あり**
- **有料全文は再配信しない**

## 関連ドキュメント

- 商品設計: `docs/coconala-product.md`
- 出品文の控え: `docs/coconala-listing.md`
- 画像の控え: `docs/coconala-assets/`
