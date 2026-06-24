import asyncio
import truststore
truststore.inject_into_ssl()

from adk_agents.producer.agent import root_agent
from google.adk.runners import Runner

async def test_resume():
    runner = Runner(agent=root_agent)
    input_data = {"title": "Test Video", "idea": "This is a test idea for a recipe app."}
    session_id = "test-session-12345"
    
    print("=== START ===")
    
    # 最初の実行
    async for event in runner.run_async(input_data, session_id=session_id):
        print(f"EVENT: {event.node_info.node_path if hasattr(event, 'node_info') and event.node_info else 'Unknown'}")
        if getattr(event, 'request_input', None) or hasattr(event, 'actions') and getattr(event.actions, 'route', None):
            print(">>> Hit RequestInput! Stopping.")
            break
            
    print(f"=== Session ID: {session_id} ===")
    
    # 再開
    print("=== RESUME with Approve ===")
    runner2 = Runner(agent=root_agent)
    
    from google.genai import types
    async for event in runner2.run_async(
        session_id=session_id, 
        new_message=types.Content(parts=[types.Part.from_text("Approve")], role="user")
    ):
        print(f"EVENT: {event.node_info.node_path if hasattr(event, 'node_info') and event.node_info else 'Unknown'}")

if __name__ == "__main__":
    asyncio.run(test_resume())
