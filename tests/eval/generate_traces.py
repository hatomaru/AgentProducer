import asyncio
import json
import os
import sys

# Optional SSL handling for Windows environments as per project rules
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from adk_agents.producer.agent import root_agent
from google.adk.runners import InMemoryRunner
from google.genai import types

async def run_scenario(runner, dataset_item):
    session_id = f"session_{dataset_item['id']}"
    
    await runner.session_service.create_session(
        app_name=runner.app_name, user_id="eval_user", session_id=session_id
    )
    
    print(f"Running scenario: {dataset_item['id']}")
    
    # Start workflow
    async for event in runner.run_async(
        session_id=session_id,
        user_id="eval_user",
        state_delta={"title": dataset_item["title"], "idea": dataset_item["idea"]}
    ):
        if getattr(event, 'type', '') == 'request_input' or type(event).__name__ == 'RequestInput':
            print("Intercepted human-in-the-loop review step")
            break
            
    # Provide human-in-the-loop feedback
    msg = types.Content(parts=[types.Part.from_text(text=dataset_item["expected_feedback"])], role="user")
    
    async for event in runner.run_async(session_id=session_id, user_id="eval_user", new_message=msg):
        if getattr(event, 'type', '') == 'request_input' or type(event).__name__ == 'RequestInput':
            break
            
    # If it was a feedback scenario, we need to approve the second draft to finish
    if dataset_item["expected_action"] == "feedback":
        msg2 = types.Content(parts=[types.Part.from_text(text="Approve")], role="user")
        async for event in runner.run_async(session_id=session_id, user_id="eval_user", new_message=msg2):
            if getattr(event, 'type', '') == 'request_input' or type(event).__name__ == 'RequestInput':
                break

    session = await runner.session_service.get_session(app_name=runner.app_name, user_id="eval_user", session_id=session_id)
    state = session.state
    
    # Extract trace/state details into the trace output
    return {
        "id": dataset_item["id"],
        "input": dataset_item["idea"],
        "expected_output": dataset_item["expected_action"],
        "trace": state
    }

async def main():
    runner = InMemoryRunner(agent=root_agent)
    dataset_path = os.path.join(os.path.dirname(__file__), "datasets", "basic-dataset.json")
    
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
        
    traces = []
    for item in dataset:
        try:
            trace = await run_scenario(runner, item)
            traces.append(trace)
        except Exception as e:
            print(f"Error running scenario {item['id']}: {e}")
            traces.append({
                "id": item["id"],
                "input": item["idea"],
                "expected_output": item["expected_action"],
                "error": str(e)
            })

    output_dir = os.path.join(os.path.dirname(__file__), "../../artifacts/traces")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "generated_traces.json")
    
    with open(output_path, "w") as f:
        json.dump(traces, f, indent=2)
        
    print(f"Successfully generated traces and saved to {output_path}")

if __name__ == "__main__":
    asyncio.run(main())
