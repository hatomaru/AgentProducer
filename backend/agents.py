from google.adk import Agent
from pydantic import BaseModel, model_validator

class ProducerState(BaseModel):
    title: str = ""
    idea: str = ""
    draft: str = ""
    research: str = ""
    critic_feedback: str = ""
    needs_more_research: bool = False
    loop_count: int = 0

class PlannerOutput(BaseModel):
    draft: str

planner_agent = Agent(
    name="planner",
    instruction="""あなたは優秀な企画プロデューサーです。現在のステートに含まれる「title」と「idea」をもとに、詳細な企画書ドラフトにまとめます。
抽象的なアイデアを、目的・ターゲット・体験価値・MVP・実装順序に分解してMarkdown形式で出力してください。""",
    output_schema=PlannerOutput,
    model="gemini-2.5-flash",
)

class ResearchOutput(BaseModel):
    research: str

researcher_agent = Agent(
    name="researcher",
    instruction="""あなたは優秀なリサーチャーです。ステートに含まれる「draft」（企画書ドラフト）について、市場調査や競合、必要な技術について深堀り調査を行い、レポートを作成してください。
もしステートに「critic_feedback」がある場合は、それは批評家からの「再調査の要求や指摘」です。以前の調査内容（research）に加えて、その指摘事項を重点的に深掘りし、調査結果を更新してください。""",
    output_schema=ResearchOutput,
    model="gemini-2.5-flash",
)

import re

class CriticOutput(BaseModel):
    critic_feedback: str
    needs_more_research: bool

    @model_validator(mode='before')
    @classmethod
    def extract_bool(cls, data):
        if isinstance(data, dict):
            feedback = data.get("critic_feedback", "")
            if isinstance(feedback, str):
                match = re.search(r'"?needs_more_research"?\s*:\s*(true|false)', feedback, re.IGNORECASE)
                if match:
                    val_str = match.group(1).lower()
                    data["needs_more_research"] = (val_str == "true")
                    # Clean up the trailing garbage by splitting at the match
                    data["critic_feedback"] = feedback[:match.start()].strip().rstrip(',').rstrip('{').rstrip('}')
        return data

critic_agent = Agent(
    name="critic",
    instruction="""あなたは鋭い視点を持つ批評家です。ステートに含まれる「draft」と「research」を読み込み、企画の弱点、リスク、さらに良くするための改善提案を指摘してください。
必ず構造化されたJSONスキーマに沿って出力してください。テキスト文末に手動でJSON文字列を追記しないでください。
内容が不十分であり、さらにリサーチが必要な場合はJSONパラメータの `needs_more_research` を true にし、リサーチャーに対する追加の調査ポイントをフィードバックテキストに含めてください。十分な場合は false にしてください。""",
    output_schema=CriticOutput,
    model="gemini-2.5-flash",
)

class FinalPlannerOutput(BaseModel):
    final_draft: str

final_planner_agent = Agent(
    name="final_planner",
    instruction="""あなたは優秀な企画プロデューサーです。これまでのアイデア、リサーチ結果、および批評家のフィードバックなど、ステートにある全ての情報を統合し、最終的な企画書を完成させてください。
目的・ターゲット・体験価値・MVP・実装順序などを綺麗に整理し、Markdown形式で出力してください。""",
    output_schema=FinalPlannerOutput,
    model="gemini-2.5-flash",
)
