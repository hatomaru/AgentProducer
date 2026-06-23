import asyncio
import sys
sys.path.insert(0, '.')
import truststore
truststore.inject_into_ssl()

from google.adk import Agent
from pydantic import BaseModel
from google.adk.runners import InMemoryRunner

class PlannerOutput(BaseModel):
    draft: str

planner_agent_no_input = Agent(
    name="planner",
    instruction="Generate a draft for the given app idea.",
    output_schema=PlannerOutput,
    model="gemini-2.5-flash",
)

async def main():
    try:
        runner = InMemoryRunner(agent=planner_agent_no_input)
        events = await runner.run_debug("Test idea: a recipe app")
        for e in events:
            print("---")
            if hasattr(e, 'message') and e.message:
                print("MESSAGE DIR:", dir(e.message))
                if hasattr(e.message, 'parts'):
                    print("PARTS:", e.message.parts)
                elif hasattr(e.message, 'content'):
                    print("CONTENT:", e.message.content)
            if hasattr(e, 'model_output'):
                print("MODEL_OUTPUT:", e.model_output)
    except Exception as ex:
        print("ERROR:", ex)

if __name__ == '__main__':
    asyncio.run(main())
