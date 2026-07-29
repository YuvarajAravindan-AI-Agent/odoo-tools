"""
Localhost-only tool-calling API in front of the Odoo instance, for the voice
agent's LLM to call (create_partner, get_products, create_order, get_order,
get_orders). Never exposed through Caddy — only reachable from other
processes on this host (e.g. the Pipecat orchestrator), same isolation model
as the read-only proxy at /opt/odoo-chat/proxy.
"""
import os

from dotenv import load_dotenv

load_dotenv()  # must run before importing odoo_client, which reads env vars at import time

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query  # noqa: E402

import odoo_client as odoo  # noqa: E402

TOKEN = os.getenv("ODOO_TOOLS_TOKEN")

app = FastAPI(title="Odoo Voice-Agent Tools", version="0.1.0")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not TOKEN:
        raise HTTPException(status_code=500, detail="Tools token not configured on server")
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/health")
def health():
    ok, detail = odoo.ping()
    return {"status": "ok", "odoo_reachable": ok, "detail": detail}


@app.get("/products", dependencies=[Depends(require_token)])
def products(query: str | None = Query(default=None)):
    return {"products": odoo.get_products(query=query)}


@app.post("/partners", dependencies=[Depends(require_token)])
def create_partner(name: str = Body(...), phone: str | None = Body(default=None), email: str | None = Body(default=None)):
    return odoo.create_partner(name=name, phone=phone, email=email)


@app.post("/orders", dependencies=[Depends(require_token)])
def create_order(partner_id: int = Body(...), lines: list[dict] = Body(...)):
    return odoo.create_order(partner_id=partner_id, lines=lines)


@app.get("/orders/{order_id}", dependencies=[Depends(require_token)])
def get_order(order_id: int):
    order = odoo.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.get("/orders", dependencies=[Depends(require_token)])
def get_orders(partner_id: int = Query(...)):
    return {"orders": odoo.get_orders(partner_id=partner_id)}
