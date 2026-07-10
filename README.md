# 朝刊ニュース網羅確認

毎朝 6:30（JST・土日含む）に、総合ニュース（経済寄り）と**日経必須**の見出しを集め、**スマホ向け Web ページ（GitHub Pages）** に公開します。メール送信は任意です。PCを開けなくても GitHub Actions が自動実行します。

詳細要件: [docs/requirements.md](docs/requirements.md)

## スマホで見る（推奨）

1. GitHub に push し、Actions で朝刊を生成・Pages にデプロイする（後述）
2. 公開 URL（`https://jumkita.github.io/asahan/`）をスマホのブラウザで開く
3. ホーム画面に追加すると、アプリのようにすぐ開ける

正しいURL（ハイフンなし）:

```text
https://jumkita.github.io/asahan/
```


ローカル確認:

```bash
python -m morning_news.digest
# 生成された site/index.html をブラウザで開く
```

## 前提条件

- Python 3.11+
- GitHub リポジトリ（Actions / Pages 有効）
- （任意）受信できるメールアドレスと SMTP（Gmail アプリパスワードなど）

## セットアップ（ローカル確認）

```bash
cd C:\Users\jukit\Cursor\ニュース
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

```bash
# 収集＋スマホ向けサイト生成（メール無し）
python -m morning_news.digest

# 補足なしで収集
python -m morning_news.digest --no-ai

# サイト生成をスキップ
python -m morning_news.digest --no-publish

# 収集してメール送信（SMTP設定時）
python -m morning_news.digest --send
```

### 期待結果

- `data/archive/YYYY-MM-DD.html` と `.txt` が生成される
- `site/index.html`（今日）と `site/history.html`（履歴）が更新される
- 標準出力に `[朝刊] YYYY-MM-DD（曜） N件` と `ai=件数` が出る
- RSS要約が薄い記事は「補足」ラベル付きで、公式ページの無料リード（description）を入れる
- `--send` かつ SMTP 設定があるときだけ `MAIL_TO` に HTML メールが届く
- 日経が0件のときは終了コード 2（要調査）

## GitHub Actions + Pages（クラウド自動）

1. このフォルダを GitHub リポジトリとして push
2. Repository → Settings → Pages → Source を **GitHub Actions** にする
3. （任意）Settings → Secrets and variables → Actions に SMTP を登録するとメールも送る

| Secret | 例 | 必須 |
|--------|-----|------|
| `SMTP_HOST` | `smtp.gmail.com` | 任意 |
| `SMTP_PORT` | `587` | 任意 |
| `SMTP_USER` | Gmail アドレス | 任意 |
| `SMTP_PASSWORD` | アプリパスワード | 任意 |
| `MAIL_FROM` | 送信元（通常は USER と同じ） | 任意 |
| `MAIL_TO` | スマホで見るメールアドレス | 任意 |

4. Actions → **Morning News Digest** → Run workflow で手動確認
5. 成功後、Pages の URL で朝刊を確認（ジョブの `deploy` 環境に URL が出る）
6. スケジュール: `30 21 * * *`（UTC）= 毎日 **6:30 JST**（土日含む・自動）

**毎日の自動反映は有効です。** Actions の `Morning News Digest` が毎朝走り、生成した `site/` を GitHub Pages にデプロイします。手動確認は Actions → Run workflow からいつでもできます。

SMTP Secrets が無い場合でもサイト公開は行われます。メールはスキップされます。

### Gmail アプリパスワードの目安（メールを使う場合）

1. Googleアカウントで2段階認証を有効化
2. 「アプリパスワード」を発行
3. その16桁を `SMTP_PASSWORD` に設定（通常のログインパスワードは使わない）

## ソース設定

`config/sources.yaml` を編集して追加・除外します。`category` は次のいずれかです。

- `nikkei`（必須グループ）
- `economy`（経済・やや多め）
- `general`（総合）

## テスト

```bash
pytest -q
```

## 注意

- RSS は各メディアの個人利用向け提供を前提に、**見出し・リード（無料部分）のみ**扱います。有料本文の取得・再配信はしません。
- 日経・NHK などは公式ページが会員向けの場合があります。朝刊では「見出しのみ」と明示します。
- Yahoo・毎日など無料で読める想定の記事は「無料記事を開く」と表示します。
- GitHub Actions の `schedule` は負荷により数分遅れることがあります。
- Pages の URL はリポジトリが public の場合、誰でも閲覧できます。private にする場合は GitHub のプラン制限に注意してください。
