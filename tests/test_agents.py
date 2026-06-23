import pytest
import os
from src.agents.planner import PlannerAgent
from src.agents.researcher import ResearchAgent
from src.agents.critic import CriticAgent

def test_planner_agent():
    agent = PlannerAgent()
    user_idea = "AIを使ったタスク管理アプリ"
    draft = agent.generate_draft(user_idea)
    
    assert draft is not None
    # 実際のAPIレスポンスまたはフォールバックが返ることを確認
    assert len(draft) > 10

def test_research_agent():
    agent = ResearchAgent()
    draft = "AIを使ったタスク管理アプリ"
    research_result = agent.research(draft)
    
    assert research_result is not None
    assert len(research_result) > 10

def test_critic_agent():
    agent = CriticAgent()
    draft = "AIを使ったタスク管理アプリ"
    research_result = "類似アプリ多数"
    feedback = agent.evaluate(draft, research_result)
    
    assert feedback is not None
    assert len(feedback) > 10
