import pytest
from src.workflow.graph import AgentProducerWorkflow, WorkflowState

def test_workflow_initial_state():
    # ワークフローの初期化とステートのテスト
    workflow = AgentProducerWorkflow()
    state = WorkflowState(user_idea="AIを使ったタスク管理アプリ")
    
    assert state.user_idea == "AIを使ったタスク管理アプリ"
    assert state.draft is None
    assert state.revision_count == 0

def test_workflow_planner_node():
    # Plannerノード単体の動作テスト
    workflow = AgentProducerWorkflow()
    state = WorkflowState(user_idea="テストアイデア")
    
    # Plannerノードを実行
    new_state = workflow.planner_node(state)
    assert new_state.draft is not None
    assert new_state.revision_count == 1
