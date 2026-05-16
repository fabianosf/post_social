"""
Landing page pública — página de vendas para atrair novos clientes SaaS.
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, render_template, redirect, url_for, Response
from flask_login import current_user

landing_bp = Blueprint("landing", __name__)

BASE_URL = "https://postay.com.br"


@landing_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("landing.html", scroll_to=None)


@landing_bp.route("/recursos")
def features():
    return render_template("landing.html", scroll_to="features")


@landing_bp.route("/planos")
def pricing():
    return render_template("landing.html", scroll_to="pricing")


@landing_bp.route("/faq")
def faq():
    return render_template("landing.html", scroll_to="faq")


@landing_bp.route("/termos")
def terms():
    return render_template("terms.html")


@landing_bp.route("/privacidade")
def privacy():
    return render_template("privacy.html")


@landing_bp.route("/health")
def health():
    """Health check para Docker, load balancer e uptime monitoring."""
    import os
    from pathlib import Path
    from sqlalchemy import text
    from .models import db

    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = None
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), socket_timeout=2)
        redis_ok = r.ping()
    except Exception:
        redis_ok = False

    worker_ok = None
    hb = Path(__file__).resolve().parent.parent / "logs" / "worker_heartbeat.txt"
    try:
        if hb.exists():
            age = datetime.now(timezone.utc).timestamp() - hb.stat().st_mtime
            worker_ok = age < 900
        else:
            worker_ok = False
    except Exception:
        worker_ok = False

    failed_n = pending_n = 0
    if db_ok:
        try:
            from .models import PostQueue
            failed_n = PostQueue.query.filter_by(status="failed").count()
            pending_n = PostQueue.query.filter_by(status="pending").count()
        except Exception:
            pass

    ok = db_ok and redis_ok is not False and worker_ok is not False
    status = 200 if ok else 503
    return jsonify({
        "status": "ok" if ok else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "worker": worker_ok,
        "queue": {"pending": pending_n, "failed": failed_n},
        "ts": datetime.now(timezone.utc).isoformat(),
    }), status


@landing_bp.route("/robots.txt")
def robots():
    content = f"""User-agent: *
Allow: /
Disallow: /dashboard
Disallow: /admin
Disallow: /uploads/
Disallow: /tiktok/
Disallow: /pagamento/webhook

Sitemap: {BASE_URL}/sitemap.xml
"""
    return Response(content, mimetype="text/plain")


@landing_bp.route("/sitemap.xml")
def sitemap():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pages = [
        {"url": "/",         "priority": "1.0", "changefreq": "weekly"},
        {"url": "/recursos", "priority": "0.8", "changefreq": "monthly"},
        {"url": "/planos",   "priority": "0.9", "changefreq": "monthly"},
        {"url": "/faq",      "priority": "0.7", "changefreq": "monthly"},
        {"url": "/cadastro", "priority": "0.8", "changefreq": "monthly"},
        {"url": "/login",    "priority": "0.5", "changefreq": "yearly"},
    ]
    urls = "\n".join(
        f"""  <url>
    <loc>{BASE_URL}{p['url']}</loc>
    <lastmod>{now}</lastmod>
    <changefreq>{p['changefreq']}</changefreq>
    <priority>{p['priority']}</priority>
  </url>"""
        for p in pages
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>"""
    return Response(xml, mimetype="application/xml")
