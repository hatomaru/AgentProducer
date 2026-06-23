from pydantic import BaseModel
from typing import Optional

class WorkflowState(BaseModel):
    user_idea: str
    draft: Optional[str] = None
    research_result: Optional[str] = None
    critic_feedback: Optional[str] = None
    revision_count: int = 0

class AgentProducerWorkflow:
    def __init__(self):
        from src.agents.planner import PlannerAgent
        from src.agents.researcher import ResearchAgent
        from src.agents.critic import CriticAgent
        
        self.planner = PlannerAgent()
        self.researcher = ResearchAgent()
        self.critic = CriticAgent()
        
    def planner_node(self, state: WorkflowState) -> WorkflowState:
        draft = self.planner.generate_draft(
            user_idea=state.user_idea,
            previous_draft=state.draft,
            critic_feedback=state.critic_feedback
        )
        state.draft = draft
        state.revision_count += 1
        return state
