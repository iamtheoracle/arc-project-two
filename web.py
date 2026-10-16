#!/usr/bin/env python3
"""Optional Gradio web interface."""
import gradio as gr
from core.agent import ArcAgent

agent = None

def init_agent(model: str):
    global agent
    agent = ArcAgent(model=model)
    return f"Agent ready with model: {model}"

def respond(message, history):
    if agent is None:
        return "Please initialize the agent first (set model and click Initialize)."
    return agent.chat(message)

with gr.Blocks(title="Arc Project Two") as demo:
    gr.Markdown("# Arc Project Two\nLocal AI — No API keys required")
    model_input = gr.Textbox(value="llama3.1:8b", label="Ollama Model")
    init_btn = gr.Button("Initialize Agent")
    status = gr.Textbox(label="Status", interactive=False)
    init_btn.click(init_agent, inputs=model_input, outputs=status)

    chatbot = gr.ChatInterface(respond, title="Chat with Arc")

if __name__ == "__main__":
    demo.launch()
