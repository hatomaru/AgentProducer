import asyncio
import truststore
truststore.inject_into_ssl()

import os
from adk_agents.producer.agent import root_agent
from google.adk.runners import InMemoryRunner
from google.genai import types
import json

async def main():
    runner = InMemoryRunner(agent=root_agent)
    session_id = "artifact_session"
    
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="default_user", session_id=session_id
    )
    
    print("=== Start Workflow ===")
    async for event in runner.run_async(
        session_id=session_id,
        user_id="default_user",
        state_delta={"title": "AI英会話アプリ", "idea": "ユーザーのレベルに合わせて英会話を教えてくれるAIアプリ。"}
    ):
        if getattr(event, 'type', '') == 'request_input' or type(event).__name__ == 'RequestInput':
            break

    print("\n=== Review (Approve) ===")
    msg = types.Content(parts=[types.Part.from_text(text="問題ない")], role="user")
    
    async for event in runner.run_async(session_id=session_id, user_id="default_user", new_message=msg):
        pass
        
    print("\n=== Continuing Workflow ===")
    async for event in runner.run_async(session_id=session_id, user_id="default_user"):
        pass

    state = await runner.session_service.get_state(app_name=runner.app_name, user_id="default_user", session_id=session_id)
    final_draft = state.get("final_draft", "")
    pitch_script = state.get("pitch_script", "")
    
    with open("output_artifact.json", "w", encoding="utf-8") as f:
        json.dump({"final_draft": final_draft, "pitch_script": pitch_script}, f, ensure_ascii=False)

if __name__ == "__main__":
    asyncio.run(main())
