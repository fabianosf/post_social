"""
Package do dashboard — define o blueprint e importa todos os sub-módulos de rotas.
"""

from flask import Blueprint

dashboard_bp = Blueprint("dashboard", __name__)

# Importar sub-módulos após criar o blueprint para evitar imports circulares
from . import routes_main       # noqa: E402, F401
from . import routes_instagram  # noqa: E402, F401
from . import routes_posts      # noqa: E402, F401
from . import routes_settings   # noqa: E402, F401
from . import routes_api        # noqa: E402, F401
