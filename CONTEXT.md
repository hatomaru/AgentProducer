# Project Context

## Development Practices & Guidelines

本プロジェクトでは以下の開発プラクティスとセキュリティモデリングを採用しています。
詳細なガイドラインはワークスペース内の `.agents/skills/tdd` および `.agents/skills/stride` に定義されています。

### 1. TDD (Test-Driven Development / テスト駆動開発)
コードの品質と堅牢性を保つため、TDDのサイクルを遵守して開発を進めます。
1. **Red**: 失敗するテストを最初に記述する。
2. **Green**: テストをパスさせるための最小限の実装を行う。
3. **Refactor**: 振る舞いを変えずにコードを整理・最適化する。

### 2. STRIDE Threat Modeling (脅威モデリング)
システム設計や新機能の追加時におけるセキュリティリスクの特定と対策のために、STRIDE手法を適用します。
各項目の観点でアーキテクチャや機能のレビューを行ってください。
- **S**poofing (なりすまし) - 対策: 認証
- **T**ampering (改ざん) - 対策: 完全性の確保
- **R**epudiation (否認) - 対策: 否認防止、ロギング
- **I**nformation Disclosure (情報漏洩) - 対策: 機密性の確保、暗号化
- **D**enial of Service (サービス拒否) - 対策: 可用性の確保
- **E**levation of Privilege (権限昇格) - 対策: 認可、最小権限の原則
