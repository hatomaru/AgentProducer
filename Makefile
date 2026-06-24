.PHONY: generate-traces grade

generate-traces:
	python tests/eval/generate_traces.py

grade:
	agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml --output artifacts/eval_results
