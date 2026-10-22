# 南関競馬AI 監査修正版（2026-10-22）

基準リポジトリ: https://github.com/jackiyboy63-sketch/nankan-keiba-ai

基準コミット: `26ff74b6a609fe8d0177986e02e8c712cff109a0`

GitHubの設定確認・書き込み再試行は実施していません。読み取り取得したコードをローカルで修正しました。

## 反映

パッケージ内 `changes.patch` に変更と追加ファイルがすべて入っています。
既存リポジトリを開いたPCまたはGitHub Codespacesのターミナルで適用できます。
パッケージのZIPをアップロード・展開し、リポジトリのルートで次を実行します。
パッチの場所は展開先に合わせて指定してください。

```bash
git status --short
git apply --check /path/to/changes.patch
git apply /path/to/changes.patch
python -m unittest discover -s tests -v
git diff --stat
```

`--check` が失敗した場合はそのまま停止し、手元の変更を残してください。
既存変更を破棄するコマンドは不要です。`replacement/` には同じ変更後ファイルも収録しています。

反映内容を確認後、通常のユーザー自身のGitHub認証でコミット・pushできます。
この作業環境からのGitHub書き込みは実施していません。

## 再現

Python 3.12、pandas 2系、numpyを使用します。

```bash
pip install 'pandas>=2.1,<3' numpy
python -m unittest discover -s tests -v
python nar_history.py --input . --output data/processed
python nar_walkforward.py --input data/processed/horse_history.csv --archives . --start 2026-06-01 --end 2026-09-30 --output-dir walkforward_results
```

初期値の `--input .` は、`data/` と直下の公式ZIPを両方読み込みます。
結果パッケージのZIPは解析対象とは別の場所に保存する運用を推奨します。
`nar-walkforward.yml` を反映すれば、GitHub Actionsの **NAR chronological payout benchmark** から手動実行できます。
GitHub Actions側の動作確認は未実施です。ローカルのテストと実データ検証を実施しています。

## 出力

- `summary.csv`: モデル・券種・月ごとの投資、払戻、回収率、的中率、最大ドローダウン、高配当依存度。
- `bets.csv`: 固定方式で選んだ組番と100円単位の払戻明細。実購入の記録ではありません。
- `accuracy.csv`: 評価1位の勝利・3着内、勝ち馬順位、上位3頭捕捉。
- `excluded.csv`: 着順や頭数の不整合、払戻欠損等の除外明細。
- `manifest.json`: 入力CSVと各ZIPのSHA-256、条件、制約。

最大払戻を除いた回収率は、投資額を維持したまま最大払戻1件だけを差し引く保守的な参考値です。

4券種はそれぞれ独立した比較対象です。合算した購入プランではありません。
評価1位の単勝、評価1位の複勝、評価1・2位の馬連、評価1・2位のワイドを各100円で検証します。
各方式は1日5,000円上限で、日付・競馬場名・Rの固定順に処理します。
事後払戻は精算だけに使用し、人気・オッズ・結果による馬の選別は行いません。
ただし不完全な結果のレースを事後に除外するため、実運用で再現できる収益の証明ではありません。

## 判断上の制約

- 現モデルは固定配点の採点方式です。勝率に校正された機械学習モデルではありません。
- `確かさ(%)` は取得できた評価配点の割合であり、的中確率ではありません。
- 対象レースの馬リストと馬場は結果CSVに由来します。発走前時点の取得時刻は保証できません。
- 取消・中止・同着・頭数不一致等は保守的に除外。返還金のシミュレーションは未実装です。
- 当日途中の馬場変化、発走前オッズの時系列、予測確率の校正をまだ接続していません。
- 現時点でオッズ条件付き期待値選別や年間回収率120%の達成は検証していません。
- この検証を見て買い方・配点を変える場合、同期間を再び未使用テスト扱いにしないでください。
