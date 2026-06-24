import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import truststore
from dotenv import load_dotenv

# 文字化けとSSLエラー対策
truststore.inject_into_ssl()
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from google.adk.runners import InMemoryRunner

app = FastAPI(title="Agent Producer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions = {}

class StartRequest(BaseModel):
    session_id: str
    user_idea: str

class ActionRequest(BaseModel):
    session_id: str
    action: str  # "approve", "revise", "reject"
    revision_note: str | None = None

@app.get("/")
async def root():
    return {"message": "Agent Producer API is running. Please access the frontend at http://localhost:3000"}

async def run_agent(agent, prompt: str) -> dict:
    runner = InMemoryRunner(agent=agent)
    events = await runner.run_debug(prompt, quiet=True)
    for e in reversed(events):
        if hasattr(e, 'message') and e.message and hasattr(e.message, 'parts'):
            for part in e.message.parts:
                if hasattr(part, 'text') and part.text:
                    try:
                        # Extract the JSON text. Sometimes it is wrapped in ```json ... ```
                        text = part.text.strip()
                        if text.startswith("```json"):
                            text = text.removeprefix("```json").removesuffix("```").strip()
                        elif text.startswith("```"):
                            text = text.removeprefix("```").removesuffix("```").strip()
                        return json.loads(text)
                    except:
                        pass
    return {}

from adk_agents.producer.agent import root_agent
from google.adk.runners import InMemoryRunner

workflow_runners = {}

class StartRequest(BaseModel):
    title: str = ""
    user_idea: str
    session_id: str

@app.post("/start")
async def start_workflow(req: StartRequest):
    input_data = {"title": req.title, "idea": req.user_idea}
    runner = InMemoryRunner(agent=root_agent)
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="default_user", session_id=req.session_id
    )
    workflow_runners[req.session_id] = runner
    
    final_draft = ""
    # Run the workflow
    async for event in runner.run_async(session_id=req.session_id, user_id="default_user", state_delta=input_data):
        print(f"[DEBUG /start] Got event from node: {getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'}")
        if hasattr(event, 'output') and event.output is not None:
            # The final_planner_agent outputs the final draft.
            if hasattr(event, 'node_info') and event.node_info and getattr(event.node_info, 'node_path', '') == "final_planner":
                if hasattr(event.output, "final_draft"):
                    final_draft = event.output.final_draft
                elif isinstance(event.output, dict) and "final_draft" in event.output:
                    final_draft = event.output["final_draft"]

        # fallback if not caught from event
        if not final_draft and hasattr(event, 'state') and event.state:
            if isinstance(event.state, dict) and "draft" in event.state:
                final_draft = event.state["draft"]
            elif hasattr(event.state, 'draft'):
                final_draft = event.state.draft

    if isinstance(final_draft, str):
        final_draft = final_draft.replace("\\n", "\n")

    sessions[req.session_id] = {
        "title": req.title,
        "user_idea": req.user_idea,
        "draft": final_draft,
        "status": "pending_review",
        "video_result": ""
    }

    return {"message": final_draft}

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]

from google.genai import types

@app.post("/review")
async def review_gate(req: ActionRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    state = sessions[req.session_id]
    runner = workflow_runners.get(req.session_id)
    if not runner:
        raise HTTPException(status_code=500, detail="Workflow runner not found for this session")
    
    if req.action == "approve":
        state["status"] = "processing_video"
        
        video_result = ""
        msg = types.Content(parts=[types.Part.from_text(text="Approve")], role="user")
        print(f"[DEBUG /review] Resuming runner with message: Approve")
        
        # 1. 再開用のメッセージを渡して中断を解除する（ADKの仕様上、ここで一度ジェネレータが完了することがある）
        state_delta = {"final_draft": state.get("draft", "")}
        async for event in runner.run_async(session_id=req.session_id, user_id="default_user", new_message=msg, state_delta=state_delta):
            print(f"[DEBUG /review init] Got event from node: {getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'}")
            
        # 2. 残りのワークフロー（producer_agent -> video_agent）を最後まで回す
        print(f"[DEBUG /review] Continuing runner to finish workflow")
        async for event in runner.run_async(session_id=req.session_id, user_id="default_user", state_delta=state_delta):
            print(f"[DEBUG /review continue] Got event from node: {getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'}")
            if hasattr(event, 'output') and event.output is not None:
                if hasattr(event, 'node_info') and event.node_info and getattr(event.node_info, 'node_path', '') == "video_agent":
                    if hasattr(event.output, "video_result"):
                        video_result = event.output.video_result
                    elif isinstance(event.output, dict) and "video_result" in event.output:
                        video_result = event.output["video_result"]
        
        state["video_result"] = video_result
        state["status"] = "approved"
        return {"message": "Draft approved and video generated.", "state": state}
        
    elif req.action == "revise":
        msg = types.Content(parts=[types.Part.from_text(text=f"Reject: {req.revision_note}")], role="user")
        
        final_draft = ""
        state_delta = {"final_draft": state.get("draft", "")}
        # 1. 中断解除
        async for event in runner.run_async(session_id=req.session_id, user_id="default_user", new_message=msg, state_delta=state_delta):
            pass
            
        # 2. 継続実行
        async for event in runner.run_async(session_id=req.session_id, user_id="default_user"):
            if hasattr(event, 'output') and event.output is not None:
                if hasattr(event, 'node_info') and event.node_info and getattr(event.node_info, 'node_path', '') == "final_planner":
                    if hasattr(event.output, "final_draft"):
                        final_draft = event.output.final_draft
                    elif isinstance(event.output, dict) and "final_draft" in event.output:
                        final_draft = event.output["final_draft"]
        
            if not final_draft and hasattr(event, 'state') and event.state:
                if isinstance(event.state, dict) and "draft" in event.state:
                    final_draft = event.state["draft"]
                elif hasattr(event.state, 'draft'):
                    final_draft = event.state.draft
                    
        if final_draft:
            state["draft"] = final_draft
            
        state["status"] = "pending_review"
        return {"message": "Draft revised.", "state": state}
        
    elif req.action == "reject":
        state["status"] = "rejected"
        return {"message": "Draft rejected.", "state": state}
        
    raise HTTPException(status_code=400, detail="Invalid action")
