import sys
from unittest.mock import patch
from main import main

inputs = ["自動でレシピを考えてくれるアプリ", "1"]

def mock_input(prompt):
    print(prompt, end="")
    val = inputs.pop(0)
    print(val)
    return val

if __name__ == "__main__":
    with patch("builtins.input", mock_input):
        main()
