# Sigma Awards エントリー一覧

[The Sigma Awards](https://sigmaawards.org) に応募されたデータジャーナリズム作品を、カードUIで検索・閲覧する静的サイトです。

公開ページ: https://sigma-awards.data-visualization.jp/

## データ

一次ソースは Sigma Awards の GitHub Organization です。

- Organization: [Sigma-Awards repositories](https://github.com/orgs/Sigma-Awards/repositories)
- エントリー正本: [The-Sigma-Awards-projects-data](https://github.com/Sigma-Awards/The-Sigma-Awards-projects-data)

データは Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International です。利用時は Sigma Awards / GIJN へのクレジットが必要です。

### ID台帳（`scripts/sigma/ids.json`）

作品ID（`2024-s-0001` など）は公開URLに使われるため、上流CSVが変わっても変えません。上流には応募IDがないので、`scripts/build-data.py` は年×種別ごとに上流の行を台帳の指紋（行全体のハッシュ、タイトル、組織、リンク、説明、Category）と照合します。

1. 行全体のハッシュが上流と台帳で1件ずつ一致するものは、その場で確定します。
2. 残りは点数（タイトル3、リンク全一致2・一部一致1、説明2、組織1、Category1）で照合し、4点以上を高い順に1対1で割り当てます。ただしリンクの共通または説明の一致が必須で、タイトル＋組織だけでは割り当てません（removed のIDも同じ）。
3. 照合できない行は新規として、その年×種別の最大番号＋1を振ります。
4. 上流から消えたIDは `removed: true` で台帳に残し、出力しません。番号は再利用しません。

結果（確定・点数照合・新規・削除）はビルドの標準出力に表示され、台帳は全グループが成功したときだけ更新されます。指紋はCSVを読んだままの値（`read_rows`）から計算し、表示用の整形（`clean_row`）は照合の後に行うため、整形ルールを変えてもIDは動きません。台帳には作成に使った上流コミットも記録され、`entries.json` の `upstreamCommit` にも入ります。台帳の変更はコミットしてください。

照合が止まったとき（`ID ledger:` で始まるエラー）：

- 「candidates tie」：同点の候補が競合しています。表示された行と ID を見て、正しい対応を `ids.json` の `overrides` に `"<ID>": "<行ハッシュ>"` で追加し、再実行します。行ハッシュは台帳の `rowHash` か、`scripts/sigma/ledger.py` の `row_hash()` で得られます。
- 「Needs review」：タイトル・組織だけが似た行とIDの組があり、リンクも説明も共通しません。同じ作品なら `overrides` に `"<ID>": "<行ハッシュ>"` で固定し、別の作品なら古いIDを `"<ID>": null`（以後どの行にも割り当てない）にして再実行します。上流にまだ一致する行があるIDを `null` にするとエラーになります（公開URLが変わるため）。固定した後のビルドで台帳の指紋が更新されるので、`overrides` の記載は削除して構いません（行を後で修正すると一致せずエラーになります）。
- 「matched by score (limit …)」：点数照合の行が多すぎます（年×種別あたり `min(20, 行数の10%)`、最小3件。タイトル・リンク・説明が一致し競合のない行は数えません）。上流の差分を確認し、意図した変更なら対応するIDを `overrides` で固定してから再実行します。
- 同点の候補は、正規化前のタイトルが完全に一致する組を優先します（大文字小文字だけが違う重複用）。
- ビルド出力に `unneeded override` と出たIDの上書きは、外しても結果が同じなので削除できます。
- 存在しないIDや、どの行にも一致しない行ハッシュを指定した `overrides` はエラーになります。
- 上流から消えた行が戻ったときは、同じIDに自動で戻ります。

テストは `python3 scripts/test_sigma_ids.py` です。`.tmp-data` に上流があれば実データでも検証します。

## 使い方

```bash
python3 scripts/build-data.py
python3 -m http.server 4173 --directory public
```

ブラウザで `http://localhost:4173` を開きます。`index.html` をファイルとして直接開くと JSON を読めません。

`scripts/build-data.py` は、未取得なら上記リポジトリを `.tmp-data/` に clone し、`public/data/` へ正規化 JSON を書き出します。

タイトル・概要・詳細本文の日本語は `scripts/translate-ja.py` がローカルの NLLB モデルで付与します。既定表示は日本語、原文はカードと詳細に残します。

### 翻訳の `<unk>` 対策（ローカルで実行）

NLLBの語彙外の文字（原文の引用符・ダッシュ・`₦` など、出力側の珍しい漢字）が `<unk>` として訳に残ることがあります。`translate-ja.py` は、入力の記号を翻訳前に正規化（JSONの原文は変更しません）し、訳に `<unk>` が出たらキャッシュへ保存せず、`disable_unk` つきでbeamを広げた再試行、Ollama（`--ollama-retry` を付けたときだけ）、補正辞書（適用時にログへ出ます） `scripts/ja-unk-corrections.json` の順に試します。それでも残る訳は付けず、原文を表示します（`.tmp-data/ja-failed.json` に記録し、`--retry-failed` で再挑戦できます）。

```bash
# 1. 既存の壊れた訳を、キャッシュと public/data/*.json から削除
.venv/bin/python scripts/translate-ja.py --purge-unk
# 2. （任意）語彙外文字を出現数つきで一覧にする。翻訳はしません
.venv/bin/python scripts/translate-ja.py --audit-vocab
# 3. 再翻訳（削除した分だけが対象）
.venv/bin/python scripts/translate-ja.py        # または scripts/run-translate-loop.sh
# 4. <unk> が残っていないこと（すべて0）を確認してコミット
grep -c '<unk>' public/data/*.json
```

補正辞書は `{"灌<unk>": "灌漑"}` の形式で追記できます。テストは `python3 scripts/test_translate_ja.py`（モデル不要）です。

### Sigmaデータの整形

`scripts/build-data.py` は、上流CSVの内容がそのまま流れ込んだ表示上の問題を、共通処理 `scripts/sigma_text.py`（標準ライブラリのみ）で直します。作品IDの決め方は変えていません。

- **文字実体**：全フィールドで `&amp;` `&lt;` `&gt;` `&quot;` `&apos;` と数値参照だけを1回デコードします。`html.unescape` は使いません。セミコロンのない `&para=` や `&timestamp=` を含むURLを壊さないためです。
- **URL（`links` と `url`）**：実体をデコードして空白を除き、Markdown の `[t](u)` と `](` から URL を取り出します。空白で区切り、`http(s)://` で始まる断片をそれぞれ1本のURLにします。空白なしの連結は、2本目の直前が `/` で、外側が web.archive.org、translate.google.com、google.com/url のいずれでもないときだけ分割します。末尾の `.,;:` と、対応していない `)` `]` を除きます。`#:~:text=` を含むURLは変更しません。scheme が http/https で、netloc に `.` を含み、空白がないものだけを残し、重複は順序を保って除きます。`url` は整形後の先頭のリンクです。変換前後は `public/data/url-fixes.json` に全件記録します。
- **プレースホルダ値**：`org` `country` `authors` `tools` `impact` が、前後の空白と大文字小文字を除いて `none` `n/a` `na` `nil` `nil.` `-` `—` と完全一致するときは空にします。
- **文字化け**：CSV は行ごとに UTF-8 で読み、失敗した行だけ Mac Roman で読み直します。
- **日本語訳の引き継ぎ**：既存JSONの原文を同じ規則で整形したものが、新しい原文と一致する欄の訳だけを引き継ぎます（フィールドごとに判定）。原文が空になった欄、`<unk>` を含む訳は捨て、原文表示になります。捨てた件数は理由別に表示します。引き継ぐ訳にも実体デコードをかけます。

`read_rows` は文字コードの判定（行ごとに UTF-8、失敗した行だけ Mac Roman。UTF-8 の文字が混在する行はビルドを止めます）だけを行い、値の整形は `clean_row` に置きます（`read_rows` を変えると台帳の指紋が変わるため）。

`python3 scripts/test_build_data.py` が整形規則の単体テストと、`public/data` 全体の不変条件（`<unk>`・基本実体・U+FFFD・不正なリンク・プレースホルダ値がないこと）を検証します。

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

84件に日本語要約を付与しています。説明のない対象は原題・媒体・選考情報などのみを掲載します。作品リスト・個別詳細ページは追加取得しません。サムネイルは保存HTML内の画像参照から復元し、採用できたものだけ表示します。旧DJA紹介ページと作品へのリンクを区別しており、リンク先が現在閲覧できるかの確認は行っていません。

SigmaデータのCC BY-NC-SAライセンスをDJA資料に適用するものではありません。各資料の出典はレコードごとに表示します。

### 検証

```bash
python3 scripts/test_dja_data.py
```

10件のテストで整合性、2013年の省略原題、開催年、共同受賞、NOSの誤リンク、特別表彰、画像の対応・検証、再生成の一致を確認します。元資料がある場合はネット接続を禁止した状態で再生成も検証します。

Playwrightが利用できる環境では、静的サーバーを4173番で起動して次を実行できます。

```bash
node scripts/test-catalog-ui.cjs
```

PC・スマートフォン、複合フィルター、URL復元、日本語／原文、詳細表示と取得失敗、キーボード操作、既存Sigma一覧を検証します。テスト中は外部通信を遮断し、DJAやWaybackへの取得要求がないことも確認します。


### DJAサムネイルの復元

保存HTMLで作品と対応付く画像URLだけを抽出し、配信元、続いてWaybackの画像スナップショットを使います。作品サイトのOGP探索やスクリーンショット作成は行いません。画像のみの段落、遅延読み込み画像、隣のカラムの画像にも対応し、2018年の個人部門のように複数対象に画像が1枚しかない場合は主対象だけに対応付けます。2019年のフッターロゴは作品画像として取り込みません。

```bash
# 通常のデータ生成はPython標準ライブラリのみで実行可能
python3 scripts/build-dja-data.py
# 以下の画像取得・画像テストのみ、Pillowを導入済みのPythonが必要
python3 scripts/fetch-dja-thumbs.py
python3 scripts/build-dja-data.py
python3 scripts/test_dja_thumbnails.py
```

取得処理は既存画像をハッシュで照合して再利用します。`--workers`（既定6）と `--timeout`（既定15秒）を指定できます。Waybackへの並列アクセスは2件までに制限し、CDXで確認した同一画像パスの保存のみを使います。元ページの保存時点に近いものから確認し、最古の保存も候補に含めます。TLS証明書の検証は有効です。

採用結果の正本は `scripts/dja/thumbnails.json`、画像ファイルは `public/thumbs/dja/` です。元の画像URL、入力HTML、保存URL、取得URL、形式、サイズ、SHA-256を記録します。`public/data/dja/thumbnails-report.json` には全535件の結果・除外理由・失敗した取得先を記録します。目視で判明したDJA/DENロゴの代替画像は `scripts/dja/rejected-images.json` のハッシュで除外し、URLが作品名でも画像本体が仮画像なら採用しません。

現在96件（2013年73件、2015年1件、2016年1件、2018年15件、2019年6件）を採用しています。残りは取得・採用できなかった44件と画像参照のない395件です。形式検証だけでは作品画像と断定できないため、新規取得後は目視でも対応を確認してください。仮画像が見つかった場合は除外ハッシュを記録し、採用結果を見直してからデータを再生成します。元画像を変換せず保存し、ブラウザはローカル画像だけを読み込みます。データ再生成では正本の画像と入力HTMLの対応、ファイルの存在・ハッシュを確認して `thumb` を再設定するため、再生成後もサムネイルが保持されます。

### 静的ページの生成（クローラー向け）

JavaScriptなしでも内容を読めるよう、コミット済みのJSONからビルド時に静的HTMLを生成します。データJSONは変更しません。Netlifyでは `netlify.toml` のとおり `python3 scripts/build-pages.py` を実行し、`dist/` を公開します（Python標準ライブラリのみ、`dist/` はGit管理外）。

```bash
python3 scripts/build-pages.py && python3 -m http.server 4173 --directory dist
python3 scripts/test_build_pages.py
```

`--public-dir`（既定 `public`）と `--output-dir`（既定 `dist`）を指定できます。`public/` を `dist/` へコピーし、次を追加します。同じ入力からは毎回同じ出力になります。

- 作品ごとの個別ページ: `/entries/{id}/`（Sigma 3,899件）、`/dja/entries/{id}/`（DJA 535件）。日本語・原文、リンク・出典、canonical、OGP、JSON-LD（`CreativeWork`）を含みます。
- 年別一覧ページ: `/{year}/`（2020〜2026）、`/dja/{year}/`（2012〜2019）。
- `/` と `/dja/` の `#card-grid` に既定年の先頭24件のカードと「年別一覧」リンク集を埋め込みます。JavaScriptが動くと `app.js` が置き換えます。
- `sitemap.xml`（`lastmod` なし）。
