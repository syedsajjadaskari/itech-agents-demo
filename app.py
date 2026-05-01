import os
import json
from dotenv import load_dotenv
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FileSearchTool, FunctionTool, ToolSet, FilePurpose
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager

load_dotenv()

# ── Azure client ──────────────────────────────────────────────────────────────
ai = AgentsClient(
    endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)
MODEL = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")

# ── Ticket function (this is what the agent will call) ────────────────────────
def create_ticket(customer_name: str, issue: str) -> str:
    """Create a support ticket for a customer issue that needs human help."""
    ticket_id = f"TKT-{abs(hash(issue)) % 99999:05d}"
    print(f"\n>>> TICKET CREATED: {ticket_id} | {customer_name}: {issue}\n")
    return json.dumps({"ticket_id": ticket_id, "message": "Team will contact you in 24 hours."})

# ── Agent state (created once at startup) ────────────────────────────────────
agents = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Setting up agents...")

    # Agent 1 — FAQ agent reads from faq.txt
    file = ai.files.upload_and_poll(file_path="data/faq.txt", purpose=FilePurpose.AGENTS)
    vs   = ai.vector_stores.create_and_poll(file_ids=[file.id], name="faq-store")
    tool = FileSearchTool(vector_store_ids=[vs.id])

    faq_agent = ai.create_agent(
    model=MODEL,
    name="faq-agent",
    instructions=(
        "You are a support agent. "
        "ONLY answer using the file search tool results. "
        "If the file search returns no results, say: I need to escalate this. "
        "NEVER use your own knowledge. NEVER guess. "
        "If asked about payments, ONLY state what is in the document."
    ),
    tools=tool.definitions,
    tool_resources=tool.resources,
)

    # Agent 2 — Support agent creates tickets
    toolset = ToolSet()
    toolset.add(FunctionTool(functions={create_ticket}))
    ai.enable_auto_function_calls(toolset)

    support_agent = ai.create_agent(
        model=MODEL,
        name="support-agent",
        instructions="You handle customer complaints and issues. Always call create_ticket to log the issue. Be kind and empathetic.",
        toolset=toolset,
    )

    agents["faq"]     = faq_agent.id
    agents["support"] = support_agent.id
    agents["vs"]      = vs.id
    agents["faq_res"] = tool.resources

    print(f"FAQ agent ready:     {faq_agent.id}")
    print(f"Support agent ready: {support_agent.id}")
    print("Visit http://localhost:8000")
    yield

    # Cleanup
    ai.delete_agent(agents["faq"])
    ai.delete_agent(agents["support"])
    ai.vector_stores.delete(agents["vs"])
    print("Agents deleted. Bye!")

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class Message(BaseModel):
    text: str

def ask_agent(agent_id: str, question: str, tool_resources=None) -> str:
    thread = ai.threads.create()
    ai.messages.create(thread_id=thread.id, role="user", content=question)
    ai.runs.create_and_process(thread_id=thread.id, agent_id=agent_id)
    msgs = list(ai.messages.list(thread_id=thread.id))
    return msgs[0].text_messages[-1].text.value

@app.post("/chat")
async def chat(msg: Message):
    reply = ask_agent(agents["faq"], msg.text)   # no tool_resources here anymore
    if "escalate" in reply.lower():
        reply = ask_agent(agents["support"], msg.text)
        return JSONResponse({"reply": reply, "agent": "support"})
    return JSONResponse({"reply": reply, "agent": "faq"})

@app.get("/health")
async def health():
    return {"status": "ok", "agents": list(agents.keys())}

app.mount("/", StaticFiles(directory="frontend", html=True), name="ui")