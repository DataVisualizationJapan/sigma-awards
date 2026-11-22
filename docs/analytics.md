# Data Visualization Japan アクセス解析共通仕様

仕様バージョン: 1.0.0 / 作成日: 2026-11-22 / 対象: DVJの4サイト。公開日はPRとデプロイ履歴に記録する。

## 目的と計測先

DVJ本体と関連コンテンツを横断して、利用状況・コンテンツ閲覧・コミュニティへの導線を分析する。リポジトリ単位でGAプロパティを増やさず、1プロパティ・1ウェブデータストリームを共有する。

導入前に管理画面で確認した設定（2026-11-22）:

| 項目 | 確認値 |
|---|---|
| アカウント | data-visualization-japan / 406836401 |
| プロパティ | sigma-awards / 552654889 |
| ウェブストリーム | sigma-awards / 15677035157 |
| 測定ID | G-0DP20HK462 |
| ストリームURL | https://sigma-awards.data-visualization.jp |
| データ受信 | 過去48時間に受信あり |
| 拡張計測 | 有効 |
| 履歴変更に基づくページビュー | 有効 |
| サイト内検索の自動収集 | 有効 |
| URLクエリパラメータのデータ編集 | 無効 |
| メールアドレスのデータ編集 | 有効 |

プロパティ・ストリームの表示名は今回は維持する。名称を変更しなくても同じストリームで4サイトを計測できる。別ドメインの個人サービスなどを追加する場合は、本仕様の対象に自動的には含めない。

## 対象と設定ファイル

| リポジトリ | site_id | 本番ホスト名 | 設定ファイル |
|---|---|---|---|
| hugo-website | main | data-visualization.jp | data/analytics.json |
| sigma-awards | sigma_awards | sigma-awards.data-visualization.jp | public/analytics.json |
| sigma-awards-report | sigma_awards_report | sigma-awards-report.data-visualization.jp | analytics/analytics.json |
| eyeo-festival | eyeo_festival | eyeo-festival.data-visualization.jp | data/analytics.json |

設定項目は enabled、measurement_id、site_id、production_hosts。production_hostsは完全一致の明示リストとし、ワイルドカードやドメインの部分一致を使わない。新しい本番ホスト名を加える際は対象と影響を確認する。

全サイトで同じ内容のdvj-analytics.jsを自サイトから配信する。外部の共通JS配信サイトは新設しない。元実装はhugo-websiteのstatic/js/dvj-analytics.jsを基準とし、変更時は仕様バージョンを更新して4リポジトリを同時レビューする。各リポジトリは参照先にアクセスできなくても単体でビルドできる。

## 設置・実行

- Googleタグgtag.jsを使用し、GTMやテーマ標準のGA機能と併用しない。
- 1ページの初期化は1回。測定IDは設定ファイル1か所で管理する。
- HTTPSかつ本番ホスト名の場合だけGoogleタグを読み込む。localhost、プレビュー、GitHub Pagesの別名URL、file://は送信しない。
- Hugoは共通partialから設定JSONと自サイトのJSを出力する。開発環境・hugo serverでは出力しない。
- Sigmaはpublic/index.htmlとpublic/dja/index.htmlの明示マーカーにビルド時に挿入する。個別作品・年別ページも同じ設定から生成する。HTMLからタグを正規表現で抽出する実装は廃止する。
- レポートはtemplate.htmlとbuild.pyを生成元とし、単一index.htmlに設定と同一JSを埋め込む。index.htmlだけの手修正は禁止する。
- Cookieはcookie_domain:autoとし、親ドメインを共有する。本体・サブドメイン間のユーザー／セッション継続は公開後に確認する。
- 計測スクリプトの読み込み失敗やブロック時も、本文・検索・詳細表示の動作を継続する。

## ページビューと操作イベント

| 操作 | 計測 |
|---|---|
| ページ初回表示 | gtag configによる自動page_viewを1回 |
| Sigma作品詳細を開く・別作品へ移る | 新しいパスへ変わる場合に手動page_viewを1回 |
| 詳細から一覧へ戻る | 一覧のpage_viewを1回 |
| 戻る・進むで作品詳細と一覧を行き来する | 表示したコンテンツごとにpage_viewを1回 |
| 年・国・カテゴリなどの絞り込み | filter_apply。page_viewは増やさない |
| 自由入力の検索 | filter_apply。検索語は送らず、has_searchと結果件数だけ |
| 一覧のページ送り | pagination_change。page_viewは増やさない |
| 日本語／原文の切り替え | language_change。page_viewは増やさない |
| connpass・Facebookグループ・YouTubeチャンネルへの導線 | community_click |
| connpassのイベントページ・Peatix・Google Formsへの導線 | registration_click。申込完了とは解釈しない |
| EyeoでVimeoプレーヤーを読み込む | video_load。再生開始・視聴完了とは解釈しない |

初回ページビューの自動送信は有効のまま、GA側の「ブラウザの履歴イベントに基づくページの変更」は無効にする。手動page_viewの前にはsend_page_view:falseで画面情報を更新する。送信するタイトルとURLは実際の表示コンテンツに合わせ、page_referrerは直前に計測した画面を使う。同一パスでのクエリ変更・同じ詳細の再描画は重複計測しない。

操作イベント名は上表のホワイトリスト方式とする。任意のイベント名・入力文字列をそのまま送らない。検索・絞り込みイベントは600ms待ってまとめ、初期状態の復元は操作イベントにしない。初期実装で送信する属性は、結果件数、検索入力の有無、一覧ページ番号、catalog(sigma/dja)、language(ja/src)、決められた宛先分類、数字の動画IDに限定する。

## URL・データ取り扱い

初期化・仮想ページビューのpage_locationとpage_referrerから、検索・絞り込みクエリとフラグメントを取り除く。キャンペーン分析用のutm_source、utm_medium、utm_campaign、utm_id、utm_content、utm_termのみ保持する。これらのキャンペーンパラメータにも個人情報を入れない。DVJ内の回遊リンクにはUTMを付けない。

自由入力の検索語はイベントパラメータ、URL、リンク先URL経由でも送信しない方針とする。自動計測も含むため、公開前にサイト内検索の自動収集停止とGAのクエリパラメータ編集を設定する。クエリパラメータの対象は q、s、search、query、keyword、keywords、search_term。これは今後の収集前に値を伏字化する設定であり、過去データを削除するリクエストではない。

各サイトにGoogle Analyticsの利用、Cookie、DVJ関連サイトを横断した集計、検索語を送らない方針とGoogleの説明先を掲載する。Eyeoの「アクセス解析を使用していない」という現状説明は、導入と同時に更新する。

## GA管理画面の前提設定

対象は上記の既存ウェブストリームだけ。

1. 拡張計測 → ページビュー数 → 詳細設定で「ブラウザの履歴イベントに基づくページの変更」をオフにする。ページ読み込み時の計測は維持する。
2. 拡張計測の「サイト内検索」をオフにする。
3. URLクエリパラメータのデータ編集を有効にし、q、s、search、query、keyword、keywords、search_termを対象にする。メールアドレスのデータ編集は維持する。
4. イベントスコープのカスタムディメンションsite_idとanalytics_spec_versionを登録する。これにより通常のレポートや探索でも利用できる。site_idがない過去データはホスト名で区別する。

他の拡張計測、広告連携、保持期間、フィルタは本変更に含めない。新しいプロパティ・ストリームの作成、過去データの削除は行わない。

## 公開手順と検証

有効化後の設定値を管理する。GA側の前提設定と公開承認がそろった状態でデプロイする。

1. 4リポジトリの差分と本仕様をレビューする。既存内容と競合した場合は再確認する。
2. 承認された範囲で、変更前のコミット・GA設定を記録したうえでGAの前提設定を変更する。
3. 同じ公開作業の中で、Sigmaの修正、本体の説明ページ、残りのサイトを反映する。公開時刻と計測定義の変更日を記録する。
4. Tag Assistant／DebugView／通信内容で、初回1回、作品詳細1回、戻る・進む1回、絞り込み0PVを確認する。任意の検索語を入れても送信データに含まれないことを確認する。
5. localhost・Netlifyプレビュー・GitHub Pages別名ではGoogleタグと収集リクエストが発生しないことを確認する。
6. 本体→Sigma→レポート→本体を移動し、計測先ID、Cookieドメイン、ユーザー／セッション継続、自己参照の有無を確認する。
7. 翌日以降にホスト名とsite_idごとのデータを確認する。新しいPV定義によりSigmaの閲覧数が変わるため、導入前後を無条件に比較しない。

実送信・DebugView・全サイトの本番ビルドは公開作業で確認し、結果をPRに記録する。ローカルでは共通JSの動作、Sigma実装の画面遷移フック、既存生成テスト13件、代表9ページのタグ出力、単一レポート再生成、Hugo共通partialの6条件を検証している。Hugoテーマ全体・実データ全件に対する検証の代わりとはしない。

## 復元方法

GitHub反映時に本変更だけをまとめたコミットと元のコミットを記録する。問題があれば、それ以降の変更を失わないよう本変更のコミットをrevertし、必要なサイトを再デプロイする。強制pushやreset --hardを復元手順には使わない。

元のGA設定は履歴変更PVがオン、サイト内検索がオン、URLクエリパラメータ編集がオフ。コードの復元と整合するよう設定を戻す。コードだけを元に戻してGA設定を残すと計測定義が混在するため、同じ作業で扱う。カスタムディメンションはデータ削除せず、使わなくても残せる。変更前の公開内容は各PRのベースコミットから復元できる。公開作業では、そのコミットとGAの変更前の値を控える。

## 参照

- [GA4 アカウントの構成](https://support.google.com/analytics/answer/9679158?hl=ja)
- [ページビューの測定](https://developers.google.com/analytics/devguides/collection/ga4/views?hl=en)
- [SPAの測定](https://developers.google.com/analytics/devguides/collection/ga4/single-page-applications)
- [個人を特定できる情報を送信しないための方法](https://support.google.com/analytics/answer/6366371?hl=ja)
