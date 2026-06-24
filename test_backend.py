import asyncio
import truststore
truststore.inject_into_ssl()
from fastapi.testclient import TestClient
from backend.main import app

def run_test():
    client = TestClient(app)
    session_id = "test_session_999"
    
    print("=== Sending /start request ===")
    response = client.post("/start", json={
        "session_id": session_id,
        "title": "Test Title",
        "user_idea": "test idea for a cooking app"
    })
    
    print(f"Status: {response.status_code}")
    print(f"Message: {response.json().get('message')}")
    
    print("\n=== Sending /review (Approve) ===")
    response2 = client.post("/review", json={
        "session_id": session_id,
        "action": "approve"
    })
    
    print(f"Status: {response2.status_code}")
    # print full json for inspection
    import json
    print(json.dumps(response2.json(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    run_test()
