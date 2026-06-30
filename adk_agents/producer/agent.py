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
    language: Optional[str] = Field(default="en", description="Language for output (e.g. 'ja' or 'en')")
    force_japanese: bool = Field(default=False, description="Force output to be in Japanese regardless of input language")
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
            # JSON解析できない単なる自然言語テキストの場合、最初の入力か途中入力（レビュー）か判別できないため、
            # idea と review_output の両方にセットしておきます。
            # 後続のルーター（start_router または route_after_approval）が現在のステート（企画書が存在するか等）に応じて自動で適切な方を採用します。
            return {"idea": text, "review_output": text}

class ProducerState(BaseModel):
    """
    ワークフロー全体で共有されるステート（状態）スキーマ。
    各エージェントはこのステートを読み書きしながら処理を進めます。
    """
    language: str = "en"
    force_japanese: bool = False
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
        import re
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', query):
            prompt = f"以下のクエリでWeb検索を行い、結果を要約して詳細を提供してください。必ず日本語で出力してください: {query}"
        else:
            prompt = f"Perform a web search for the following query, summarize the results, and provide details: {query}"
            
        client = Client()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
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
    idea: str = Field(description="The original project idea. Extract and output this exactly as it was provided.")
    title: str = Field(description="The project title. Extract and output this if provided, otherwise generate a suitable short title.")
    draft: str

class ResearchOutput(BaseModel):
    research: str

class CriticOutput(BaseModel):
    critic_feedback: str = Field(description="フィードバックテキスト。要求された言語（例えば日本語）で必ず記述すること。 (Feedback text. Must be written in the requested language, e.g. Japanese.)")
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

def _safe_state_get(state: Any, key: str, default: Any = "") -> Any:
    """
    ADK 2.x の State オブジェクト（dict-like だが dict のサブクラスではない）
    および通常の dict の両方から安全に値を取得するヘルパー。
    """
    try:
        # State クラスは .get() メソッドをサポート
        if hasattr(state, 'get'):
            return state.get(key, default)
        # フォールバック: 属性アクセス
        return getattr(state, key, default)
    except Exception:
        return default

def _get_original_idea(ctx: Any) -> str:
    idea = ""
    try:
        idea = _safe_state_get(ctx.state, "idea", "")
    except Exception:
        pass
        
    if not idea:
        try:
            if hasattr(ctx, "input") and ctx.input:
                if isinstance(ctx.input, dict):
                    idea = ctx.input.get("idea", "")
                elif hasattr(ctx.input, 'get'):
                    idea = ctx.input.get("idea", "")
                else:
                    idea = getattr(ctx.input, "idea", "")
        except Exception:
            pass
            
    if not idea and hasattr(ctx, "state"):
        try:
            for attr_key in ["planner_output", "producer_agent_output"]:
                obj = _safe_state_get(ctx.state, attr_key, None)
                if obj:
                    if isinstance(obj, dict):
                        idea = obj.get("idea", "")
                    elif hasattr(obj, "idea"):
                        idea = getattr(obj, "idea", "")
                    if idea:
                        break
        except Exception:
            pass

    if idea and "[Additional Requests/Modification Instructions from User]" in idea:
        idea = idea.split("[Additional Requests/Modification Instructions from User]")[0].strip()
    return str(idea) if idea else ""

def _get_language(ctx: Any) -> str:
    lang = "en"
    force_jp = False
    # force_japaneseフラグがTrueの場合は常に "ja" を返す
    try:
        force_jp = _safe_state_get(ctx.state, "force_japanese", False)
    except Exception:
        force_jp = False
    if force_jp:
        return "ja"
    try:
        lang = _safe_state_get(ctx.state, "language", "en")
    except Exception:
        pass
        
    return lang

def _get_state_value(ctx: Any, key: str) -> str:
    val = ""
    try:
        val = _safe_state_get(ctx.state, key, "")
        if not val:
            # state内のネストされたオブジェクトからも検索
            for attr_key in ["planner_output", "searcher_output", "researcher_output", "critic_output", "final_planner_output"]:
                obj = _safe_state_get(ctx.state, attr_key, None)
                if obj:
                    if isinstance(obj, dict) and key in obj:
                        val = obj[key]
                        break
                    elif hasattr(obj, 'get'):
                        candidate = obj.get(key, "")
                        if candidate:
                            val = candidate
                            break
                    elif hasattr(obj, key):
                        val = getattr(obj, key, "")
                        if val:
                            break
    except Exception:
        pass
    return str(val) if val else ""

def get_planner_instruction(ctx: Any) -> str:
    idea = _get_original_idea(ctx)
    lang = _get_language(ctx)
    
    if lang == "ja":
        return f"""あなたは優秀な企画プロデューサーです。ステートに含まれる 'title' と 'idea' をもとに、詳細な企画書のドラフトを作成してください。
もし入力として 'previous_final_draft'（前回作成した最終企画書）と 'user_feedback'（ユーザーからの修正指示）が与えられた場合は、ゼロから作成するのではなく、前回の内容をブラッシュアップし、ユーザーからのフィードバックの反映を最優先に行なってください。

[CRITICAL INSTRUCTION]
このプロジェクトの中核となるのは以下のオリジナルアイデアです。このアイデアに厳密に従い、コアコンセプトから絶対に逸脱しないでください。
--- ORIGINAL IDEA ---
{idea}
---------------------

抽象的なアイデアを目的、ターゲット層、体験価値、MVP、実装手順などに分解し、詳細な企画書のドラフトを作成してください。
出力は必ず提供されたJSONスキーマに従って構造化してください。
必ず、あなたが認識した元のアイデアをそのまま 'idea' フィールドに、タイトルを 'title' フィールドに格納し、生成したドラフトを 'draft' フィールドにMarkdown形式で含めてください。
必ず日本語で出力してください。"""
    else:
        return f"""You are an excellent planning producer. Based on the 'title' and 'idea' included in the current state, summarize them into a detailed project proposal draft.
If 'previous_final_draft' (the final proposal created last time) and 'user_feedback' (modification instructions from the user) are provided as inputs, do not start from scratch. Instead, brush up the proposal based on the previous content while giving top priority to reflecting the user's feedback.

[CRITICAL INSTRUCTION]
The core of this project is the following original idea. You MUST strictly adhere to this idea and DO NOT deviate from its core concept.
--- ORIGINAL IDEA ---
{idea}
---------------------

Break down abstract ideas into objectives, target audience, experiential value, MVP, and implementation sequence, and output in Markdown format."""

def get_critic_instruction(ctx: Any) -> str:
    idea = _get_original_idea(ctx)
    draft = _get_state_value(ctx, "draft")
    research = _get_state_value(ctx, "research")
    
    base_instruction = f"""あなたは鋭い視点を持つ批評家（Critic）です。ステートに含まれる 'draft' と 'research' を読み、提案の弱点、リスク、および改善案を指摘して、企画をさらにブラッシュアップしてください。

[CRITICAL INSTRUCTION]
このプロジェクトの中核となるのは以下のオリジナルアイデアです。
--- ORIGINAL IDEA ---
{idea}
---------------------
あなたは、'draft'がこのコアコンセプトに厳密に沿っているかを検証しなければなりません。もしドラフトがこのコンセプトから逸脱している場合は、それを強く指摘し、プランナーに元のコンセプトに戻るよう指示する必要があります。

構造化されたJSONスキーマに従って出力してください。テキストの末尾に手動でJSON文字列を追加しないでください。
内容が不十分で追加のリサーチが必要な場合は、JSONパラメータ `needs_more_research` を true に設定し、フィードバックテキスト内にリサーチャー向けの追加調査ポイントを含めてください。十分な場合は false に設定してください。
必ずブール値として出力してください。文字列の 'true' や 'false' は使用せず、JSONのブール値（true / false）として指定してください。
言語設定に関わらず、フィードバック内容は必ず日本語で出力してください。"""

    return f"{base_instruction}\n\n=== DRAFT ===\n{draft}\n\n=== RESEARCH ===\n{research}"

def get_final_planner_instruction(ctx: Any) -> str:
    idea = _get_original_idea(ctx)
    lang = _get_language(ctx)
    draft = _get_state_value(ctx, "draft")
    research = _get_state_value(ctx, "research")
    critic_feedback = _get_state_value(ctx, "critic_feedback")
    
    if lang == "ja":
        base_instruction = f"""あなたは優秀な企画プロデューサーです。これまで得られたアイデア、リサーチ結果、criticのフィードバックなど、ステート内のすべての情報を統合し、最終的なプロジェクト企画書を完成させてください。

[CRITICAL INSTRUCTION]
このプロジェクトの中核となるのは以下のオリジナルアイデアです。リサーチ結果やcriticのフィードバックを取り入れる際にも、このアイデアに厳密に従い、コアコンセプトから絶対に逸脱しないでください。
--- ORIGINAL IDEA ---
{idea}
---------------------

目的、ターゲット層、体験価値、MVP、実装手順などを綺麗に整理し、Markdown形式で出力してください。
必ず日本語で出力してください。"""
    else:
        base_instruction = f"""You are an excellent planning producer. Integrate all the information in the state, including ideas, research results, and critic feedback obtained so far, and complete the final project proposal.

[CRITICAL INSTRUCTION]
The core of this project is the following original idea. You MUST strictly adhere to this idea and DO NOT deviate from its core concept even when incorporating research results and critic feedback.
--- ORIGINAL IDEA ---
{idea}
---------------------

Organize the objectives, target audience, experiential value, MVP, implementation sequence, etc. neatly, and output in Markdown format."""

    return f"{base_instruction}\n\n=== CURRENT DRAFT ===\n{draft}\n\n=== RESEARCH ===\n{research}\n\n=== CRITIC FEEDBACK ===\n{critic_feedback}"

planner_agent = Agent(
    name="planner",
    instruction=get_planner_instruction,
    output_schema=PlannerOutput,
    model="gemini-2.5-flash",
)

def get_searcher_instruction(ctx: Any) -> str:
    lang = _get_language(ctx)
    draft = _get_state_value(ctx, "draft")
    critic_feedback = _get_state_value(ctx, "critic_feedback")
    
    if lang == "ja":
        base_instruction = """あなたは優秀なリサーチャーです。ステートに含まれる 'draft'（企画書ドラフト）について、市場調査、競合、必要な技術などの深掘り調査を行なってください。
もしステートに 'critic_feedback' がある場合、それはcriticからの「再調査依頼や指摘事項」です。前回の 'research' 内容に加え、特にその指摘箇所を重点的に深掘りし、最新情報を取得してください。
最新情報を取得するために、必ずWeb検索ツール（perform_web_search）を使用してください。
[IMPORTANT] 検索ツールの使用は最大5回までに制限してください。過剰なループを避け、その5回以内の検索で得られた情報に基づいて必ず回答を生成し終了してください。
必ず日本語で出力してください。"""
    else:
        base_instruction = """You are an excellent researcher. Conduct an in-depth investigation into market research, competitors, and required technologies for the 'draft' (project proposal draft) included in the state.
If 'critic_feedback' is present in the state, it represents 'requests or points for re-investigation' from the critic. In addition to the previous 'research' content, focus heavily on those points and obtain the latest information.
You must use the web search tool (perform_web_search) to acquire the latest information.
[IMPORTANT] Limit the use of the search tool to a maximum of 5 times. Avoid excessive search loops, and ensure you generate a response and complete the process based on the information obtained within those 5 searches."""

    return f"{base_instruction}\n\n=== CURRENT DRAFT ===\n{draft}\n\n=== CRITIC FEEDBACK ===\n{critic_feedback}"

def get_researcher_instruction(ctx: Any) -> str:
    lang = _get_language(ctx)
    draft = _get_state_value(ctx, "draft")
    
    if lang == "ja":
        base_instruction = """あなたはリサーチ内容をまとめる担当エージェントです。ステートに含まれる 'searcher' の出力やこれまでの情報を整理し、最終的なリサーチレポートとしてまとめてください。
必ず日本語で出力してください。"""
    else:
        base_instruction = """You are an agent responsible for summarizing research content. Organize the output of the 'searcher' and the information gathered so far included in the state, and compile it into a final research report."""

    return f"{base_instruction}\n\n=== CURRENT DRAFT ===\n{draft}"

searcher_agent = Agent(
    name="searcher",
    instruction=get_searcher_instruction,
    tools=[web_search_tool],
    model="gemini-2.5-flash",
)

researcher_agent = Agent(
    name="researcher",
    instruction=get_researcher_instruction,
    output_schema=ResearchOutput,
    model="gemini-2.5-flash",
)

critic_agent = Agent(
    name="critic",
    instruction=get_critic_instruction,
    output_schema=CriticOutput,
    output_key="critic_output",
    model="gemini-2.5-flash",
)

final_planner_agent = Agent(
    name="final_planner",
    instruction=get_final_planner_instruction,
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
    
    lang = _get_language(ctx)
    if lang == "ja":
        return f"""あなたはプレゼン資料とピッチ用の台本を作成するプロデューサーエージェントです。
以下の 'final_draft'（承認済みの企画書）の内容をもとに、以下の2点を作成してください：
1. presentation_plan: プレゼンの構成案（各セクションの要点と流れ）
2. pitch_script: 30秒程度のピッチ用台本（具体的な内容を含む読み上げ原稿）

企画書の内容を具体的に反映し、プレースホルダー（XXXなど）を使わず、実際の中身を埋め込んでください。
必ず日本語で出力してください。

=== 承認済みプロジェクト企画書 (final_draft) ===
{final_draft}
==================================
"""
    else:
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

def get_check_approval_instruction(ctx: Any) -> str:
    lang = _get_language(ctx)
    if lang == "ja":
        return """あなたは入力メッセージ抽出エージェントです。
チャット履歴の一番最後にある、ユーザーの最新の応答（承認、拒否、修正指示など）のみに注目してください。
あなたの唯一のタスクは、過去の文脈を無視し、ユーザーが最後に入力したメッセージの正確なテキストをそのまま一言一句 'exact_text' として出力することです。
過去のやり取りに影響されず、承認の判断、推論、要約、解釈などは一切行わないでください。必ず日本語で出力してください。"""
    else:
        return """You are an input message extraction agent.
Focus solely on the user's latest response (approval, rejection, or modification request, etc.) at the very end of the chat history.
Your only task is to output the exact text the user entered in the last message as 'exact_text', word for word, ignoring any past context.
Do not be influenced by past interactions, and do not make any approval judgments, inferences, summaries, or interpretations."""

check_approval_agent = Agent(
    name="check_approval_agent",
    model="gemini-2.5-flash",
    output_schema=ExtractFeedbackOutput,
    output_key="review_output",
    instruction=get_check_approval_instruction
)

# =====================================================================
# 5. ルーティング関数・カスタムノード (Routing & Custom Nodes)
# =====================================================================

# --- ADK 2.x 互換: エージェント出力 → state 保存用の中間ノード ---
# ADK 2.x では、Workflow 内でエージェントの output は node_input として
# 下流ノードに渡されるだけで、state には自動保存されない。
# 下流のエージェント（critic等）が ctx.state 経由で読み取れるよう、
# 出力フィールドを明示的に state に書き込む中間ノードが必要。

def save_planner_output(node_input: Any = None):
    """
    planner_agent の出力（PlannerOutput: idea, title, draft）を
    state に個別フィールドとして展開・保存する中間ノード。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    state_updates = {}
    if node_input:
        if hasattr(node_input, 'get'):
            # dict または dict-like オブジェクト
            for key in ["idea", "title", "draft"]:
                val = node_input.get(key, "")
                if val:
                    state_updates[key] = val
        elif isinstance(node_input, str):
            # テキスト出力の場合はdraftとして保存
            if node_input.strip():
                state_updates["draft"] = node_input
        else:
            # BaseModel等の場合
            for key in ["idea", "title", "draft"]:
                val = getattr(node_input, key, "")
                if val:
                    state_updates[key] = val
    
    logger.warning(f"[DEBUG save_planner_output] Saving to state: {list(state_updates.keys())}, draft length: {len(state_updates.get('draft', ''))}")
    
    if state_updates:
        return Event(state=state_updates)
    return None

def save_research_output(node_input: Any = None):
    """
    researcher_agent の出力（ResearchOutput: research）を
    state に保存する中間ノード。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    research = ""
    if node_input:
        if hasattr(node_input, 'get'):
            research = node_input.get("research", "") or ""
        elif hasattr(node_input, "research"):
            research = getattr(node_input, "research", "") or ""
        elif isinstance(node_input, str) and node_input.strip():
            research = node_input
    
    logger.warning(f"[DEBUG save_research_output] Research length: {len(research)}")
    
    if research:
        return Event(state={"research": research})
    return None

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
        if new_loop_count >= 3:
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

def ask_review_node(ctx: Any, final_draft: str = ""):
    """
    Human-in-the-loop (HITL) のためのカスタムノード。
    ここでワークフローを一時中断し、ユーザーからの承認またはフィードバックを待ちます。
    """
    lang = _get_language(ctx)
    if lang == "ja":
        msg = f"=== 最終ドラフト ===\n{final_draft}\n===================\nこの内容で進めてよろしいですか？（Approve または フィードバック を入力してください）"
    else:
        msg = f"=== Final Draft ===\n{final_draft}\n===================\nIs it okay to proceed with this content? (Please enter Approve / Feedback)"
        
    return RequestInput(
        message=msg,
        interrupt_id=f"human_review_{uuid.uuid4().hex[:8]}"
    )

def find_user_input_anywhere(ctx: Any) -> str:
    # 1. 既知のプロパティから探索
    for attr_name in ["input", "request", "message", "event", "user_input"]:
        obj = getattr(ctx, attr_name, None)
        if obj:
            if isinstance(obj, dict):
                if obj.get("idea"): return obj["idea"]
                if obj.get("text"): return obj["text"]
            else:
                if getattr(obj, "idea", ""): return getattr(obj, "idea", "")
                if getattr(obj, "text", ""): return getattr(obj, "text", "")
    
    # 2. messages 履歴から最後のユーザーメッセージ
    messages = getattr(ctx, "messages", getattr(ctx, "history", []))
    if messages and isinstance(messages, list):
        for msg in reversed(messages):
            role = getattr(msg, "role", "") or (msg.get("role", "") if isinstance(msg, dict) else "")
            if role == "user":
                parts = getattr(msg, "parts", []) or (msg.get("parts", []) if isinstance(msg, dict) else [])
                if parts:
                    if isinstance(parts[0], dict) and parts[0].get("text"):
                        return parts[0]["text"]
                    elif getattr(parts[0], "text", ""):
                        return getattr(parts[0], "text", "")
                elif isinstance(msg, str):
                    return msg
                elif isinstance(msg, dict) and msg.get("text"):
                    return msg["text"]
                    
    # 3. session_metadata (Playgroundのフォールバック)
    metadata = getattr(ctx, "session_metadata", None)
    if metadata and isinstance(metadata, dict):
        if metadata.get("displayName"):
            return metadata["displayName"]
            
    # 4. 強制抽出 (最後の手段)
    import re
    ctx_str = str(ctx)
    match = re.search(r"##\s+.*?ゲーム概要.*?(?='|\"|\n\n\n|$)", ctx_str, re.DOTALL)
    if match:
        return match.group(0)
        
    return ""

def start_router(ctx: Any, node_input: Any = None):
    """
    ワークフロー開始/再開時のルーティング関数。
    初期入力の idea と title を明示的にステートに保存します。
    
    ADK 2.x では Workflow の input_schema でパースされた結果は node_input として
    渡されるため、node_input からも idea/title を取得します。
    """
    import logging
    logger = logging.getLogger(__name__)
    
    idea = ""
    title = ""
    final_draft = ""

    # 1. node_input から取得（ADK 2.x: Workflowのinput_schemaパース結果）
    if node_input:
        if hasattr(node_input, 'get'):
            # dict または dict-like オブジェクト（ADK 2.x State含む）
            idea = node_input.get("idea", "") or ""
            title = node_input.get("title", "") or ""
        elif hasattr(node_input, "idea"):
            idea = getattr(node_input, "idea", "") or ""
            title = getattr(node_input, "title", "") or ""
        # types.Content の場合はテキストを idea として扱う
        elif hasattr(node_input, "parts") and node_input.parts:
            for part in node_input.parts:
                if hasattr(part, "text") and part.text:
                    idea = part.text
                    break

    # 2. state からも取得（既存のstateに値がある場合を優先）
    if hasattr(ctx, "state") and ctx.state:
        state_idea = _safe_state_get(ctx.state, "idea", "")
        state_title = _safe_state_get(ctx.state, "title", "")
        final_draft = _safe_state_get(ctx.state, "final_draft", "")
        # state に既に値がある場合はそちらを優先
        if state_idea:
            idea = state_idea
        if state_title:
            title = state_title

    # 3. フォールバック: どこからも取得できなかった場合
    if not idea:
        idea = find_user_input_anywhere(ctx)

    logger.warning(f"[DEBUG start_router] title: {title}, idea length: {len(idea)}, final_draft length: {len(final_draft)}")
    
    if final_draft:
        return Event(route="check_approval_agent")
        
    state_updates = {}
    if idea:
        state_updates["idea"] = idea
    if title:
        state_updates["title"] = title
        
    if state_updates:
        return Event(route="planner", state=state_updates)
    else:
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
        save_planner_output,     # planner出力をstateに保存
        searcher_agent, 
        researcher_agent, 
        save_research_output,    # researcher出力をstateに保存
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
        # planner → save_planner_output → searcher（draftをstateに保存してから検索）
        (planner_agent, save_planner_output),
        (save_planner_output, searcher_agent),
        (searcher_agent, researcher_agent),
        # researcher → save_research_output → critic（researchをstateに保存してからcritic）
        (researcher_agent, save_research_output),
        (save_research_output, critic_agent),
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
