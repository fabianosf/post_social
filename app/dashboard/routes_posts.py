"""
Rotas de gerenciamento de posts: upload, edição, aprovação, exclusão, CSV, GDrive.
"""

import csv
import io
import os
import random
import shutil
import uuid
from datetime import datetime, timezone, timedelta

from flask import (
    flash, redirect, request, url_for, session,
    jsonify, current_app,
)
from flask_login import login_required, current_user

from ..models import db, InstagramAccount, PostQueue
from .helpers import (
    SAFE_LIMITS, ALLOWED_VID, BRAZIL_TZ,
    allowed_file, is_video, apply_watermark, next_free_slot,
)
from . import dashboard_bp


@dashboard_bp.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    upload_folder = os.path.realpath(current_app.config["UPLOAD_FOLDER"])
    client_dir = os.path.realpath(os.path.join(upload_folder, str(current_user.id)))
    requested = os.path.realpath(os.path.join(upload_folder, filename))
    if not requested.startswith(client_dir + os.sep) and requested != client_dir:
        return "Acesso negado", 403
    from flask import send_from_directory
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)


@dashboard_bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "GET":
        return redirect(url_for("dashboard.index"))
    accounts = InstagramAccount.query.filter_by(client_id=current_user.id).all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    if not current_user.can_post():
        flash(f"Limite mensal atingido ({current_user.get_monthly_limit()} posts). Faça upgrade para o plano Pro!", "error")
        return redirect(url_for("dashboard.index"))

    files = request.files.getlist("photos")
    caption = request.form.get("caption", "").strip()
    hashtags = request.form.get("hashtags", "").strip()
    post_fb = request.form.get("share_facebook") == "on"
    post_story = request.form.get("post_story") == "on"
    post_tiktok = request.form.get("post_to_tiktok") == "on"

    if post_story and not current_user.is_pro():
        flash("Stories é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    account_id = request.form.get("account_id", type=int)
    scheduled_str = request.form.get("scheduled_at", "").strip()
    needs_approval = request.form.get("needs_approval") == "on"

    if not account_id:
        account_id = session.get("active_account_id") or current_user.default_account_id
    if account_id:
        target_account = InstagramAccount.query.filter_by(
            id=account_id, client_id=current_user.id
        ).first()
    else:
        target_account = accounts[0]

    if not target_account:
        flash("Conta Instagram não encontrada.", "error")
        return redirect(url_for("dashboard.index"))

    scheduled_at = None
    if scheduled_str:
        try:
            local_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M")
            scheduled_at = local_dt.replace(tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            flash("Data/hora inválida.", "error")
            return redirect(url_for("dashboard.index"))

    if scheduled_at:
        ref_brt = scheduled_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
    else:
        ref_brt = datetime.now(BRAZIL_TZ)
    day_start_brt = ref_brt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_brt   = day_start_brt + timedelta(days=1)
    day_start = day_start_brt.astimezone(timezone.utc).replace(tzinfo=None)
    day_end   = day_end_brt.astimezone(timezone.utc).replace(tzinfo=None)

    _feed_base = PostQueue.query.filter(
        PostQueue.account_id == target_account.id,
        PostQueue.post_type != "story",
        PostQueue.status.in_(["posted", "pending", "processing"]),
        db.or_(
            db.and_(PostQueue.posted_at >= day_start, PostQueue.posted_at < day_end),
            db.and_(PostQueue.scheduled_at >= day_start, PostQueue.scheduled_at < day_end),
        ),
    )
    ig_today = _feed_base.filter(PostQueue.post_to_instagram == True).count()
    fb_today = _feed_base.filter(PostQueue.post_to_facebook == True).count()

    stories_today = PostQueue.query.filter(
        PostQueue.account_id == target_account.id,
        PostQueue.post_type == "story",
        PostQueue.status.in_(["posted", "pending", "processing"]),
        db.or_(
            db.and_(PostQueue.posted_at >= day_start, PostQueue.posted_at < day_end),
            db.and_(PostQueue.scheduled_at >= day_start, PostQueue.scheduled_at < day_end),
        ),
    ).count()

    MAX_DAY = SAFE_LIMITS["max_posts_per_day"]
    day_label = ref_brt.strftime("%d/%m")

    if not post_story and (ig_today >= MAX_DAY or (post_fb and fb_today >= MAX_DAY)):
        search_after = day_start
        new_slot = next_free_slot(target_account.id, search_after)
        new_slot_brt = new_slot.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ)
        flash(
            f"Dia {day_label} já tem {MAX_DAY}/{MAX_DAY} posts. "
            f"Agendamento movido automaticamente para {new_slot_brt.strftime('%d/%m às %H:%M')}.",
            "info",
        )
        scheduled_at = new_slot
        ref_brt = new_slot_brt

    if post_story and stories_today >= SAFE_LIMITS["max_stories_per_day"]:
        flash(
            f"Limite de stories atingido para @{target_account.ig_username} "
            f"({SAFE_LIMITS['max_stories_per_day']} stories/dia). "
            f"Tente novamente amanhã.",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    if not files or all(f.filename == "" for f in files):
        flash("Selecione pelo menos uma foto.", "error")
        return redirect(url_for("dashboard.index"))

    client_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id))
    os.makedirs(client_dir, exist_ok=True)

    valid_files = [f for f in files if f.filename and allowed_file(f.filename)]
    if not valid_files:
        flash("Nenhum arquivo válido selecionado.", "error")
        return redirect(url_for("dashboard.index"))

    is_album = len(valid_files) > 1 and all(not is_video(f.filename) for f in valid_files)

    if is_album:
        paths = []
        names = []
        for file in valid_files:
            ext = file.filename.rsplit(".", 1)[1].lower()
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            file.save(file_path)
            if current_user.watermark_enabled and current_user.watermark_path:
                apply_watermark(file_path, current_user.watermark_path,
                                current_user.watermark_position, current_user.watermark_opacity)
            paths.append(file_path)
            names.append(file.filename)

        post = PostQueue(
            client_id=current_user.id,
            account_id=target_account.id,
            post_type="album",
            image_path="|".join(paths),
            image_filename=", ".join(names),
            caption=caption if caption else None,
            hashtags=hashtags,
            scheduled_at=scheduled_at,
            needs_approval=needs_approval,
            status="draft" if needs_approval else "pending",
            post_to_instagram=True,
            post_to_facebook=post_fb,
            post_to_tiktok=post_tiktok,
        )
        db.session.add(post)
        queued = 1
    else:
        queued = 0
        for file in valid_files:
            ext = file.filename.rsplit(".", 1)[1].lower()
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            file.save(file_path)
            post_type = "reels" if is_video(file.filename) else "photo"
            if post_type == "photo" and current_user.watermark_enabled and current_user.watermark_path:
                apply_watermark(file_path, current_user.watermark_path,
                                current_user.watermark_position, current_user.watermark_opacity)
            post = PostQueue(
                client_id=current_user.id,
                account_id=target_account.id,
                post_type=post_type,
                image_path=file_path,
                image_filename=file.filename,
                caption=caption if caption else None,
                hashtags=hashtags,
                scheduled_at=scheduled_at,
                needs_approval=needs_approval,
                status="draft" if needs_approval else "pending",
                post_to_instagram=True,
                post_to_facebook=post_fb,
            )
            db.session.add(post)
            queued += 1

    if post_story:
        story_posts = PostQueue.query.filter_by(client_id=current_user.id).order_by(PostQueue.id.desc()).limit(queued).all()
        for sp in story_posts:
            story_paths = []
            for path in sp.image_path.split("|"):
                if os.path.exists(path):
                    ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
                    story_name = f"{uuid.uuid4().hex}.{ext}"
                    story_path = os.path.join(client_dir, story_name)
                    shutil.copy2(path, story_path)
                    story_paths.append(story_path)
            if story_paths:
                story = PostQueue(
                    client_id=current_user.id,
                    account_id=target_account.id,
                    post_type="story",
                    image_path=story_paths[0],
                    image_filename=f"[Story] {sp.image_filename}",
                    caption=None,
                    status="pending",
                    post_to_instagram=True,
                    post_to_facebook=post_fb,
                )
                db.session.add(story)
                queued += 1

    db.session.commit()

    if not needs_approval:
        new_posts = (
            PostQueue.query.filter_by(client_id=current_user.id, status="pending")
            .order_by(PostQueue.id.desc())
            .limit(queued)
            .all()
        )
        new_posts.reverse()
        if scheduled_at:
            for p in new_posts:
                p.scheduled_at = scheduled_at
            db.session.commit()
            times_str = scheduled_at.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ).strftime("%d/%m %H:%M")
            flash(f"{len(new_posts)} postagem(ns) agendada(s) para {times_str}.", "success")
        else:
            flash(f"{queued} postagem(ns) na fila! Será publicada em até 5 minutos.", "success")
    else:
        flash(f"{queued} postagem(ns) salvas como rascunho. Aprove a legenda para publicar.", "info")

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/delete", methods=["POST"])
@login_required
def delete_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if post:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        db.session.commit()
        flash("Postagem removida.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/edit", methods=["POST"])
@login_required
def edit_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not post or post.status not in ("pending", "draft", "failed", "posted"):
        flash("Post não encontrado ou não pode ser editado.", "error")
        return redirect(url_for("dashboard.index"))

    new_caption = request.form.get("caption", "").strip() or None
    new_hashtags = request.form.get("hashtags", "").strip() or None
    scheduled_str = request.form.get("scheduled_at", "").strip()
    new_scheduled = None
    if scheduled_str:
        try:
            local_dt = datetime.strptime(scheduled_str, "%Y-%m-%dT%H:%M")
            new_scheduled = local_dt.replace(tzinfo=BRAZIL_TZ).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            pass

    if post.status == "posted":
        if not current_user.can_post():
            flash("Limite mensal atingido.", "error")
            return redirect(url_for("dashboard.index"))

        new_paths = []
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
                new_path = os.path.join(os.path.dirname(path), f"{uuid.uuid4().hex}.{ext}")
                shutil.copy2(path, new_path)
                new_paths.append(new_path)

        if not new_paths:
            flash("Arquivos originais não encontrados. Faça upload novamente.", "error")
            return redirect(url_for("dashboard.index"))

        new_post = PostQueue(
            client_id=current_user.id,
            account_id=post.account_id,
            post_type=post.post_type,
            image_path="|".join(new_paths),
            image_filename=post.image_filename,
            caption=new_caption if new_caption is not None else post.caption,
            hashtags=new_hashtags if new_hashtags is not None else post.hashtags,
            scheduled_at=new_scheduled,
            status="pending",
            post_to_instagram=post.post_to_instagram,
            post_to_facebook=post.post_to_facebook,
        )
        db.session.add(new_post)
        db.session.commit()
        when = new_scheduled.replace(tzinfo=timezone.utc).astimezone(BRAZIL_TZ).strftime("%d/%m às %H:%M") if new_scheduled else "agora (até 5 min)"
        flash(f"Postagem reagendada para {when}!", "success")
    else:
        post.caption = new_caption
        post.hashtags = new_hashtags
        post.scheduled_at = new_scheduled
        if post.status == "failed":
            post.status = "pending"
            post.error_message = None
        db.session.commit()
        flash("Post atualizado!", "success")

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/approve", methods=["POST"])
@login_required
def approve_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id, status="draft").first()
    if post:
        new_caption = request.form.get("caption", "").strip()
        if new_caption:
            post.caption = new_caption
        post.status = "pending"
        post.needs_approval = False
        db.session.commit()
        flash("Postagem aprovada e enviada para a fila!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/retry", methods=["POST"])
@login_required
def retry_post(post_id):
    post = PostQueue.query.filter_by(id=post_id, client_id=current_user.id, status="failed").first()
    if post:
        post.status = "pending"
        post.error_message = None
        db.session.commit()
        flash("Postagem reenviada para a fila.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/post/<int:post_id>/duplicate", methods=["POST"])
@login_required
def duplicate_post(post_id):
    original = PostQueue.query.filter_by(id=post_id, client_id=current_user.id).first()
    if not original:
        flash("Postagem não encontrada.", "error")
        return redirect(url_for("dashboard.index"))

    if not current_user.can_post():
        flash("Limite mensal atingido.", "error")
        return redirect(url_for("dashboard.index"))

    new_paths = []
    for path in original.image_path.split("|"):
        if os.path.exists(path):
            ext = path.rsplit(".", 1)[1] if "." in path else "jpg"
            new_name = f"{uuid.uuid4().hex}.{ext}"
            new_path = os.path.join(os.path.dirname(path), new_name)
            shutil.copy2(path, new_path)
            new_paths.append(new_path)

    if not new_paths:
        flash("Arquivos originais não encontrados.", "error")
        return redirect(url_for("dashboard.index"))

    duplicate = PostQueue(
        client_id=current_user.id,
        account_id=original.account_id,
        post_type=original.post_type,
        image_path="|".join(new_paths),
        image_filename=original.image_filename,
        caption=original.caption,
        hashtags=original.hashtags,
        status="pending",
        post_to_instagram=original.post_to_instagram,
        post_to_facebook=original.post_to_facebook,
    )
    db.session.add(duplicate)
    db.session.commit()
    flash("Postagem duplicada e enviada para a fila!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/clear-posted", methods=["POST"])
@login_required
def clear_posted():
    posted = PostQueue.query.filter_by(client_id=current_user.id, status="posted").all()
    count = 0
    for post in posted:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        count += 1
    db.session.commit()
    if count:
        flash(f"{count} postagens publicadas removidas.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/posts/clear-failed", methods=["POST"])
@login_required
def clear_failed():
    failed = PostQueue.query.filter_by(client_id=current_user.id, status="failed").all()
    count = 0
    for post in failed:
        for path in post.image_path.split("|"):
            if os.path.exists(path):
                os.remove(path)
        db.session.delete(post)
        count += 1
    db.session.commit()
    if count:
        flash(f"{count} postagens com erro removidas.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/csv-import", methods=["POST"])
@login_required
def csv_import():
    if not current_user.is_pro():
        flash("Import CSV é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    accounts = InstagramAccount.query.filter_by(client_id=current_user.id, status="active").all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    csv_file = request.files.get("csv_file")
    images = request.files.getlist("csv_images")

    if not csv_file or not csv_file.filename:
        flash("Selecione um arquivo CSV.", "error")
        return redirect(url_for("dashboard.index"))

    account_id = request.form.get("account_id", type=int) or accounts[0].id

    client_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], str(current_user.id))
    os.makedirs(client_dir, exist_ok=True)

    image_map = {}
    for img in images:
        if img.filename and allowed_file(img.filename):
            ext = img.filename.rsplit(".", 1)[1].lower() if "." in img.filename else "jpg"
            safe_name = f"{uuid.uuid4().hex}.{ext}"
            file_path = os.path.join(client_dir, safe_name)
            img.save(file_path)
            image_map[img.filename.lower()] = file_path

    try:
        content = csv_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
    except Exception:
        flash("Erro ao ler CSV. Use UTF-8 com colunas: filename, caption, hashtags, scheduled_at", "error")
        return redirect(url_for("dashboard.index"))

    queued = 0
    for row in reader:
        filename = (row.get("filename") or "").strip()
        if not filename:
            continue
        file_path = image_map.get(filename.lower())
        if not file_path:
            continue
        if not current_user.can_post():
            flash(f"Limite mensal atingido. {queued} postagens importadas.", "error")
            break

        scheduled_at = None
        sched_str = (row.get("scheduled_at") or "").strip()
        if sched_str:
            try:
                scheduled_at = datetime.strptime(sched_str, "%Y-%m-%d %H:%M")
            except ValueError:
                pass

        _is_vid = filename.rsplit(".", 1)[1].lower() in ALLOWED_VID if "." in filename else False
        post = PostQueue(
            client_id=current_user.id,
            account_id=account_id,
            post_type="reels" if _is_vid else "photo",
            image_path=file_path,
            image_filename=filename,
            caption=(row.get("caption") or "").strip() or None,
            hashtags=(row.get("hashtags") or "").strip() or None,
            scheduled_at=scheduled_at,
            status="pending",
            post_to_instagram=True,
            post_to_facebook=True,
        )
        db.session.add(post)
        queued += 1

    db.session.commit()
    flash(f"{queued} postagens importadas do CSV!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/gdrive-import", methods=["POST"])
@login_required
def gdrive_import():
    if not current_user.is_pro():
        flash("Import do Google Drive é um recurso exclusivo do Plano Pro. Faça upgrade para usar!", "error")
        return redirect(url_for("dashboard.index"))

    from modules.gdrive_import import sync_drive

    accounts = InstagramAccount.query.filter_by(client_id=current_user.id, status="active").all()
    if not accounts:
        flash("Conecte seu Instagram primeiro.", "error")
        return redirect(url_for("dashboard.index"))

    folder_id = current_user.gdrive_folder_id or ""
    if not folder_id:
        flash("Configure primeiro a URL da sua pasta do Google Drive nas configurações.", "error")
        return redirect(url_for("dashboard.index"))

    imported, captions_by_day = sync_drive(current_user.id, current_app.config["UPLOAD_FOLDER"], folder_id)

    if not imported:
        flash("Nenhuma nova imagem encontrada no Google Drive.", "info")
        return redirect(url_for("dashboard.index"))

    account_id = accounts[0].id
    now = datetime.now(timezone.utc)
    today_weekday = now.weekday()
    days_until_monday = (7 - today_weekday) % 7
    if days_until_monday == 0:
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        week_start = (now + timedelta(days=days_until_monday)).replace(hour=0, minute=0, second=0, microsecond=0)

    slot_hours = SAFE_LIMITS.get("suggested_times", [9, 17])

    posts_per_day: dict[int, int] = {i: 0 for i in range(7)}
    existing = PostQueue.query.filter(
        PostQueue.client_id == current_user.id,
        PostQueue.status.in_(["pending", "draft", "processing"]),
        PostQueue.scheduled_at >= week_start,
        PostQueue.scheduled_at < week_start + timedelta(days=7),
    ).all()
    for ep in existing:
        if ep.scheduled_at:
            wd = ep.scheduled_at.weekday()
            posts_per_day[wd] = posts_per_day.get(wd, 0) + 1

    files_without_day = [item for item in imported if item.get("weekday") is None]
    files_with_day = [item for item in imported if item.get("weekday") is not None]

    next_day = 0
    for item in files_without_day:
        while next_day < 7 and posts_per_day.get(next_day, 0) >= len(slot_hours):
            next_day += 1
        if next_day < 7:
            item["weekday"] = next_day
            next_day += 1

    all_items = files_with_day + files_without_day
    created_count = 0
    skipped_count = 0

    for item in all_items:
        weekday = item.get("weekday")
        if weekday is None:
            skipped_count += 1
            continue

        day_count = posts_per_day.get(weekday, 0)
        if day_count >= len(slot_hours):
            skipped_count += 1
            continue

        if not current_user.can_post():
            flash("Limite mensal atingido.", "error")
            break

        day_hours = captions_by_day.get(weekday, {}).get("hours") or slot_hours
        slot_hour = day_hours[day_count % len(day_hours)]
        jitter = random.randint(-SAFE_LIMITS.get("random_delay_minutes", 20),
                                SAFE_LIMITS.get("random_delay_minutes", 20))
        sched_time = (week_start + timedelta(days=weekday)).replace(
            hour=slot_hour, minute=0, second=0, microsecond=0
        ) + timedelta(minutes=jitter)

        day_caption_data = captions_by_day.get(weekday, {})
        caption = day_caption_data.get("caption", "")
        hashtags = day_caption_data.get("hashtags", "")

        post = PostQueue(
            client_id=current_user.id,
            account_id=account_id,
            post_type="photo",
            image_path=item["filepath"],
            image_filename=item["filename"],
            caption=caption,
            hashtags=hashtags,
            scheduled_at=sched_time,
            status="pending",
            needs_approval=False,
            post_to_instagram=True,
            post_to_facebook=True,
        )
        db.session.add(post)
        current_user.increment_post_count()
        posts_per_day[weekday] = day_count + 1
        created_count += 1

    db.session.commit()

    caption_info = f" com legendas do postagens.txt" if captions_by_day else " (sem postagens.txt — sem legendas)"
    msg = f"{created_count} post(s) agendados para a semana{caption_info}."
    if skipped_count:
        msg += f" {skipped_count} ignorado(s) (dia cheio ou sem dia disponível)."
    flash(msg, "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/gdrive/save-folder", methods=["POST"])
@login_required
def save_gdrive_folder():
    folder_url = request.form.get("gdrive_folder_url", "").strip()
    from modules.gdrive_import import extract_folder_id
    folder_id = extract_folder_id(folder_url)

    if folder_url and not folder_id:
        flash("URL ou ID da pasta inválido. Cole o link completo da pasta do Google Drive.", "error")
        return redirect(url_for("dashboard.index"))

    current_user.gdrive_folder_id = folder_id or None
    db.session.commit()

    if folder_id:
        flash("Pasta do Google Drive configurada com sucesso!", "success")
    else:
        flash("Configuração do Google Drive removida.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/gdrive/list-files")
@login_required
def gdrive_list_files():
    if not current_user.is_pro():
        return jsonify({"error": "Recurso Pro"}), 403

    folder_id = current_user.gdrive_folder_id or ""
    if not folder_id:
        return jsonify({"files": [], "error": "Pasta não configurada"})

    from modules.gdrive_import import list_drive_files
    files = list_drive_files(folder_id)
    return jsonify({"files": files})
