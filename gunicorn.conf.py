def post_fork(server, worker):
    try:
        from run import app
        with app.app_context():
            from app.models import db
            db.engine.dispose()
    except Exception:
        pass
