"""
Thin client for the local Odoo instance (127.0.0.1:8069) over XML-RPC, used by
the voice-agent's tool-calling layer.

Design rules (security):
- Every operation the HTTP layer (main.py) can trigger is a fixed function
  defined here, with a fixed model and validated inputs. Callers never supply
  arbitrary domains, fields, or method names — same rule as the read-only
  proxy at /opt/odoo-chat/proxy, just extended to permit `create` for the
  five specific operations below.
- create_order() creates a draft quotation only. It deliberately does not
  call action_confirm — confirming a sale (reserving stock, posting to
  accounting) is a business decision that should stay a separate, explicit
  step rather than something a voice call does implicitly on every call.
"""
import os
import xmlrpc.client

ODOO_URL = os.getenv("ODOO_URL", "http://127.0.0.1:8069")
ODOO_DB = os.getenv("ODOO_DB", "odoo")
ODOO_USER = os.getenv("ODOO_USER", "admin")
ODOO_PASSWORD = os.getenv("ODOO_PASSWORD", "admin")

_common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
_models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")

_uid_cache: int | None = None


def _uid() -> int:
    global _uid_cache
    if _uid_cache is None:
        _uid_cache = _common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
        if not _uid_cache:
            raise RuntimeError("Odoo authentication failed")
    return _uid_cache


def _execute(model: str, method: str, args: list, kwargs: dict | None = None):
    return _models.execute_kw(ODOO_DB, _uid(), ODOO_PASSWORD, model, method, args, kwargs or {})


def _search_read(model: str, domain: list, fields: list[str], limit: int = 50, order: str = "") -> list[dict]:
    kwargs = {"fields": fields, "limit": limit}
    if order:
        kwargs["order"] = order
    return _execute(model, "search_read", [domain], kwargs)


def ping() -> tuple[bool, str]:
    try:
        _uid()
        return True, "odoo reachable"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------------------------------------------------------------------------
# Public, whitelisted operations for the voice agent's tool-calling
# ---------------------------------------------------------------------------
def get_products(query: str | None = None, limit: int = 20) -> list[dict]:
    domain = [["sale_ok", "=", True]]
    if query:
        domain.append(["name", "ilike", query])
    return _search_read(
        "product.product",
        domain,
        # Note: qty_available is deliberately excluded — it's added by the
        # `stock` (Inventory) module, which isn't installed on this instance.
        ["name", "list_price", "default_code"],
        limit=limit,
    )


def create_partner(name: str, phone: str | None = None, email: str | None = None) -> dict:
    vals: dict = {"name": name}
    if phone:
        vals["phone"] = phone
    if email:
        vals["email"] = email
    partner_id = _execute("res.partner", "create", [vals])
    return {"id": partner_id, "name": name}


def create_order(partner_id: int, lines: list[dict]) -> dict:
    """lines: [{"product_id": int, "quantity": float}, ...]"""
    order_lines = [
        (0, 0, {"product_id": line["product_id"], "product_uom_qty": line["quantity"]})
        for line in lines
    ]
    order_id = _execute("sale.order", "create", [{"partner_id": partner_id, "order_line": order_lines}])
    order = _search_read(
        "sale.order",
        [["id", "=", order_id]],
        ["name", "partner_id", "amount_total", "state", "date_order"],
        limit=1,
    )
    return order[0] if order else {"id": order_id}


def get_order(order_id: int) -> dict | None:
    orders = _search_read(
        "sale.order",
        [["id", "=", order_id]],
        ["name", "partner_id", "amount_total", "state", "date_order"],
        limit=1,
    )
    if not orders:
        return None
    order = orders[0]
    order["lines"] = _search_read(
        "sale.order.line",
        [["order_id", "=", order_id]],
        ["product_id", "product_uom_qty", "price_unit", "price_subtotal"],
        limit=200,
    )
    return order


def get_orders(partner_id: int, limit: int = 20) -> list[dict]:
    return _search_read(
        "sale.order",
        [["partner_id", "=", partner_id]],
        ["name", "partner_id", "amount_total", "state", "date_order"],
        limit=limit,
        order="date_order desc",
    )
