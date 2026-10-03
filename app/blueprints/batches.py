from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Pond, SlakeBatch
from app.services.rules import RuleError, assert_peak_within_cap, atomically_save_batch, peak_cap_for_plant

bp = Blueprint("batches", __name__, url_prefix="/batches")


def _pond_caps(ponds) -> dict:
    """模板/JS 用：每个池所属厂区的现行上限（停用为 None）。"""
    return {pond.id: peak_cap_for_plant(pond.plant) for pond in ponds}


def _parse_peak(raw: str) -> float:
    """峰值输入解析；空串表示不记峰值(None)。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    return float(raw)


@bp.route("/")
@login_required
def list_batches():
    batches = (
        SlakeBatch.query.join(Pond)
        .order_by(SlakeBatch.started_at.desc())
        .all()
    )
    return render_template("batches/list.html", batches=batches)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create_batch():
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        started_raw = request.form.get("started_at") or ""
        target = float(request.form.get("target_temp_c") or 80)
        notes = (request.form.get("notes") or "").strip()
        started_at = (
            datetime.fromisoformat(started_raw)
            if started_raw
            else datetime.utcnow()
        )
        try:
            peak = _parse_peak(request.form.get("peak_temp_c") or "")
        except ValueError:
            flash("峰值温度格式无效", "error")
            return render_template("batches/form.html", ponds=ponds, batch=None, pond_caps=_pond_caps(ponds))

        pond = db.session.get(Pond, pond_id)
        try:
            # 新建同样受厂区现行上限约束，不能借道登记页超上限写入。
            assert_peak_within_cap(pond.plant if pond else None, peak)
            batch = SlakeBatch(
                pond_id=pond_id,
                started_at=started_at,
                target_temp_c=target,
                peak_temp_c=peak,
                notes=notes,
            )
            db.session.add(batch)
            db.session.commit()
            flash("熟化批次已登记", "ok")
        except RuleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return render_template("batches/form.html", ponds=ponds, batch=None, pond_caps=_pond_caps(ponds))

        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=pond.plant_id if pond else None,
                pond=pond_id,
            )
        )
    return render_template("batches/form.html", ponds=ponds, batch=None, pond_caps=_pond_caps(ponds))


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@login_required
def edit_batch(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        started_raw = request.form.get("started_at") or ""
        started_at = datetime.fromisoformat(started_raw) if started_raw else batch.started_at
        target = float(request.form.get("target_temp_c") or 80)
        notes = (request.form.get("notes") or "").strip()
        version_raw = (request.form.get("version") or "").strip()
        try:
            expected_version = int(version_raw) if version_raw else None
        except ValueError:
            expected_version = None
        try:
            peak = _parse_peak(request.form.get("peak_temp_c") or "")
        except ValueError:
            flash("峰值温度格式无效", "error")
            return render_template("batches/form.html", ponds=ponds, batch=batch, pond_caps=_pond_caps(ponds))

        try:
            atomically_save_batch(
                batch=batch,
                pond_id=pond_id,
                started_at=started_at,
                target_temp_c=target,
                peak_temp_c=peak,
                notes=notes,
                expected_version=expected_version,
            )
            db.session.commit()
            flash("熟化批次已更新", "ok")
        except RuleError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            # 重查后回显，确保页面版本号/现值是最新的。
            batch = db.session.get(SlakeBatch, batch_id)
            return render_template("batches/form.html", ponds=ponds, batch=batch, pond_caps=_pond_caps(ponds))

        return redirect(
            url_for(
                "board.floor_plan",
                plant_id=batch.pond.plant_id,
                pond=batch.pond_id,
            )
        )
    return render_template("batches/form.html", ponds=ponds, batch=batch, pond_caps=_pond_caps(ponds))
