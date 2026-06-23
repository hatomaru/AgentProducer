---
name: remotion-setup-and-run
description: Remotionの環境構築の確認、環境構築の実行、実際の動画生成の手順を定義したスキル。ADK Playground等のAgent Toolとして実行する際の標準的な手順を提供する。
---

# Remotion 環境構築と動画生成スキル

このスキルは、Agent Producer内でRemotionを用いた動画生成を行うための具体的な手順とルールを定義するものです。ADKのTool（FunctionTool等）から実行する際はこの手順に従ってください。

## 1. 環境構築の確認手順

動画を生成する前に、Remotionのプロジェクトが既に構築されているかを確認します。

1. **プロジェクトディレクトリの確認**:
   - プロジェクトルート直下に `remotion-project` というディレクトリが存在するか確認します。
   - `remotion-project/package.json` の存在を確認し、存在する場合は既に構築済みとみなします。

## 2. 環境構築の手順

`remotion-project` が存在しない場合は、以下の手順で初期化します。

1. **Remotionプロジェクトの作成**:
   - 以下のコマンドを実行して、インタラクティブプロンプトをスキップしつつ空のRemotionプロジェクトを作成します。
   - コマンド例: `npx create-video remotion-project --unattended` (または、適切なテンプレート指定があれば `npx create-video remotion-project --template blank --unattended`)
2. **依存関係のインストール**:
   - 生成された `remotion-project` ディレクトリに移動し、`npm install` または `npm ci` を実行して依存関係を解決します。
3. **必要な設定の追加**:
   - `remotion-project` 内のファイルを編集し、生成したい動画のコンポーネント（Composition）やプロパティを設定します。

## 3. 実際の動画生成の手順

環境構築が完了し、動画用のReactコンポーネントが準備できた後、動画のレンダリングを行います。

1. **出力先ディレクトリの確認**:
   - プロジェクトルートに `Movie/out/` ディレクトリが存在しない場合は作成します。
2. **GPUアクセラレーションの指定**:
   - レンダリング時は必ず `--gl=angle` またはプラットフォームに適したGPUフラグを付与します。
3. **レンダリングコマンドの実行**:
   - `remotion-project` ディレクトリ内で以下のコマンドを実行します。
   - コマンド例: `npx remotion render src/index.ts <CompositionName> ../Movie/out/output_video.mp4 --gl=angle`
   - ※ `<CompositionName>` は `src/index.ts` (または `src/Root.tsx`) に定義されたCompositionのIDに置き換えてください。
   - ※ 出力ファイル名はタイムスタンプ等を利用し、一意な名前にしてください（例: `../Movie/out/pitch_163820.mp4`）。

## 注意事項

- Remotionに関する生成ファイル（`remotion-project/` および `Movie/out/`）はファイルサイズが大きくなるため、リポジトリにコミットしないようにしてください。（`.gitignore` で除外する）
- この手順はAgentのPythonコードから `subprocess` や `os.system` 等で自動実行可能（ADK Playgroundから実行可能）な形で実装されることが想定されています。
