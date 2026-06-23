"use client";

import { useState } from "react";

export default function Home() {
  const [idea, setIdea] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [loading, setLoading] = useState(false);
  const [state, setState] = useState<any>(null);

  const startWorkflow = async () => {
    setLoading(true);
    const newSessionId = "session_" + Date.now();
    setSessionId(newSessionId);
    try {
      const res = await fetch("http://localhost:8000/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: newSessionId, user_idea: idea })
      });
      const data = await res.json();
      setState(data);
    } catch (e) {
      alert("Error starting workflow");
    } finally {
      setLoading(false);
    }
  };

  const handleReview = async (action: string, revisionNote?: string) => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:8000/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, action, revision_note: revisionNote || "" })
      });
      const data = await res.json();
      setState(data.state);
    } catch (e) {
      alert("Error reviewing");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 text-gray-800 p-8">
      <main className="max-w-4xl mx-auto space-y-8">
        <h1 className="text-3xl font-bold">Agent Producer (ADK 2.0)</h1>

        {!state ? (
          <div className="bg-white p-6 rounded-lg shadow">
            <h2 className="text-xl mb-4">企画アイデアを入力</h2>
            <textarea
              className="w-full p-3 border rounded mb-4"
              rows={4}
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              placeholder="例: 自動でレシピを考えてくれるアプリ"
            />
            <button
              onClick={startWorkflow}
              disabled={loading || !idea}
              className="bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "Generating..." : "スタート"}
            </button>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="bg-white p-6 rounded-lg shadow">
              <h2 className="text-xl font-bold mb-2">現在のステータス: {state.status}</h2>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-white p-6 rounded-lg shadow">
                <h3 className="font-bold text-lg mb-2">企画ドラフト</h3>
                <pre className="whitespace-pre-wrap text-sm bg-gray-100 p-4 rounded h-64 overflow-y-auto">
                  {state.draft}
                </pre>
              </div>
              <div className="space-y-6">
                <div className="bg-white p-6 rounded-lg shadow">
                  <h3 className="font-bold text-lg mb-2">調査結果</h3>
                  <pre className="whitespace-pre-wrap text-sm bg-gray-100 p-4 rounded h-32 overflow-y-auto">
                    {state.research_result}
                  </pre>
                </div>
                <div className="bg-white p-6 rounded-lg shadow">
                  <h3 className="font-bold text-lg mb-2">Criticの指摘</h3>
                  <pre className="whitespace-pre-wrap text-sm bg-gray-100 p-4 rounded h-32 overflow-y-auto">
                    {state.critic_feedback}
                  </pre>
                </div>
              </div>
            </div>

            {state.status === "pending_review" && (
              <div className="bg-blue-50 p-6 rounded-lg shadow border border-blue-200">
                <h2 className="text-xl font-bold mb-4">Review Gate (人間確認)</h2>
                <div className="flex space-x-4">
                  <button
                    onClick={() => handleReview("approve")}
                    disabled={loading}
                    className="bg-green-600 text-white px-6 py-2 rounded hover:bg-green-700"
                  >
                    Approve (承認して進む)
                  </button>
                  <button
                    onClick={() => {
                      const note = prompt("修正指示を入力してください:");
                      if (note) handleReview("revise", note);
                    }}
                    disabled={loading}
                    className="bg-yellow-500 text-white px-6 py-2 rounded hover:bg-yellow-600"
                  >
                    Revise (指示して修正)
                  </button>
                  <button
                    onClick={() => handleReview("reject")}
                    disabled={loading}
                    className="bg-red-600 text-white px-6 py-2 rounded hover:bg-red-700"
                  >
                    Reject (却下)
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
