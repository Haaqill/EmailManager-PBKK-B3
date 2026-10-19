"""
Phase 2 - Step 2: Plain Python ReAct Agent Execution Loop
Building an Agentic AI Gmail Inbox Manager from Scratch
"""

import sys
import os
import json
from typing import List, Dict, Any, Optional

# Import the Pydantic schemas and Mock Gmail Client from Phase 2 Step 1
sys.path.append("/workspace/artifacts")
from gmail_tool_schemas import GMAIL_TOOLS, get_openai_function_tools, MockGmailAPIClient


class SimulatedLLM:
    """
    Simulates an LLM's ReAct (Reasoning + Acting) decision engine for local prototyping.
    Evaluates the conversation history and decides whether to invoke a tool or return a final response.
    """

    def __init__(self):
        self.step_count = 0

    def generate_step(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Evaluates current message history and returns either a tool call request or a final answer.
        """
        # Look at the last message to decide the next action
        last_message = messages[-1] if messages else {}
        content = last_message.get("content", "")
        role = last_message.get("role", "")

        # Initial prompt: Start by listing unread emails
        if role == "user":
            return {
                "thought": "I need to check for unread emails in the primary inbox to categorize and process them.",
                "tool_call": {
                    "name": "list_unread_emails",
                    "arguments": {"max_results": 5, "query": "is:unread category:primary"}
                }
            }

        # After listing unread emails, inspect thread details or process them
        if role == "tool" and last_message.get("name") == "list_unread_emails":
            res = json.loads(content)
            threads = res.get("threads", [])
            
            # Formulate plan based on retrieved threads
            return {
                "thought": f"Found {len(threads)} unread emails. Let's process 'thread_101' from boss@company.com first by inspecting the full thread history, and archive the newsletter 'thread_102'.",
                "tool_call": {
                    "name": "get_thread_history",
                    "arguments": {"thread_id": "thread_101"}
                }
            }

        # After fetching thread history for thread_101 (urgent boss email)
        if role == "tool" and last_message.get("name") == "get_thread_history":
            return {
                "thought": "Thread 101 is an urgent request from boss@company.com asking for the Q4 strategy deck before 3 PM. I should create a draft reply confirming receipt and apply the URGENT label.",
                "tool_call": {
                    "name": "create_draft",
                    "arguments": {
                        "thread_id": "thread_101",
                        "to_email": "boss@company.com",
                        "subject": "Re: Q4 Strategy Review Sync",
                        "body": "Hi, I have received your request and am finalizing the Q4 strategy slides. I will share the presentation deck well before 3 PM today."
                    }
                }
            }

        # After creating the draft for thread_101, apply label
        if role == "tool" and last_message.get("name") == "create_draft":
            return {
                "thought": "Draft created successfully. Now applying the 'URGENT' label to thread_101 to highlight it in the inbox.",
                "tool_call": {
                    "name": "apply_label",
                    "arguments": {
                        "thread_id": "thread_101",
                        "label_name": "URGENT"
                    }
                }
            }

        # After applying label to thread_101, process thread_102 (newsletter)
        if role == "tool" and last_message.get("name") == "apply_label" and "thread_101" in content:
            return {
                "thought": "Thread 101 processed. Now processing thread_102 (newsletter@techdigest.io). This is a marketing newsletter, so I will archive it to keep the inbox clean.",
                "tool_call": {
                    "name": "archive_thread",
                    "arguments": {"thread_id": "thread_102"}
                }
            }

        # Final step: Summarize execution
        if role == "tool" and last_message.get("name") == "archive_thread":
            return {
                "thought": "All pending unread emails have been processed according to priority.",
                "final_response": "Processed 2 unread emails:\n1. thread_101 (boss@company.com): Created draft reply and labeled as URGENT.\n2. thread_102 (newsletter@techdigest.io): Archived successfully."
            }

        return {
            "thought": "No further actions required.",
            "final_response": "Inbox processing completed."
        }


class GmailReActAgent:
    """
    A lightweight, framework-free ReAct Agent that executes the Sense-Think-Act-Observe loop.
    """

    def __init__(self, max_iterations: int = 10):
        self.max_iterations = max_iterations
        self.messages: List[Dict[str, Any]] = []
        self.llm = SimulatedLLM()
        self.execution_trace: List[Dict[str, Any]] = []

    def run(self, user_goal: str) -> str:
        """
        Runs the main ReAct loop until completion or max iterations.
        """
        # Step 1: Initialize context with user goal
        self.messages.append({"role": "user", "content": user_goal})
        print(f"==================================================")
        print(f"🤖 STARTING REACT AGENT LOOP")
        print(f"Goal: {user_goal}")
        print(f"==================================================\n")

        for iteration in range(1, self.max_iterations + 1):
            print(f"--- [ITERATION {iteration}] ---")

            # 1. THINK: LLM evaluates state and decides action
            llm_decision = self.llm.generate_step(self.messages)
            thought = llm_decision.get("thought", "")
            print(f"💭 THOUGHT: {thought}")

            # Check if LLM reached a final answer
            if "final_response" in llm_decision:
                final_answer = llm_decision["final_response"]
                print(f"\n✅ FINAL ANSWER:\n{final_answer}\n")
                self.messages.append({"role": "assistant", "content": final_answer})
                return final_answer

            # 2. ACT: Extract tool call and parameters
            tool_call = llm_decision.get("tool_call", {})
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("arguments", {})

            print(f"🛠️ ACT (Tool Call): `{tool_name}`")
            print(f"   Arguments: {json.dumps(tool_args)}")

            # Append assistant's tool call intent to message history
            self.messages.append({
                "role": "assistant",
                "content": f"Thought: {thought}",
                "tool_calls": [tool_call]
            })

            # 3. OBSERVE: Execute tool against Gmail API / Mock Client
            try:
                observation = MockGmailAPIClient.execute_tool(tool_name, tool_args)
                obs_str = json.dumps(observation)
                print(f"👁️ OBSERVATION: {obs_str}\n")

                # Record observation into message history
                self.messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": obs_str
                })

                # Log trace
                self.execution_trace.append({
                    "iteration": iteration,
                    "thought": thought,
                    "tool_name": tool_name,
                    "arguments": tool_args,
                    "observation": observation
                })

            except Exception as e:
                error_msg = f"Error executing tool {tool_name}: {str(e)}"
                print(f"❌ OBSERVATION ERROR: {error_msg}\n")
                self.messages.append({
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps({"status": "error", "message": error_msg})
                })

        return "Agent reached maximum iteration limit before completing goal."


if __name__ == "__main__":
    agent = GmailReActAgent(max_iterations=8)
    user_prompt = "Check my primary inbox for unread emails, process any urgent requests, and organize newsletters."
    result = agent.run(user_prompt)
    
    print("\n==================================================")
    print(f"SUMMARY OF EXECUTION TRACE ({len(agent.execution_trace)} Tool Calls):")
    print("==================================================")
    for idx, step in enumerate(agent.execution_trace, 1):
        print(f"{idx}. Called `{step['tool_name']}` -> Status: {step['observation'].get('status')}")
