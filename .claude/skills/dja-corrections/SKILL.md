---
name: dja-corrections
description: Data Journalism Awards（DJA）データの事実・表記を補正するときの手順。public/data/dja/ の値を直す、scripts/dja/corrections.json に補正を追加する、文字実体や誤記を修正する、といった作業の前に読む。
---

# DJAデータの補正

DJAのデータ `public/data/dja/` は、`scripts/build-dja-data.py` が元アーカイブ（`../data-journalism-awards/archive/`）から生成する。事実の補正は必ず `scripts/dja/corrections.json` に書き、再生成しても補正が保たれるようにする。

## 手順

1. 対象を特定する。`public/data/dja/entries.json` で作品の `id`、開催年、原題を確認する。補正のキーは `"{開催年}|{抽出した原題}"`（例: `"2014|Across U.S. Companies, Tax Rates Vary Greatly"`）。キーの作り方は `scripts/build-dja-data.py` の `records` の参照箇所で確かめる。
2. `scripts/dja/corrections.json` の `records` に、直したいフィールドだけを書く。
   ```json
   "2014|Across U.S. Companies, Tax Rates Vary Greatly": {
     "summary": "…S.&P. 500 companies paid…"
   }
   ```
   レコードの中身は再生成時に `row.update(...)` で作品データへそのまま上書きされる。補正したいフィールド以外は書かない。
3. 補正の理由は、`corrections.json` 最上位の `notes` 配列に1行で追記する。
4. 値は原文の表記を保つ。直すのは誤りの部分だけにする（例: `S.&amp;P. 500` は `S.&P. 500` にし、ピリオドを残す）。
5. 再生成する。
   - アーカイブがある場合: `python3 scripts/build-dja-data.py` を実行する。
   - アーカイブがない場合: コミット済みの `public/data/dja/entries.json` と該当する `details-{year}.json` の値を、corrections と同じ値に直接書き換える。ファイルの書式（インデント、キー順、末尾の改行 `}\n`）は元のまま保ち、`git diff -- public/data/dja` が対象の行だけになることを確かめる。
6. `scripts/test_dja_data.py` に、補正の値が corrections と出力JSONの両方で一致することを確かめるテストを加え、`python3 scripts/test_dja_data.py` を実行して通ることを確認する（アーカイブがないための skip は問題ない）。

## 確認

- `git diff --stat` に、`scripts/dja/corrections.json`、`public/data/dja/` の対象ファイル、`scripts/test_dja_data.py` だけが出ていること。
- `git diff -- public/data/dja` の変更が、直したい値の行だけであること。
- `python3 scripts/test_dja_data.py` が通ること。
