import sys
import os
import truststore
truststore.inject_into_ssl()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from google.adk import Workflow
from backend.agents import (
    planner_agent, searcher_agent, researcher_agent, critic_agent, final_planner_agent,
    producer_agent, video_agent, ProducerState
)
from pydantic import BaseModel, Field, model_validator
import json

class ProducerInput(BaseModel):
    title: str = Field(description="企画のタイトル名")
    idea: str = Field(description="企画のアイデア詳細")

    @model_validator(mode='before')
    @classmethod
    def extract_from_content(cls, data):
        if hasattr(data, "parts") and data.parts:
            text = data.parts[0].text
            try:
                return json.loads(text)
            except Exception:
                return {"title": "無題", "idea": text}
        return data

from google.adk.events.event import Event

def check_research(needs_more_research: bool = False, loop_count: int = 0):
    new_loop_count = loop_count
    needs_more = needs_more_research
    
    if needs_more:
        new_loop_count += 1
        if new_loop_count >= 3:
            needs_more = False
            
    route_name = "research" if needs_more else "final"
    return Event(
        route=route_name, 
        state={"loop_count": new_loop_count}
    )

root_agent = Workflow(
    name="producer",
    input_schema=ProducerInput,
    state_schema=ProducerState,
    nodes=[planner_agent, searcher_agent, researcher_agent, critic_agent, final_planner_agent],
    edges=[
        ("START", planner_agent),
        (planner_agent, searcher_agent),
        (searcher_agent, researcher_agent),
        (researcher_agent, critic_agent),
        (critic_agent, check_research, {
            "research": searcher_agent,
            "final": final_planner_agent
        })
    ]
)

class Phase2Input(BaseModel):
    title: str
    final_draft: str

    @model_validator(mode='before')
    @classmethod
    def extract_from_content(cls, data):
        if hasattr(data, "parts") and data.parts:
            text = data.parts[0].text
            try:
                return json.loads(text)
            except Exception:
                return {"title": "無題", "final_draft": text}
        return data

phase2_agent = Workflow(
    name="producer_phase2",
    input_schema=Phase2Input,
    state_schema=ProducerState,
    nodes=[producer_agent, video_agent],
    edges=[
        ("START", producer_agent),
        (producer_agent, video_agent)
    ]
)
