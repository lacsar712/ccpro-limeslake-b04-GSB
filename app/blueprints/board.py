from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant, Pond
from app.services.rules import (
    RuleError,
    assert_can_set_pond_status,
    atomically_save_batch,
    latest_batch_for_pond,
    peak_cap_for_plant,
)

bp = Blueprint("board", __name__, url_prefix="/board")

STATUS_LABELS = {
    Pond.STATUS_FILLING: "注水中",
    Pond.STATUS_SLAKING: "熟化中",
    Pond.STATUS_DRAWN: "已出灰",
}


@bp.route("/")
@login_required
def floor_plan():
    plants = Plant.query.order_by(Plant.name).all()
    plant_id_raw = request.args.get("plant_id", "").strip()
    active_plant = None
    if plant_id_raw.isdigit():
        active_plant = db.session.get(Plant, int(plant_id_raw))
    if active_plant is None and plants:
        active_plant = plants[0]

    ponds = []
    if active_plant:
        ponds = (
            Pond.query.filter_by(plant_id=active_plant.id)
            .order_by(Pond.code)
            .all()
        )

    pond_cards = []
    for pond in ponds:
        batch = latest_batch_for_pond(pond)
        pond_cards.append({"pond": pond, "batch": batch})

    selected_id = request.args.get("pond", type=int)
    selected = None
    selected_batch = None
    if selected_id:
        selected = next((c["pond"] for c in pond_cards if c["pond"].id == selected_id), None)
        if selected:
            selected_batch = latest_batch_for_pond(selected)

    return render_template(
        "board/floor.html",
        plants=plants,
        active_plant=active_plant,
        pond_cards=pond_cards,
        selected=selected,
        selected_batch=selected_batch,
        status_labels=STATUS_LABELS,
        peak_cap_c=peak_cap_for_plant(active_plant),
    )


@bp.route("/ponds/<int:pond_id>/ops", methods=["POST"])
@login_required
def pond_ops(pond_id: int):
    pond = Pond.query.get_or_404(pond_id)
    status = request.form.get("status") or pond.status
    peak_raw = (request.form.get("peak_temp_c") or "").strip()
    notes = (request.form.get("batch_notes") or "").strip()
    version_raw = (request.form.get("version") or "").strip()

    batch = latest_batch_for_pond(pond)
    if batch is None:
        flash("该池尚无熟化批次，无法登记峰值或出灰", "error")
        return redirect(
            url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
        )

    try:
        expected_version = int(version_raw) if version_raw else None
    except ValueError:
        expected_version = None

    # 峰值框留空表示本次不改峰值（只改状态/备注）：保留旧值且不施加上限，
    # 历史遗留的超限旧值不阻塞出灰；填了值才走峰值写入与厂区上限校验。
    peak_submitted = bool(peak_raw)
    if peak_submitted:
        try:
            peak_value = float(peak_raw)
        except ValueError:
            flash("峰值温度格式无效", "error")
            return redirect(
                url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id)
            )
    else:
        peak_value = batch.peak_temp_c

    try:
        atomically_save_batch(
            batch=batch,
            pond_id=pond.id,
            started_at=batch.started_at,
            target_temp_c=batch.target_temp_c,
            peak_temp_c=peak_value,
            notes=notes,
            expected_version=expected_version,
            enforce_peak_cap=peak_submitted,
        )
        assert_can_set_pond_status(pond, status)
        pond.status = status
        db.session.commit()
        flash(f"{pond.code} 已更新", "ok")
    except RuleError as exc:
        db.session.rollback()
        flash(str(exc), "error")

    return redirect(url_for("board.floor_plan", plant_id=pond.plant_id, pond=pond.id))
