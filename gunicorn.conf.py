def post_fork(server, worker):
    from app.models import db
    db.engine.dispose()
