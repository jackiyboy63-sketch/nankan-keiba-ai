# Codespacesに依存しない定時取得（試作）

GitHub Actions上で日本時間10:07・15:07に起動し、最大345分ずつ監視します。PCやCodespacesの起動は不要です。自動購入はありません。人気・オッズは採点に使いません。

## 適用とコード保存

```bash
unzip -n nankan-cloud-20261023.zip -d /tmp/nankan-cloud-20261023
python /tmp/nankan-cloud-20261023/apply_cloud.py
git add nar_cloud_prerace.py tests/test_cloud_prerace.py README_CLOUD.md .github/workflows/nar-prerace-cloud.yml
git commit -m "Add opt-in cloud prerace capture sessions"
git push
```

この段階では定時実行はまだ有効になりません。

## 初回設定

1. 実装は `experimental-v3-20261023` ブランチに置きます。ワークフローはこのブランチのコードを取得します。
2. `.github/workflows/nar-prerace-cloud.yml` をデフォルトブランチ（通常main）にも同じ内容で追加します。mainに他の試作コードを一括マージする必要はありません。ファイルだけを追加します。ブランチ名を変える場合はcheckoutのrefも更新します。
3. Actions → NAR cloud prerace archive → Run workflow → minutes=1 で初回確認します。短時間では日程確認だけで終わる場合があります。まず依存関係、履歴作成、Artifacts保存の動作を確認します。開催中でも1分テストが実レースの取得に成功する保証はありません。
4. 実行枠と料金を確認してから Settings → Secrets and variables → Actions → Variables → New repository variable に `NAR_PRERACE_ENABLED` = `true` を追加すると定時実行が有効になります。無効化はfalseに変更します。実行中のジョブはActions画面から別途中止します。

手動実行は変数の設定前でも動作します。長い手動実行は最大345分なので料金確認後に行ってください。

## 動作

全4場の当日出走表を確認し、検証できたレースだけ既存処理で発走5〜1分前に取得・評価・保存します。取得失敗は既存の上限3回、間隔60秒。時刻が取得できない場はエラーとして残します。「日程が取得できない」と「非開催」は自動で断定しません。

朝と午後のセッションは別環境のため、重なる時間帯に同じレースを別々に保存する場合があります。既存ファイルを上書きしません。比較処理は最初の完了記録を選びます。定時実行はGitHubの都合で遅延・不実行になる場合があり、全レースの取得を保証しません。約10:07〜20:52が想定監視範囲で、開始前・終了後のレースは対象外です。

履歴はその都度Gitに保存済みの月次公式ZIPから作り直します。Codespaces内だけにあるデータは使われません。先に月次ZIPがGitHubに保存されていることを確認してください。月次データのダウンロード処理自体はこの追加版に含みません。

## 記録の取得

Actionsで実行を開き、下部のArtifactsから `nar-prerace-実行ID-試行番号` をダウンロードします。取得原文・評価CSV・完了/失敗記録・監視記録を含みます。画面への自動同期は含みません。

保存期間は90日（リポジトリ側の上限に制限される場合があります）。永続保存ではありません。期限前にダウンロードして保管してください。ジョブ中の記録は終了時にアップロードします。通常のエラー時も保存を試みますが、強制終了やランナー障害時は未アップロード分を失う場合があります。

緑色の成功表示だけでは取得成功を意味しません。`cloud_summary.json` と各Rの `run_manifest.json` の `completed_prerace` を確認してください。結果データが揃った後、各Artifactsの `prerace_runs` をローカルの `data/prerace_runs` にまとめ、従来の比較処理を使います。ZIP展開時の最上位フォルダは確認してください。

## 実行時間・料金

開催日は待機を含め最大約690分/日＋準備時間。毎日上限まで動かすと約20,700分/月＋準備時間です。非開催でも日程確認の実行時間は使います。標準ランナーは公開リポジトリでは原則無料、非公開ではプランの無料枠を消費し、超過時の課金や停止はアカウント設定によります。Artifactsの保存容量にも注意してください。正確な金額はGitHubのBilling画面で確認します。非公開リポジトリを勝手に公開する必要はありません。

コード・模擬時刻のテストは実施済み。GitHub Actionsの実環境と公式の発走前取得はまだ未確認です。GitHubに対する書き込み権限がこちらにないため、適用・mainへのワークフロー追加・有効化はユーザー操作が必要です。

公式資料:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
