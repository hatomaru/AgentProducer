import json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import truststore
from dotenv import load_dotenv

# 文字化けとSSLエラー対策
truststore.inject_into_ssl()
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from backend.agents import planner_agent, researcher_agent, critic_agent
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

from google.adk.runners import Runner
from adk_agents.producer.agent import root_agent

class StartRequest(BaseModel):
    title: str = ""
    user_idea: str
    session_id: str

@app.post("/start")
async def start_workflow(req: StartRequest):
    input_data = {"title": req.title, "idea": req.user_idea}
    runner = Runner(agent=root_agent)
    
    final_draft = ""
    # Run the workflow
    async for event in runner.run_async(input_data):
        if event.output is not None:
            # The final_planner_agent outputs the final draft.
            # We can capture it if the node path is final_planner.
            if event.node_info and event.node_info.node_path == "final_planner":
                if hasattr(event.output, "final_draft"):
                    final_draft = event.output.final_draft
                elif isinstance(event.output, dict) and "final_draft" in event.output:
                    final_draft = event.output["final_draft"]

    # fallback if not caught from event
    if not final_draft:
        session = await runner.memory_service.get_session(runner.resumability_config.session_id)
        if session and "draft" in session.state:
            final_draft = session.state["draft"]

    if isinstance(final_draft, str):
        final_draft = final_draft.replace("\\n", "\n")

    sessions[req.session_id] = {
        "user_idea": req.user_idea,
        "draft": final_draft,
        "status": "pending_review"
    }

    return {"message": final_draft}

@app.get("/session/{session_id}")
async def get_session(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]

@app.post("/review")
async def review_gate(req: ActionRequest):
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
        
    state = sessions[req.session_id]
    
    if req.action == "approve":
        state["status"] = "approved"
        return {"message": "Draft approved.", "state": state}
        
    elif req.action == "revise":
        revise_prompt = f"Idea: {state['user_idea']}\nPrevious Draft: {state['draft']}\nUser Revision Note: {req.revision_note}"
        planner_out = await run_agent(planner_agent, revise_prompt)
        state["draft"] = planner_out.get("draft", state["draft"])
        state["status"] = "pending_review"
        return {"message": "Draft revised.", "state": state}
        
    elif req.action == "reject":
        state["status"] = "rejected"
        return {"message": "Draft rejected.", "state": state}
        
    raise HTTPException(status_code=400, detail="Invalid action")
