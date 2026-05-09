"""
Landing page pública — página de vendas para atrair novos clientes SaaS.
"""

from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, Response
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
