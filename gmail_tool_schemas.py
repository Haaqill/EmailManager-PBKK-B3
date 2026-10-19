"""
Gmail API Tool Schemas for Agentic AI Inbox Manager
Phase 2 - Step 1: Typed Pydantic models, JSON Schema exports, and execution stubs.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr
import json

# =====================================================================
# 1. PYDANTIC TOOL PARAMETER SCHEMAS
# =====================================================================

class ListUnreadEmailsInput(BaseModel):
    """Parameters for retrieving unread emails from the Gmail inbox."""
    max_results: int = Field(
        default=10, 
        ge=1, 
        le=50, 
        description="Maximum number of email threads to retrieve (1-50)."
    )
    query: Optional[str] = Field(
        default="is:unread category:primary", 
        description="Optional Gmail search query filter (e.g. 'is:unread newer_than:2d')."
    )
    include_spam_trash: bool = Field(
        default=False, 
        description="Whether to include messages from SPAM and TRASH folders."
    )


class GetThreadHistoryInput(BaseModel):
    """Parameters for fetching full thread conversation history."""
    thread_id: str = Field(
        ..., 
        description="The unique Gmail thread identifier (e.g., '18c5e2a91f4b802a')."
    )
    max_messages: int = Field(
        default=5, 
        ge=1, 
        le=20, 
        description="Maximum number of recent messages in the thread to fetch."
    )


class ApplyLabelInput(BaseModel):
    """Parameters for applying a user or system label to an email thread."""
    thread_id: str = Field(
        ..., 
        description="The unique Gmail thread identifier."
    )
    label_name: str = Field(
        ..., 
        description="Name of the label to apply (e.g. 'URGENT', 'FINANCE', 'NEWSLETTER')."
    )


class ArchiveThreadInput(BaseModel):
    """Parameters for archiving an email thread (removes INBOX label)."""
    thread_id: str = Field(
        ..., 
        description="The unique Gmail thread identifier to archive."
    )


class TrashThreadInput(BaseModel):
    """Parameters for moving a spam or junk email thread to Trash."""
    thread_id: str = Field(
        ..., 
        description="The unique Gmail thread identifier to move to trash."
    )


class CreateDraftInput(BaseModel):
    """Parameters for creating a reply draft in Gmail."""
    thread_id: str = Field(
        ..., 
        description="The Gmail thread ID to reply to."
    )
    to_email: str = Field(
        ..., 
        description="Recipient email address."
    )
    subject: str = Field(
        ..., 
        description="Subject line for the reply message."
    )
    body: str = Field(
        ..., 
        description="The body text of the reply email draft."
    )


class SendEmailInput(BaseModel):
    """Parameters for directly sending an email response via Gmail API."""
    thread_id: str = Field(
        ..., 
        description="The Gmail thread ID to attach the message to."
    )
    to_email: str = Field(
        ..., 
        description="Recipient email address."
    )
    subject: str = Field(
        ..., 
        description="Subject line for the outgoing email."
    )
    body: str = Field(
        ..., 
        description="Body text of the message."
    )
    draft_id: Optional[str] = Field(
        default=None, 
        description="Optional draft ID if converting a previously reviewed draft into a sent email."
    )


# =====================================================================
# 2. TOOL REGISTRY & FUNCTION CALLING SCHEMA GENERATOR
# =====================================================================

GMAIL_TOOLS = [
    {
        "name": "list_unread_emails",
        "description": "Fetches a list of unread email threads from the user's primary inbox.",
        "parameters": ListUnreadEmailsInput.model_json_schema()
    },
    {
        "name": "get_thread_history",
        "description": "Retrieves the full message history and body text for a specific email thread ID.",
        "parameters": GetThreadHistoryInput.model_json_schema()
    },
    {
        "name": "apply_label",
        "description": "Applies a descriptive tag/label to an email thread for organization.",
        "parameters": ApplyLabelInput.model_json_schema()
    },
    {
        "name": "archive_thread",
        "description": "Archives an email thread by removing it from the INBOX view without deleting.",
        "parameters": ArchiveThreadInput.model_json_schema()
    },
    {
        "name": "trash_thread",
        "description": "Moves an email thread to TRASH (for junk or spam messages).",
        "parameters": TrashThreadInput.model_json_schema()
    },
    {
        "name": "create_draft",
        "description": "Creates an un-sent email draft in Gmail for user review.",
        "parameters": CreateDraftInput.model_json_schema()
    },
    {
        "name": "send_email",
        "description": "Sends an email message directly to the recipient via Gmail REST API.",
        "parameters": SendEmailInput.model_json_schema()
    }
]


def get_openai_function_tools() -> List[Dict[str, Any]]:
    """Exports tools formatted for OpenAI / LangChain Function Calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"]
            }
        }
        for tool in GMAIL_TOOLS
    ]


# =====================================================================
# 3. MOCK EXECUTION STUBS (FOR AGENT TESTING & PROTOTYPING)
# =====================================================================

class MockGmailAPIClient:
    """Mock implementation of the Gmail API for testing the ReAct agent loop locally."""

    @staticmethod
    def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches tool calls to mock API handlers and returns structured observation results."""
        if tool_name == "list_unread_emails":
            params = ListUnreadEmailsInput(**arguments)
            return {
                "status": "success",
                "count": 2,
                "threads": [
                    {
                        "thread_id": "thread_101",
                        "sender": "boss@company.com",
                        "subject": "Q4 Strategy Review Sync",
                        "snippet": "Can you prepare the slides for tomorrow's meeting?",
                        "date": "2026-10-08T09:15:00Z"
                    },
                    {
                        "thread_id": "thread_102",
                        "sender": "newsletter@techdigest.io",
                        "subject": "Weekly AI Digest #245",
                        "snippet": "Top 10 trends in agentic AI architecture for 2026...",
                        "date": "2026-10-08T07:30:00Z"
                    }
                ]
            }

        elif tool_name == "get_thread_history":
            params = GetThreadHistoryInput(**arguments)
            return {
                "status": "success",
                "thread_id": params.thread_id,
                "messages": [
                    {
                        "id": "msg_001",
                        "sender": "boss@company.com",
                        "body": "Hi, please send over the Q4 strategy deck before 3 PM today.",
                        "timestamp": "2026-10-08T09:15:00Z"
                    }
                ]
            }

        elif tool_name == "apply_label":
            params = ApplyLabelInput(**arguments)
            return {
                "status": "success",
                "thread_id": params.thread_id,
                "applied_label": params.label_name
            }

        elif tool_name == "archive_thread":
            params = ArchiveThreadInput(**arguments)
            return {
                "status": "success",
                "thread_id": params.thread_id,
                "action": "archived",
                "removed_labels": ["INBOX"]
            }

        elif tool_name == "trash_thread":
            params = TrashThreadInput(**arguments)
            return {
                "status": "success",
                "thread_id": params.thread_id,
                "action": "trashed"
            }

        elif tool_name == "create_draft":
            params = CreateDraftInput(**arguments)
            return {
                "status": "success",
                "draft_id": "draft_999",
                "thread_id": params.thread_id,
                "to": params.to_email,
                "subject": params.subject,
                "body_preview": params.body[:50] + "..."
            }

        elif tool_name == "send_email":
            params = SendEmailInput(**arguments)
            return {
                "status": "success",
                "message_id": "msg_sent_777",
                "thread_id": params.thread_id,
                "recipient": params.to_email,
                "delivery_timestamp": "2026-10-08T22:45:00Z"
            }

        else:
            raise ValueError(f"Unknown tool: {tool_name}")


if __name__ == "__main__":
    print("=== Gmail Tool Schemas Successfully Loaded ===")
    print(f"Total Tools Registered: {len(GMAIL_TOOLS)}")
    print("\nSample OpenAI Tool Schema (list_unread_emails):")
    sample_tools = get_openai_function_tools()
    print(json.dumps(sample_tools[0], indent=2))
    
    print("\nExecuting Test Call to Mock Client:")
    res = MockGmailAPIClient.execute_tool("list_unread_emails", {"max_results": 5})
    print(json.dumps(res, indent=2))
