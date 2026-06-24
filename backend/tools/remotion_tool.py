import os
import subprocess
import time
from google.adk.tools import FunctionTool

def generate_remotion_video(title: str, composition_id: str = "MyComp") -> str:
    """
    Remotionを用いて指定されたテーマに基づき背景動画やピッチ動画を生成します。
    
    Args:
        title (str): 動画のタイトルやテーマ。ファイル名の一部として利用されます。
        composition_id (str): 生成するコンポジション名 (デフォルト: HelloWorld)
    
    Returns:
        str: 動画生成の実行結果（成功時のファイルパスやエラーメッセージ）
    """
    # 実行時のカレントディレクトリはプロジェクトルートを想定
    project_root = os.getcwd()
    project_dir = os.path.join(project_root, "remotion-project")
    out_dir = os.path.join(project_root, "Movie", "out")
    
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. 環境構築の確認と作成
    if not os.path.exists(os.path.join(project_dir, "package.json")):
        print(f"[{time.strftime('%H:%M:%S')}] {project_dir} が見つかりません。新規作成します...")
        try:
            # shell=True is needed on Windows for npx
            subprocess.run(
                ["npx", "create-video", "remotion-project", "--unattended"],
                cwd=project_root,
                check=True,
                shell=True
            )
        except Exception as e:
            return f"Remotion環境構築に失敗しました: {str(e)}"

    # 2. 動画のレンダリング
    timestamp = int(time.time())
    safe_title = "".join([c if c.isalnum() else "_" for c in title])[:20]
    output_filename = f"{safe_title}_{timestamp}.mp4"
    # remotion render command needs relative or absolute path correctly. We use absolute here.
    output_path = os.path.join(out_dir, output_filename)
    
    try:
        print(f"[{time.strftime('%H:%M:%S')}] 動画を生成中: {output_path}")
        subprocess.run(
            ["npx", "remotion", "render", "src/index.ts", composition_id, output_path, "--gl=angle"],
            cwd=project_dir,
            check=True,
            shell=True
        )
        return f"動画の生成が完了しました。出力先: {output_path}"
    except Exception as e:
        return f"動画のレンダリングに失敗しました: {str(e)}"

remotion_tool = FunctionTool(generate_remotion_video)
