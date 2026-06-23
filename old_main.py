import sys
import truststore
from dotenv import load_dotenv

# 文字化け対策: 標準入出力をUTF-8に強制
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stdin.encoding.lower() != 'utf-8':
    sys.stdin.reconfigure(encoding='utf-8')

from src.workflow.graph import AgentProducerWorkflow, WorkflowState

# グローバルルールに従い、OSの証明書ストアを利用する
truststore.inject_into_ssl()
load_dotenv()

def main():
    print("=== Agent Producer (MVP) ===")
    user_idea = input("企画アイデアを入力してください: ")
    if not user_idea.strip():
        user_idea = "AIを使ったタスク管理アプリ"
        print(f"空入力のため、デフォルトのアイデア「{user_idea}」を使用します。")
    
    workflow = AgentProducerWorkflow()
    state = WorkflowState(user_idea=user_idea)
    
    # 1. Planner Agent
    print("\n[Planner Agent] ドラフトを作成中...")
    state = workflow.planner_node(state)
    
    # 2. Research Agent
    print("\n[Research Agent] 類似作品・市場を調査中...")
    state.research_result = workflow.researcher.research(state.draft)
    
    # 3. Critic Agent
    print("\n[Critic Agent] 企画の弱点を分析中...")
    state.critic_feedback = workflow.critic.evaluate(state.draft, state.research_result)
    
    # 自己批評ループ (MVPは1回実行)
    print("\n[Planner Agent] 指摘を受けてドラフトを修正中...")
    state = workflow.planner_node(state)
    
    # Review Gate
    print("\n" + "="*40)
    print("【Review Gate】 確認用ドラフトが生成されました。")
    print("="*40)
    print(f"\n{state.draft}\n")
    print("-" * 40)
    print(f"調査結果:\n{state.research_result}\n")
    print("-" * 40)
    print(f"Criticのフィードバック:\n{state.critic_feedback}\n")
    print("="*40)
    
    while True:
        choice = input("アクションを選択してください [1: Approve, 2: Revise, 3: Reject]: ")
        if choice == "1":
            print("\n✅ 企画が承認されました。Producer Agent (次フェーズ) へ引き継ぎます...")
            with open("approved_draft.md", "w", encoding="utf-8") as f:
                f.write(state.draft)
            print("承認済みドラフトを approved_draft.md に保存しました。")
            break
        elif choice == "2":
            revision_note = input("修正指示を入力してください: ")
            print(f"\n🔄 Revise: 修正指示「{revision_note}」を受け付けました。再実行します...")
            break
        elif choice == "3":
            print("\n❌ Reject: Planner Agent に差し戻します。")
            break
        else:
            print("無効な選択です。")

if __name__ == "__main__":
    main()
