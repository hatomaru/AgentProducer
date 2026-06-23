import os
from google import genai

class PlannerAgent:
    def __init__(self):
        # APIキーは環境変数 GEMINI_API_KEY から自動取得されます
        self.client = genai.Client()
        self.model = "gemini-2.5-flash"

    def generate_draft(self, user_idea: str, previous_draft: str = None, critic_feedback: str = None) -> str:
        if previous_draft and critic_feedback:
            prompt = f"""
あなたは優秀な企画担当（Planner Agent）です。
以前のドラフトに対してCriticからフィードバックがありました。これを踏まえてドラフトを改善してください。

【元のアイデア】
{user_idea}

【以前のドラフト】
{previous_draft}

【Criticからのフィードバック】
{critic_feedback}

フィードバックを反映した新しい企画ドラフトをMarkdown形式で出力してください。
"""
        else:
            prompt = f"""
あなたは優秀な企画担当（Planner Agent）です。
以下のユーザーのアイデアを元に、企画ドラフトを作成してください。

【ユーザーのアイデア】
{user_idea}

以下の項目を含めてMarkdown形式で出力してください。
- 概要
- コア体験
- ターゲットユーザー
- MVP範囲
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            # フォールバック処理 (APIキー未設定時などテスト用)
            return f"# 概要\n\n{user_idea}の企画ドラフトです。\n\n## MVP\n最小限の実装。\n\n(APIエラーまたはキー未設定のためフォールバック出力: {e})"
