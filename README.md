# Agent Producer: A Human-in-the-loop Multi-Agent System for Researching and Improving Creative Project Ideas

*Language: [日本語 (Japanese)](README_ja.md)*

> [!NOTE]
> **Vibe Coding Project**
> This repository is a project built through "Vibe Coding", an interactive development approach utilizing AI (LLMs). It is published as part of a personal development project and serves as a submission for the Kaggle competition "AI Agents: Intensive Vibe Coding Capstone Project".

## Overview
**Agent Producer** is a multi-agent system powered by the Google Agent Development Kit (ADK) 2.0 and Gemini. It assists creators in transforming ideas into project drafts, conducting research, suggesting improvements, and creating presentation materials.

Based on an idea inputted by the user, multiple specialized agents collaborate to refine the project. By incorporating a "Review Gate (Human-in-the-loop)", it seamlessly blends the productivity of AI with human decision-making, rapidly generating high-quality project drafts and pitch scripts that align with the creator's true intentions.

## Problem Statement
In creative work, investigating markets or similar projects, identifying weaknesses, and creating presentation materials require significant effort.
While the use of AI for text generation is increasing, leaving everything to AI often results in outputs that deviate from the creator's original intentions and passion.

Agent Producer acts as a **"creative companion that drastically reduces the time from project planning to presentation while keeping the creator's intentions at the core."**

## Agent Architecture
Currently (Beta version), the following agents and workflows are implemented:

- **Planner Agent**: Organizes abstract ideas and creates a project draft defining the core experience and MVP.
- **Research Agent**: Investigates similar works and market trends to reinforce the project's differentiation points.
- **Critic Agent**: Identifies weaknesses and production risks, providing constructive suggestions for improvement.
- **Review Gate (Human Approval)**: Pauses the workflow once the draft is created to await human review (Approve/Revise/Reject).
- **Producer Agent**: Based on the approved project, generates compelling catchphrases and a 30-second pitch script.

## How to Run (ADK 2.0 PlayGround)

This project is built using the Google Agent Development Kit (ADK) 2.0. Follow the steps below to launch the ADK 2.0 PlayGround and test the agent workflow.

### Prerequisites
- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Setup
Clone the repository and install the dependencies using `uv`.

```bash
uv sync
```

### Launching the ADK 2.0 PlayGround
Start the development server and PlayGround (UI) using the ADK CLI.

```bash
uv run adk web
```

After launching, access the localhost URL (PlayGround UI) displayed in the terminal via your browser.
From the Web UI, you can interact with the agents and visually test the workflow (Idea Input → Draft Generation → Human Approval → Pitch Generation).

### (Reference) CLI-based Testing
If you prefer to test the workflow directly via a program (`InMemoryRunner`) without the UI, run the following script:

```bash
uv run python run_workflow.py
```
Upon execution, the agents will proceed with planning in the terminal, and the process will pause at `=== Review (Approve) ===` waiting for your input. Once the approval process specified in the code is passed, the final pitch script will be generated.

## Roadmap
In the future, we plan to integrate a **Video Agent** that will work with video generation tools (such as Remotion) based on the generated pitch script, providing end-to-end support up to the automatic generation of short pitch videos.
