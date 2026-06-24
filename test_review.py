import asyncio
import truststore
truststore.inject_into_ssl()

import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from adk_agents.producer.agent import root_agent
from google.adk.runners import InMemoryRunner
from google.genai import types

async def main():
    runner = InMemoryRunner(agent=root_agent)
    session_id = "test_review_session_fast"
    
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="default_user", session_id=session_id
    )
    
    print("=== Start Workflow ===")
    async for event in runner.run_async(
        session_id=session_id,
        user_id="default_user",
        state_delta={"title": "テスト企画", "idea": "テストアイデア"}
    ):
        node = getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'
        print(f"[DEBUG /start] Event from: {node}")
        if getattr(event, 'type', '') == 'request_input' or type(event).__name__ == 'RequestInput':
            break

    print("\n=== Review (Approve) ===")
    msg = types.Content(parts=[types.Part.from_text(text="Approve")], role="user")
    
    # new_message を渡して再開（最初の1ステップ）
    async for event in runner.run_async(session_id=session_id, user_id="default_user", new_message=msg):
        node = getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'
        print(f"[DEBUG /review init] Event from: {node}, Route: {getattr(event, 'route', 'None')}")
        
    # その後、ワークフローが完了するまで継続実行
    print("\n=== Continuing Workflow ===")
    async for event in runner.run_async(session_id=session_id, user_id="default_user"):
        node = getattr(event.node_info, 'node_path', 'unknown') if hasattr(event, 'node_info') else 'unknown'
        print(f"[DEBUG /review continue] Event from: {node}, Route: {getattr(event, 'route', 'None')}")

if __name__ == "__main__":
    asyncio.run(main())
