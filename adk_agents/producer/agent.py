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
# from backend.tools.remotion_tool import remotion_tool

# =====================================================================
# 1. スキーマ定義 (Schemas)
# =====================================================================

from typing import Any, Optional

class ProducerInput(BaseModel):
    """
    ワークフロー開始時の初期入力スキーマ、および再開時のユーザー入力スキーマ。
    """
    title: Optional[str] = Field(default=None, description="Project title")
    idea: Optional[str] = Field(default=None, description="Project idea details")
    review_output: Optional[str] = Field(default=None, description="Feedback text from human")

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
    producer_agent_output: Any = None


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
            contents=f"Perform a web search for the following query, summarize the results, and provide details: {query}",
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




# =====================================================================
# 4. エージェント定義 (Agents)
# =====================================================================

planner_agent = Agent(
    name="planner",
    instruction="""You are an excellent planning producer. Based on the 'title' and 'idea' included in the current state, summarize them into a detailed project proposal draft.
If 'previous_final_draft' (the final proposal created last time) and 'user_feedback' (modification instructions from the user) are provided as inputs, do not start from scratch. Instead, brush up the proposal based on the previous content while giving top priority to reflecting the user's feedback.
Break down abstract ideas into objectives, target audience, experiential value, MVP, and implementation sequence, and output in Markdown format.""",
    output_schema=PlannerOutput,
    model="gemini-2.5-flash",
)

searcher_agent = Agent(
    name="searcher",
    instruction="""You are an excellent researcher. Conduct an in-depth investigation into market research, competitors, and required technologies for the 'draft' (project proposal draft) included in the state.
If 'critic_feedback' is present in the state, it represents 'requests or points for re-investigation' from the critic. In addition to the previous 'research' content, focus heavily on those points and obtain the latest information.
You must use the web search tool (perform_web_search) to acquire the latest information.
[IMPORTANT] Limit the use of the search tool to a maximum of 5 times. Avoid excessive search loops, and ensure you generate a response and complete the process based on the information obtained within those 5 searches.""",
    tools=[web_search_tool],
    model="gemini-2.5-flash",
)

researcher_agent = Agent(
    name="researcher",
    instruction="""You are an agent responsible for summarizing research content. Organize the output of the 'searcher' and the information gathered so far included in the state, and compile it into a final research report.""",
    output_schema=ResearchOutput,
    model="gemini-2.5-flash",
)

critic_agent = Agent(
    name="critic",
    instruction="""You are a critic with a sharp perspective. Read the 'draft' and 'research' included in the state, and point out the proposal's weaknesses, risks, and suggestions for improvement to make it even better.
You must output according to the structured JSON schema. Do not manually append JSON strings at the end of the text.
If the content is insufficient and more research is needed, set the JSON parameter `needs_more_research` to true, and include additional investigation points for the researcher in the feedback text. If it is sufficient, set it to false.
Be sure to output as a boolean value. Do not use string 'true' or 'false', but specify it as a JSON boolean value (true / false).""",
    output_schema=CriticOutput,
    output_key="critic_output",
    model="gemini-2.5-flash",
)

final_planner_agent = Agent(
    name="final_planner",
    instruction="""You are an excellent planning producer. Integrate all the information in the state, including ideas, research results, and critic feedback obtained so far, and complete the final project proposal.
Organize the objectives, target audience, experiential value, MVP, implementation sequence, etc. neatly, and output in Markdown format.""",
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
    
    return f"""You are a Producer Agent responsible for creating presentation materials and pitch scripts.
Based on the content of the following 'final_draft' (approved project proposal), create the following two items:
1. presentation_plan: Outline for the presentation (key points and flow per section)
2. pitch_script: A 30-second pitch script (a readable script including specific details)

Reflect the content of the proposal specifically, and fill it with actual content without using placeholders (like XXX).

=== Approved Project Proposal (final_draft) ===
{final_draft}
==================================
"""

producer_agent = Agent(
    name="producer_agent",
    instruction=get_producer_instruction,
    output_schema=ProducerAgentOutput,
    output_key="producer_agent_output",
    model="gemini-2.5-flash",
)



# --- Human-In-The-Loop (HITL) 関連エージェント ---

class ExtractFeedbackOutput(BaseModel):
    exact_text: str = Field(description="The exact full text of the message the user just entered. Output it exactly as is without summarizing or interpreting.")

check_approval_agent = Agent(
    name="check_approval_agent",
    model="gemini-2.5-flash",
    output_schema=ExtractFeedbackOutput,
    output_key="review_output",
    instruction="""
You are an input message extraction agent.
Focus solely on the user's latest response (approval, rejection, or modification request, etc.) at the very end of the chat history.
Your only task is to output the exact text the user entered in the last message as 'exact_text', word for word, ignoring any past context.
Do not be influenced by past interactions, and do not make any approval judgments, inferences, summaries, or interpretations.
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

def ask_review_node(final_draft: str = ""):
    """
    Human-in-the-loop (HITL) のためのカスタムノード。
    ここでワークフローを一時中断し、ユーザーからの承認またはフィードバックを待ちます。
    """
    return RequestInput(
        message=f"=== Final Draft ===\n{final_draft}\n===================\nIs it okay to proceed with this content? (Please enter Approve / Feedback)",
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
    
    is_approved = any(kw in text_lower for kw in approval_keywords)
    
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
        new_idea = idea + f"\n\n[Additional Requests/Modification Instructions from User]\n{review_output}"
        logger.warning("[DEBUG route_after_approval] Routing to planner with updated idea")
        # final_draftを空にすることで、次のループ再開時に正しくplannerから開始されるようにする
        # 同時に、これまでの完成版企画書(final_draft)を明示的な入力としてplannerへ渡し、ハルシネーションを防ぐ
        return Event(
            route="planner", 
            output={"previous_final_draft": actual_draft, "user_feedback": text},
            state={"idea": new_idea, "critic_feedback": text, "final_draft": ""}
        )

async def save_artifacts_node(ctx: Any, producer_agent_output: Any = None, pitch_script: str = ""):
    """
    producer_agentの処理完了後、企画のピッチ文と最終的な企画書を
    Artifactsとして登録（ファイル書き出し＋artifact_delta発行）する。
    """
    extracted_pitch = pitch_script
    if producer_agent_output:
        if hasattr(producer_agent_output, "pitch_script") and producer_agent_output.pitch_script:
            extracted_pitch = producer_agent_output.pitch_script
        elif isinstance(producer_agent_output, dict) and producer_agent_output.get("pitch_script"):
            extracted_pitch = producer_agent_output.get("pitch_script", "")
        elif str(producer_agent_output).strip() and not extracted_pitch:
            extracted_pitch = str(producer_agent_output)
            
    final_draft = ctx.state.get("final_draft", "")
    
    # ADKのContextを用いてArtifactをセッション領域に保存する
    from google.genai import types
    
    # ADKのフロントエンドで空文字だと「missing mimeType or data or text」エラーになるのを防ぐため、空の場合はプレースホルダーを入れる
    safe_pitch_script = extracted_pitch if extracted_pitch.strip() else "(Pitch script has not been generated)"
    safe_final_draft = final_draft if final_draft.strip() else "(Project proposal has not been generated)"
    
    pitch_script_version = await ctx.save_artifact("pitch_script.md", types.Part.from_text(text=safe_pitch_script))
    final_draft_version = await ctx.save_artifact("final_draft.md", types.Part.from_text(text=safe_final_draft))
        
    return Event(
        actions={"artifact_delta": {"pitch_script.md": pitch_script_version, "final_draft.md": final_draft_version}}
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
        save_artifacts_node
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
        (check_approval_agent, route_after_approval, {
            "producer_agent": producer_agent,
            "planner": planner_agent
        }),
        (producer_agent, save_artifacts_node)
    ]
)
