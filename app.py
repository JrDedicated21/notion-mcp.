import os, json
from typing import Dict

from fastapi import FastAPI, HTTPException, Request
import httpx

app = FastAPI()

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"


def _headers():
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise HTTPException(status_code=500, detail="NOTION_TOKEN not set")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


@app.get("/sse/")
async def sse_root():
    return "MCP SSE endpoint up"


@app.post("/tools/search")
async def tool_search(body: dict):
    query = body.get("query", "")
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{NOTION_BASE}/search", headers=_headers(), json={"query": query})
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    res_json = r.json()
    results = []
    for item in res_json.get("results", []):
        pid = item.get("id")
        # extract title
        title = None
        props = item.get("properties", {})
        for k, v in props.items():
            if "title" in v and v["title"]:
                title = v["title"][0].get("plain_text")
                break
        title = title or item.get("url", "Untitled")
        url = item.get("url")
        results.append({"id": pid, "title": title, "url": url})
    return {"content": [{"type": "text", "text": json.dumps({"results": results})}]}


@app.post("/tools/fetch")
async def tool_fetch(body: dict):
    pid = body.get("id")
    if not pid:
        raise HTTPException(status_code=400, detail="id is required")
    blocks = []
    start_cursor = None
    async with httpx.AsyncClient() as c:
        while True:
            params = {"page_size": 50}
            if start_cursor:
                params["start_cursor"] = start_cursor
            r = await c.get(f"{NOTION_BASE}/blocks/{pid}/children", headers=_headers(), params=params)
            if r.status_code >= 400:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            data = r.json()
            blocks.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
    lines = []
    for b in blocks:
        t = b.get("type")
        if t and b.get(t, {}).get("rich_text"):
            txt = "".join([rt.get("plain_text", "") for rt in b[t]["rich_text"]])
            if txt.strip():
                lines.append(txt.strip())
    text = "\n".join(lines) or "(No text content)"
    doc = {
        "id": pid,
        "title": "Notion Page",
        "text": text,
        "url": f"https://www.notion.so/{pid.replace('-', '')}",
        "metadata": {"source": "notion"},
    }
    return {"content": [{"type": "text", "text": json.dumps(doc)}]}


# helper to coerce property types
def _coerce_properties(props: Dict) -> Dict:
    out = {}
    for key, val in props.items():
        if "title" in val:
            out[key] = {
                "title": [
                    {
                        "type": "text",
                        "text": {"content": str(val["title"])}
                    }
                ]
            }
        elif "rich_text" in val:
            out[key] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": str(val["rich_text"])}
                    }
                ]
            }
        elif "number" in val:
            out[key] = {"number": float(val["number"]) if val["number"] is not None else None}
        elif "checkbox" in val:
            out[key] = {"checkbox": bool(val["checkbox"])}
        elif "date" in val:
            out[key] = {"date": {"start": val["date"]}}
        elif "select" in val:
            out[key] = {"select": {"name": str(val["select"])}}
        elif "multi_select" in val:
            out[key] = {"multi_select": [{"name": str(x)} for x in (val["multi_select"] or [])]}
        elif "url" in val:
            out[key] = {"url": str(val["url"])}
        else:
            out[key] = {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": str(val)}
                    }
                ]
            }
    return out


@app.post("/tools/create_page")
async def create_page(req: Request):
    body = await req.json()
    dbid = body.get("database_id")
    props_in = body.get("properties", {})
    if not dbid:
        raise HTTPException(status_code=400, detail="database_id is required")
    props = _coerce_properties(props_in)
    payload = {"parent": {"database_id": dbid}, "properties": props}
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{NOTION_BASE}/pages", headers=_headers(), json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    data = r.json()
    page_id = data.get("id")
    url = data.get("url")
    title = None
    for k, v in (data.get("properties") or {}).items():
        if "title" in v and v["title"]:
            title = v["title"][0].get("plain_text")
            break
    result = {"id": page_id, "title": title or "Untitled", "url": url}
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


@app.post("/tools/update_page")
async def update_page(req: Request):
    body = await req.json()
    page_id = body.get("page_id")
    props_in = body.get("properties", {})
    if not page_id:
        raise HTTPException(status_code=400, detail="page_id is required")
    props = _coerce_properties(props_in)
    payload = {"properties": props}
    async with httpx.AsyncClient() as client:
        r = await client.patch(f"{NOTION_BASE}/pages/{page_id}", headers=_headers(), json=payload)
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    data = r.json()
    url = data.get("url")
    result = {"id": page_id, "url": url, "updated": True}
    return {"content": [{"type": "text", "text": json.dumps(result)}]}
