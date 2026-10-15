# Sigma Awards エントリー一覧

[The Sigma Awards](https://sigmaawards.org) に応募されたデータジャーナリズム作品を、カードUIで検索・閲覧する静的サイトです。

公開ページ: https://sigma-awards.data-visualization.jp/

## データ

一次ソースは Sigma Awards の GitHub Organization です。

- Organization: [Sigma-Awards repositories](https://github.com/orgs/Sigma-Awards/repositories)
- エントリー正本: [The-Sigma-Awards-projects-data](https://github.com/Sigma-Awards/The-Sigma-Awards-projects-data)

データは Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International です。利用時は Sigma Awards / GIJN へのクレジットが必要です。

## 使い方

```bash
python3 scripts/build-data.py
python3 -m http.server 4173 --directory public
```

ブラウザで `http://localhost:4173` を開きます。`index.html` をファイルとして直接開くと JSON を読めません。

`scripts/build-data.py` は、未取得なら上記リポジトリを `.tmp-data/` に clone し、`public/data/` へ正規化 JSON を書き出します。

タイトル・概要・詳細本文の日本語は `scripts/translate-ja.py` がローカルの NLLB モデルで付与します。既定表示は日本語、原文はカードと詳細に残します。

## Data Journalism Awards（DJA）

`/dja/` に2012〜2019年の受賞・ショートリスト・特別表彰を掲載します。Sigmaとの表示処理・CSSは共用し、データを `public/data/dja/` に分けています。

### 元データと生成

元データはユーザーが取得した、隣接ディレクトリ `../data-journalism-awards/archive/` の `manifest.json` とHTML 37ファイルです。変換処理はPython標準ライブラリのみを使い、ネット接続やHTML内のスクリプト実行を行いません。元資料も変更しません。

```bash
python3 scripts/build-dja-data.py
# 任意の archive/、またはその親ディレクトリを指定
python3 scripts/build-dja-data.py --source-dir /path/to/data-journalism-awards
# 確認用の出力を別の場所に生成
python3 scripts/build-dja-data.py --output-dir /tmp/dja-data
python3 -m http.server 4173 --directory public
```

ブラウザで `http://localhost:4173/dja/` を開きます。生成済みJSONを収録しているため、閲覧・静的配信には元資料やPythonは不要です。再生成には上記のアーカイブが必要です。

### 抽出・補正

- HTML構造ごとに受賞・候補を抽出します。2013年はWizeHiveの8ページ計73件、2016・2017年の受賞は2018年の過去受賞者ページを使います。作品の公開年は開催年に使用しません。
- Communityの `winner` / `finalist` フラグは対象ごとに読み、`nowinner` / `nofinalist` や応募一覧への掲載だけで選出を判定しません。応募一覧は説明などの補完にも使用します。
- 同一年の同一対象は原題の正規化、旧DJAの個別紹介URL、明示した別名で統合します。作品への外部URLだけでは統合しません。省略表示の同名作品も、個別の応募IDが異なれば分けます。
- 部門ごとの最上位結果を `awards` に持ち、元の部門名・候補段階の結果は各部門の `evidence` に保持します。カードの `result` は受賞、特別表彰、ショートリストの順に選びます。部門・結果フィルターは同じ `awards` 要素に対して照合します。
- `scripts/dja/corrections.json` が補正の正本です。`records` は年と抽出原題で特定する事実の修正、`aliases` は同一対象の表記揺れ、`categories` は部門表記の統一、`kinds` は種別、`summariesJa` は資料に基づく短い日本語要約です。補正理由は `notes`、収録上の制約は `coverageNotes` に記録します。
- IDは開催年と正規化した対象名から決定的に生成し、省略表示の場合は個別の応募URLも使用します。追加・並べ替えで変わりません。既存の名称・別名を変更する場合は `ids` に旧IDを明示して既存URLを維持してください。キーは `年|正規化名`（省略表示ではさらに `|個別URL`）です。
- `sources` に元URL・確認済み保存URL・入力ファイル、詳細の `sourceRecords` に資料の記載を保持します。manifestに個別保存URLがないページについては、URLを推測して作りません。
- `build-report.json` にファイルのSHA-256、抽出数、年別件数、manifestの説明、文字化け・未使用補正を出力します。日時を毎回更新しないため、同じ入力から同じ結果を再生成できます。

### 収録上の制約

全応募の完全な一覧ではありません。2015年などは候補一覧が一部しか保存されていません。2012年は資料の案内が59候補なのに対し保存HTMLの実掲載は58件、2018年は86候補という案内に対し実掲載は87部門枠です。重複対象を統合した件数と、部門ごとの掲載数も異なります。各年の状況をページ内で確認できます。

2013年の多数の原題・媒体名は保存HTML自体で省略されています。補える記載が同梱資料にある対象だけ補正し、残りは省略表示を保持しています。page-3.htmlには省略位置で切れたUTF-8文字があり、置換文字と注記を残しています。

2019年の受賞ページにはNOS作品がThe Puddingを指すリンク誤りがあり、同梱ショートリストの紹介URLで補正しています。2015年の共同受賞は、構成作品をばらばらの受賞対象として数えずまとめています。

84件に日本語要約を付与しています。説明のない対象は原題・媒体・選考情報などのみを掲載します。資料・個別詳細ページ・画像を追加取得せず、サムネイルのない対象は画像なしで表示します。旧DJA紹介ページと作品へのリンクを区別しており、リンク先が現在閲覧できるかの確認は行っていません。

SigmaデータのCC BY-NC-SAライセンスをDJA資料に適用するものではありません。各資料の出典はレコードごとに表示します。

### 検証

```bash
python3 scripts/test_dja_data.py
```

8件のテストで整合性、2013年の省略原題、開催年、共同受賞、NOSの誤リンク、特別表彰、再生成の一致を確認します。元資料がある場合はネット接続を禁止した状態で再生成も検証します。

Playwrightが利用できる環境では、静的サーバーを4173番で起動して次を実行できます。

```bash
node scripts/test-catalog-ui.cjs
```

PC・スマートフォン、複合フィルター、URL復元、日本語／原文、詳細表示と取得失敗、キーボード操作、既存Sigma一覧を検証します。テスト中は外部通信を遮断し、DJAやWaybackへの取得要求がないことも確認します。
