from google.adk import Agent
from pydantic import BaseModel, model_validator
import re
from google.adk.tools import FunctionTool
from google.genai import Client, types
from typing import Any

class ProducerState(BaseModel):
    title: str = ""
    idea: str = ""
    draft: str = ""
    research: str = ""
    critic_feedback: str = ""
    needs_more_research: bool = False
    loop_count: int = 0
    final_draft: str = ""
    presentation_plan: str = ""
    pitch_script: str = ""
    video_script: str = ""
    video_result: str = ""
    searcher: str = ""
    critic_output: Any = None

def perform_web_search(query: str) -> str:
    """
    Web検索を行い、関連する情報を取得して要約します。
    
    Args:
        query: 検索クエリ
    """
    try:
        client = Client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"以下のクエリについてWeb検索を行い、結果を要約して詳細に教えてください: {query}",
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}],
                temperature=0.0,
            )
        )
        return response.text
    except Exception as e:
        return f"検索エラー: {str(e)}"

web_search_tool = FunctionTool(perform_web_search)

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

searcher_agent = Agent(
    name="searcher",
    instruction="""あなたは優秀なリサーチャーです。ステートに含まれる「draft」（企画書ドラフト）について、市場調査や競合、必要な技術について深堀り調査を行ってください。
もしステートに「critic_feedback」がある場合は、それは批評家からの「再調査の要求や指摘」です。以前の調査内容（research）に加えて、その指摘事項を重点的に深掘りし、最新の情報を取得してください。
必ずWeb検索ツール(perform_web_search)を利用して最新情報を取得してください。
【重要】検索ツールの呼び出しは絶対に最大5回までとしてください。過剰な検索ループを避け、5回以内の検索で得られた情報をもとに回答を生成して処理を終了してください。""",
    tools=[web_search_tool],
    model="gemini-2.5-flash",
)

researcher_agent = Agent(
    name="researcher",
    instruction="""あなたはリサーチ内容をまとめるエージェントです。ステートに含まれる「searcher」の出力やこれまでの情報を整理し、最終的な調査レポートとしてまとめてください。""",
    output_schema=ResearchOutput,
    model="gemini-2.5-flash",
)

from pydantic import BaseModel, Field

class CriticOutput(BaseModel):
    critic_feedback: str
    needs_more_research: bool

    @model_validator(mode='before')
    @classmethod
    def extract_bool(cls, data):
        if isinstance(data, dict):
            feedback = data.get("critic_feedback", "")
            if isinstance(feedback, str):
                import re
                match = re.search(r'"?needs_more_research"?\s*:\s*(true|false)', feedback, re.IGNORECASE)
                if match:
                    val_str = match.group(1).lower()
                    data["needs_more_research"] = (val_str == "true")
                    data["critic_feedback"] = feedback[:match.start()].strip().rstrip(',').rstrip('{').rstrip('}')
        return data

critic_agent = Agent(
    name="critic",
    instruction="""あなたは鋭い視点を持つ批評家です。ステートに含まれる「draft」と「research」を読み込み、企画の弱点、リスク、さらに良くするための改善提案を指摘してください。
必ず構造化されたJSONスキーマに沿って出力してください。テキスト文末に手動でJSON文字列を追記しないでください。
内容が不十分であり、さらにリサーチが必要な場合はJSONパラメータの `needs_more_research` を true にし、リサーチャーに対する追加の調査ポイントをフィードバックテキストに含めてください。十分な場合は false にしてください。
必ず真偽値のboolean型で出力してください。文字列の"true"や"false"ではなく、JSONの真偽値（true / false）として指定すること。""",
    output_schema=CriticOutput,
    output_key="critic_output",
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

class ProducerAgentOutput(BaseModel):
    presentation_plan: str
    pitch_script: str

producer_agent = Agent(
    name="producer_agent",
    instruction="""あなたはプレゼン資料やピッチ原稿を作成するProducer Agentです。
ステートの「final_draft」（承認済み企画書）をもとに、発表用の構成案(presentation_plan)と、30秒程度のピッチ原稿(pitch_script)を作成してください。""",
    output_schema=ProducerAgentOutput,
    model="gemini-2.5-flash",
)

from backend.tools.remotion_tool import remotion_tool

class VideoAgentOutput(BaseModel):
    video_script: str
    video_result: str

video_agent = Agent(
    name="video_agent",
    instruction="""あなたはVideo Agentです。Producer Agentが作成した「pitch_script」をもとに、ショート動画の台本(video_script)を作成し、さらにRemotion動画生成ツールを呼び出して実際に動画を出力してください。
動画のタイトルやテーマは、ステートの「title」を使用してください。ツール呼び出しの結果をvideo_resultに格納してください。""",
    tools=[remotion_tool],
    output_schema=VideoAgentOutput,
    model="gemini-2.5-flash",
)
