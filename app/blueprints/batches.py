from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond, SlakeBatch, utcnow
from app.services.peak_limits import (
    PeakLimitError,
    active_peak_limit,
    assert_peak_within_limit,
    lock_plant_for_peak_write,
    update_batch_peak,
)

bp = Blueprint("batches", __name__, url_prefix="/batches")


def _parse_peak():
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    if not peak_raw:
        return None, None
    try:
        return float(peak_raw), None
    except ValueError:
        return None, "峰值温度格式无效"


def _plant_limits(ponds) -> dict[int, float | None]:
    """各池所属厂区的现行峰值上限（停用为 None），按池 id 供表单展示。"""
    plant_ids = {p.plant_id for p in ponds}
    plants = Plant.query.filter(Plant.id.in_(plant_ids)).all() if plant_ids else []
    limits = {plant.id: active_peak_limit(plant) for plant in plants}
    return {p.id: limits.get(p.plant_id) for p in ponds}


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
        peak, parse_error = _parse_peak()
        notes = (request.form.get("notes") or "").strip()
        started_at = (
            datetime.fromisoformat(started_raw)
            if started_raw
            else utcnow()
        )
        if parse_error:
            flash(parse_error, "error")
            return render_template(
                "batches/form.html",
                ponds=ponds,
                batch=None,
                plant_limits=_plant_limits(ponds),
            )
        try:
            plant = lock_plant_for_peak_write(
                db.session.get(Pond, pond_id).plant_id
            )
            assert_peak_within_limit(peak, plant)
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
            pond = db.session.get(Pond, pond_id)
            return redirect(
                url_for(
                    "board.floor_plan",
                    plant_id=pond.plant_id if pond else None,
                    pond=pond_id,
                )
            )
        except PeakLimitError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template(
        "batches/form.html",
        ponds=ponds,
        batch=None,
        plant_limits=_plant_limits(ponds),
    )


@bp.route("/<int:batch_id>/edit", methods=["GET", "POST"])
@login_required
def edit_batch(batch_id: int):
    batch = SlakeBatch.query.get_or_404(batch_id)
    ponds = Pond.query.order_by(Pond.code).all()
    if request.method == "POST":
        pond_id = int(request.form["pond_id"])
        started_raw = request.form.get("started_at") or ""
        target = float(request.form.get("target_temp_c") or 80)
        peak, parse_error = _parse_peak()
        notes = (request.form.get("notes") or "").strip()
        version_raw = (request.form.get("version") or "").strip()
        if parse_error:
            flash(parse_error, "error")
            return render_template(
                "batches/form.html",
                ponds=ponds,
                batch=batch,
                plant_limits=_plant_limits(ponds),
            )
        try:
            expected_version = int(version_raw) if version_raw else None
        except ValueError:
            expected_version = None
        old_peak = batch.peak_temp_c
        try:
            target_pond = db.session.get(Pond, pond_id)
            plant = lock_plant_for_peak_write(target_pond.plant_id)
            assert_peak_within_limit(peak, plant)
            batch.pond_id = pond_id
            if started_raw:
                batch.started_at = datetime.fromisoformat(started_raw)
            batch.target_temp_c = target
            # 仅峰值变化时做条件更新：并发改同一熟化班峰值只放一版
            if peak != old_peak:
                update_batch_peak(batch, peak, expected_version)
            batch.notes = notes
            db.session.commit()
            flash("熟化批次已更新", "ok")
            return redirect(
                url_for(
                    "board.floor_plan",
                    plant_id=batch.pond.plant_id,
                    pond=batch.pond_id,
                )
            )
        except PeakLimitError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template(
        "batches/form.html",
        ponds=ponds,
        batch=batch,
        plant_limits=_plant_limits(ponds),
    )
