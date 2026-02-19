import os
import json
import asyncio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_VERSION = "2022-06-28"
NOTION_API_URL = "https://api.notion.com/v1"

# ---- MCP tool definitions ----
tool_defs = [
    {
        "name": "search",
        "description": "Search documents in the Notion databases",
        "parameters": {"query": {"type": "string"}}
    },
    {
        "name": "fetch",
        "description": "Fetch a single document by its id",
        "parameters": {"id": {"type": "string"}}
    },
    {
        "name": "create_page",
        "description": "Create a new page in a Notion database",
        "parameters": {
            "database_id": {"type": "string"},
            "properties": {"type": "object"}
        }
    },
    {
        "name": "update_page",
        "description": "Update properties of an existing Notion page",
        "parameters": {
            "page_id": {"type": "string"},
            "properties": {"type": "object"}
        }
    }
]

@app.get("/")
def root():
    return {"status": "ok"}

# ---- SSE endpoint ----
@app.get("/sse")
async def sse():
    async def event_generator():
        yield f"data: {json.dumps({'tools': tool_defs})}\n\n"
        while True:
            yield ": ping\n\n"
            await asyncio.sleep(20)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked"
        }
    )

# ---- MCP tool endpoints ----
@app.post("/tools/search")
async def search(req: Request):
    body = await req.json()
    query = body.get("query")
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API_URL}/search",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"
            },
            json={"query": query}
        )
    data = r.json()
    results = []
    for result in data.get("results", []):
        page_id = result.get("id")
        title = "Untitled"
        props = result.get("properties", {})
        if "Name" in props and props["Name"].get("title"):
            title = props["Name"]["title"][0]["plain_text"]
        url = result.get("url", "")
        results.append({"id": page_id, "title": title, "url": url})
    return {
        "content": [
            {"type": "text", "text": json.dumps({"results": results})}
        ]
    }

@app.post("/tools/fetch")
async def fetch(req: Request):
    body = await req.json()
    page_id = body.get("id")
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API_URL}/blocks/{page_id}/children",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION
            }
        )
    data = r.json()
    text = []
    for block in data.get("results", []):
        if "paragraph" in block:
            for rt in block["paragraph"].get("rich_text", []):
                text.append(rt.get("plain_text", ""))
    return {
        "content": [
            {"type": "text", "text": json.dumps({
                "id": page_id,
                "title": "Notion Page",
                "text": "\n".join(text),
                "url": f"https://www.notion.so/{page_id.replace('-', '')}",
                "metadata": {"source": "notion"}
            })}
        ]
    }

@app.post("/tools/create_page")
async def create_page(req: Request):
    body = await req.json()
    db_id = body.get("database_id")
    props = body.get("properties", {})
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API_URL}/pages",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"
            },
            json={"parent": {"database_id": db_id}, "properties": props}
        )
    data = r.json()
    return {
        "content": [
            {"type": "text", "text": json.dumps(data)}
        ]
    }

@app.post("/tools/update_page")
async def update_page(req: Request):
    body = await req.json()
    page_id = body.get("page_id")
    props = body.get("properties", {})
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API_URL}/pages/{page_id}",
            headers={
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json"
            },
            json={"properties": props}
        )
    data = r.json()
    return {
        "content": [
            {"type": "text", "text": json.dumps(data)}
        ]
    }
