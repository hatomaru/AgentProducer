import os
from google import genai

class CriticAgent:
    def __init__(self):
        self.client = genai.Client()
        self.model = "gemini-2.5-flash"

    def evaluate(self, draft: str, research_result: str) -> str:
        prompt = f"""
あなたは厳しい評論家（Critic Agent）です。
以下の企画ドラフトと調査結果を元に、企画の弱点やリスクを洗い出し、改善案を提示してください。

【企画ドラフト】
{draft}

【調査結果】
{research_result}

以下の項目を含めて出力してください。
- 企画上の弱点
- 改善提案
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            return f"弱点: 差別化が弱い\n課題: 体験をもっと明確に。\n\n(APIエラーまたはキー未設定のためフォールバック出力: {e})"
