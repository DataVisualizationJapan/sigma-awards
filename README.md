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
