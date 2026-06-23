import os
from google import genai

class ResearchAgent:
    def __init__(self):
        self.client = genai.Client()
        self.model = "gemini-2.5-flash"

    def research(self, draft: str) -> str:
        prompt = f"""
あなたは優秀なリサーチャー（Research Agent）です。
以下の企画ドラフトに関連する類似作品や市場傾向を推測・調査し、結果をまとめてください。

【企画ドラフト】
{draft}

以下の項目を含めて出力してください。
- 類似作品・競合
- 差別化ポイント
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            return f"類似作品: 既存アプリ\n競合: 多数\n\n(APIエラーまたはキー未設定のためフォールバック出力: {e})"
