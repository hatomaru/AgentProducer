import sys
import os
import truststore
import json
import re
import uuid
from typing import Any
from pydantic import BaseModel, Field, model_validator

# --- SSL証明書の検証エラーを回避するための設定 ---
truststore.inject_into_ssl()

# 必要に応じてプロジェクトルートを sys.path に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from google.genai import Client, types
from google.adk import Agent, Workflow
from google.adk.tools import FunctionTool
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput

# 外部からのインポート（例: remotion 動画生成ツール）
from backend.tools.remotion_tool import remotion_tool

# =====================================================================
# 1. スキーマ定義 (Schemas)
# =====================================================================

from typing import Any, Optional

class ProducerInput(BaseModel):
    """
    ワークフロー開始時の初期入力スキーマ、および再開時のユーザー入力スキーマ。
    """
    title: Optional[str] = Field(default=None, description="企画のタイトル名")
    idea: Optional[str] = Field(default=None, description="企画のアイデア詳細")
    review_output: Optional[str] = Field(default=None, description="人間からのフィードバックテキスト")

    @model_validator(mode='before')
    @classmethod
    def extract_from_content(cls, data):
        # ADKがMessageオブジェクト等で渡してきた場合への対応
        text = ""
        if hasattr(data, "parts") and data.parts:
            text = data.parts[0].text
        elif isinstance(data, dict):
            return data
        else:
            text = str(data)
            
        try:
            parsed = json.loads(text)
            if "title" in parsed or "idea" in parsed:
                return parsed
            else:
                return {"review_output": text}
        except Exception:
            # JSON解析できない単なるテキストの場合、初期入力ならidea、途中入力（レビュー）ならreview_outputとして扱う
            # ここでは安全のため、辞書形式でなければすべて review_output 扱いにする
            # 呼び出し元（初期起動）はdictで初期ステートを渡す前提
            return {"review_output": text}

class ProducerState(BaseModel):
    """
    ワークフロー全体で共有されるステート（状態）スキーマ。
    各エージェントはこのステートを読み書きしながら処理を進めます。
    """
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
    review_output: Any = None
    final_planner_output: Any = None


# =====================================================================
# 2. ツール定義 (Tools)
# =====================================================================

def perform_web_search(query: str) -> str:
    """
    Web検索を行い、関連する情報を取得して要約します。
    Google Gemini の google_search ツール機能を利用しています。
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

# エージェントが利用できるようにFunctionToolでラップする
web_search_tool = FunctionTool(perform_web_search)


# =====================================================================
# 3. エージェントの出力スキーマ定義 (Agent Output Schemas)
# =====================================================================

class PlannerOutput(BaseModel):
    draft: str

class ResearchOutput(BaseModel):
    research: str

class CriticOutput(BaseModel):
    critic_feedback: str
    needs_more_research: bool

    @model_validator(mode='before')
    @classmethod
    def extract_bool(cls, data):
        # GeminiがJSONを文字列等で返してきた場合の堅牢なパース処理
        if isinstance(data, dict):
            feedback = data.get("critic_feedback", "")
            if isinstance(feedback, str):
                match = re.search(r'"?needs_more_research"?\s*:\s*(true|false)', feedback, re.IGNORECASE)
                if match:
                    val_str = match.group(1).lower()
                    data["needs_more_research"] = (val_str == "true")
                    data["critic_feedback"] = feedback[:match.start()].strip().rstrip(',').rstrip('{').rstrip('}')
        return data

class FinalPlannerOutput(BaseModel):
    final_draft: str

class ProducerAgentOutput(BaseModel):
    presentation_plan: str
    pitch_script: str

class VideoAgentOutput(BaseModel):
    video_script: str
    video_result: str


# =====================================================================
# 4. エージェント定義 (Agents)
# =====================================================================

planner_agent = Agent(
    name="planner",
    instruction="""あなたは優秀な企画プロデューサーです。現在のステートに含まれる「title」と「idea」をもとに、詳細な企画書ドラフトにまとめます。
入力（Input）として「previous_final_draft」（前回作成した最終企画書）と「user_feedback」（ユーザーからの修正指示）が渡されている場合は、一から作り直すのではなく、前回の企画内容をベースにしつつ、ユーザーの修正指示を最優先で反映して企画をブラッシュアップしてください。
抽象的なアイデアを、目的・ターゲット・体験価値・MVP・実装順序に分解してMarkdown形式で出力してください。""",
    output_schema=PlannerOutput,
    model="gemini-2.5-flash",
)

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

final_planner_agent = Agent(
    name="final_planner",
    instruction="""あなたは優秀な企画プロデューサーです。これまでのアイデア、リサーチ結果、および批評家のフィードバックなど、ステートにある全ての情報を統合し、最終的な企画書を完成させてください。
目的・ターゲット・体験価値・MVP・実装順序などを綺麗に整理し、Markdown形式で出力してください。""",
    output_schema=FinalPlannerOutput,
    output_key="final_planner_output",
    model="gemini-2.5-flash",
)

def get_producer_instruction(ctx: Any) -> str:
    final_draft = ""
    try:
        final_draft = ctx.state.get("final_draft", "")
    except Exception:
        pass
    
    return f"""あなたはプレゼン資料やピッチ原稿を作成するProducer Agentです。
以下の「final_draft」（承認済み企画書）の内容をもとに、指定された2つを作成してください：
1. presentation_plan: 発表用の構成案（セクションごとの要点と流れ）
2. pitch_script: 30秒程度のピッチ原稿（具体的な内容を含めた、実際に読み上げ可能な台本）

企画書の内容を具体的に反映し、プレースホルダー（〇〇など）は使わずに実際の内容で埋めてください。

=== 承認済み企画書 (final_draft) ===
{final_draft}
==================================
"""

producer_agent = Agent(
    name="producer_agent",
    instruction=get_producer_instruction,
    output_schema=ProducerAgentOutput,
    model="gemini-2.5-flash",
)

def get_video_instruction(ctx: Any) -> str:
    pitch_script = ""
    title = ""
    try:
        pitch_script = ctx.state.get("pitch_script", "")
        title = ctx.state.get("title", "")
    except Exception:
        pass
        
    return f"""あなたはVideo Agentです。以下の「pitch_script」をもとに、ショート動画の台本(video_script)を作成し、さらにRemotion動画生成ツールを呼び出して実際に動画を出力してください。
動画のタイトルやテーマは「{title}」としてください。ツール呼び出しの結果をvideo_resultに格納してください。

=== ピッチ原稿 (pitch_script) ===
{pitch_script}
==================================
"""

video_agent = Agent(
    name="video_agent",
    instruction=get_video_instruction,
    tools=[remotion_tool],
    output_schema=VideoAgentOutput,
    model="gemini-2.5-flash",
)

# --- Human-In-The-Loop (HITL) 関連エージェント ---

class ExtractFeedbackOutput(BaseModel):
    exact_text: str = Field(description="ユーザーが直前に入力したメッセージの正確な全文。要約や解釈はせずそのまま出力すること。")

check_approval_agent = Agent(
    name="check_approval_agent",
    model="gemini-2.5-flash",
    output_schema=ExtractFeedbackOutput,
    output_key="review_output",
    instruction="""
あなたは入力メッセージの抽出エージェントです。
チャット履歴の一番最後にある、ユーザーの最新の返答（承認、却下、あるいは修正依頼など）のみに注目してください。
あなたの唯一の任務は、一番最後のメッセージでユーザーが入力したテキストを、過去の文脈を無視して、一言一句違えずにそのまま「exact_text」として出力することです。
過去のやり取りに引っ張られたり、承認の判断、推論、要約、解釈などは一切行わないでください。
"""
)

# =====================================================================
# 5. ルーティング関数・カスタムノード (Routing & Custom Nodes)
# =====================================================================

def check_research(critic_output: Any = None, loop_count: int = 0):
    """
    Criticのフィードバックを確認し、さらにリサーチが必要かを判定するルーティング関数。
    無限ループを防ぐため、最大ループ回数を3回に制限します。
    """
    needs_more = False
    critic_feedback = ""
    
    if critic_output:
        if isinstance(critic_output, dict):
            needs_more = critic_output.get("needs_more_research", False)
            critic_feedback = critic_output.get("critic_feedback", "")
        else:
            if hasattr(critic_output, "needs_more_research"):
                needs_more = critic_output.needs_more_research
            if hasattr(critic_output, "critic_feedback"):
                critic_feedback = critic_output.critic_feedback
            
    new_loop_count = loop_count
    
    if needs_more:
        new_loop_count += 1
        if new_loop_count >= 1:
            needs_more = False
            
    route_name = "searcher" if needs_more else "final_planner"
    return Event(
        route=route_name, 
        state={
            "loop_count": new_loop_count,
            "needs_more_research": needs_more,
            "critic_feedback": critic_feedback
        }
    )

def save_final_draft(final_planner_output: Any = None, final_draft: str = ""):
    """
    final_planner_agent の出力をローカルで抽出し、確実にステートの final_draft に代入して渡すためのノード。
    """
    draft_text = final_draft
    if final_planner_output:
        if hasattr(final_planner_output, "final_draft") and final_planner_output.final_draft:
            draft_text = final_planner_output.final_draft
        elif isinstance(final_planner_output, dict) and final_planner_output.get("final_draft"):
            draft_text = final_planner_output.get("final_draft", "")
        elif str(final_planner_output).strip():
            draft_text = str(final_planner_output)
            
    import logging
    logging.getLogger(__name__).warning(f"[DEBUG save_final_draft] Extracted final_draft length: {len(draft_text)}")
    
    return Event(route="ask_review_node", state={"final_draft": draft_text})

def ask_review_node():
    """
    Human-in-the-loop (HITL) のためのカスタムノード。
    ここでワークフローを一時中断し、ユーザーからの承認またはフィードバックを待ちます。
    """
    return RequestInput(
        message="この内容で進めてよろしいですか？（Approve / Reject / フィードバックを入力してください）",
        interrupt_id=f"human_review_{uuid.uuid4().hex[:8]}"
    )

def start_router(final_draft: str = ""):
    """
    ワークフロー再開時に、すでに企画書が完成している場合は承認プロセスから再開するためのルーティング関数。
    """
    import logging
    logging.getLogger(__name__).warning(f"[DEBUG start_router] final_draft length: {len(final_draft)}")
    if final_draft:
        return Event(route="check_approval_agent")
    return Event(route="planner")

def route_after_approval(ctx, review_output: Any = None, idea: str = "", final_draft: str = "", draft: str = "", final_planner_output: Any = None):
    """
    更新された review_output を見て分岐するルーティング関数。
    """
    import logging
    import json
    logger = logging.getLogger(__name__)
    
    # ステートから確実にfinal_draftを取得（パラメータよりctx.stateを優先）
    actual_draft = final_draft
    try:
        state_final_draft = ctx.state.get("final_draft", "")
        if state_final_draft and isinstance(state_final_draft, str):
            actual_draft = state_final_draft
    except Exception:
        pass
    
    # さらにフォールバック
    if not actual_draft:
        if final_planner_output:
            if hasattr(final_planner_output, "final_draft") and final_planner_output.final_draft:
                actual_draft = final_planner_output.final_draft
            elif isinstance(final_planner_output, dict) and final_planner_output.get("final_draft"):
                actual_draft = final_planner_output.get("final_draft", "")
            elif str(final_planner_output).strip():
                actual_draft = str(final_planner_output)
        if not actual_draft and draft:
            actual_draft = draft
    
    logger.warning(f"[DEBUG route_after_approval] actual_draft length: {len(actual_draft)}")
    
    text = ""
    try:
        if isinstance(review_output, str):
            text = review_output
        elif isinstance(review_output, dict):
            text = json.dumps(review_output, ensure_ascii=False)
        elif hasattr(review_output, 'exact_text'):
            text = str(review_output.exact_text)
        elif hasattr(review_output, 'args'):
            text = str(review_output.args)
        elif hasattr(review_output, 'model_dump_json'):
            text = review_output.model_dump_json()
        else:
            text = str(review_output)
            if hasattr(review_output, '__dict__'):
                text += " " + str(review_output.__dict__)
    except Exception as e:
        logger.error(f"Error parsing review_output: {e}")
        text = str(review_output)
        
    text_lower = text.lower()
    logger.warning(f"[DEBUG route_after_approval] Parsed text: {text_lower}")
    
    approval_keywords = ["approve", "承認", "ok", "オーケー", "はい", "進めて", "問題ない", "問題ありません", "good", "良いです"]
    rejection_keywords = ["reject", "却下", "修正", "直して", "変更して", "ダメ", "いいえ", "違います"]
    
    is_approved = any(kw in text_lower for kw in approval_keywords)
    
    # Approveキーワードが含まれていない場合のみ、Rejectキーワードを確認する
    # （両方含まれている場合は、Approveの意思を尊重する安全な設計）
    if not is_approved:
        if any(kw in text_lower for kw in rejection_keywords):
            is_approved = False
    
    if is_approved:
        logger.warning(f"[DEBUG route_after_approval] Routing to producer_agent with final_draft length: {len(actual_draft)}")

        # ステートのfinal_draftを明示的に更新しておく（UIの即時反映および後続のエージェントのため）
        try:
            ctx.state["final_draft"] = actual_draft
        except Exception as e:
            logger.error(f"Error updating state.final_draft: {e}")

        # output経由でfinal_draftの内容をproducer_agentに渡す
        # single_turnモードのAgentはnode_input経由でこの値を受け取る
        return Event(
            route="producer_agent",
            output={"final_draft": actual_draft},
            state={"final_draft": actual_draft}
        )
    else:
        # ユーザーの最初のインプット(idea)を保存し、そこにフィードバックを追記する形で更新する
        new_idea = idea + f"\n\n【ユーザーからの追加要望/修正指示】\n{review_output}"
        logger.warning("[DEBUG route_after_approval] Routing to planner with updated idea")
        # final_draftを空にすることで、次のループ再開時に正しくplannerから開始されるようにする
        # 同時に、これまでの完成版企画書(final_draft)を明示的な入力としてplannerへ渡し、ハルシネーションを防ぐ
        return Event(
            route="planner", 
            output={"previous_final_draft": actual_draft, "user_feedback": review_output},
            state={"idea": new_idea, "critic_feedback": review_output, "final_draft": ""}
        )


# =====================================================================
# 6. ワークフロー定義 (Workflow)
# =====================================================================

root_agent = Workflow(
    name="producer_workflow",
    input_schema=ProducerInput,
    state_schema=ProducerState,
    nodes=[
        planner_agent, 
        searcher_agent, 
        researcher_agent, 
        critic_agent, 
        final_planner_agent, 
        save_final_draft,
        ask_review_node, 
        check_approval_agent,
        producer_agent, 
        video_agent
    ],
    edges=[
        ("START", start_router, {
            "check_approval_agent": check_approval_agent,
            "planner": planner_agent
        }),
        (planner_agent, searcher_agent),
        (searcher_agent, researcher_agent),
        (researcher_agent, critic_agent),
        # Criticの判定による動的ルーティング
        (critic_agent, check_research, {
            "searcher": searcher_agent,
            "final_planner": final_planner_agent
        }),
        (final_planner_agent, save_final_draft),
        (save_final_draft, ask_review_node),
        (ask_review_node, check_approval_agent),
        # ユーザー承認結果による動的ルーティング (決定論的アプローチ)
        (check_approval_agent, route_after_approval, {
            "producer_agent": producer_agent,
            "planner": planner_agent
        }),
        (producer_agent, video_agent)
    ]
)
