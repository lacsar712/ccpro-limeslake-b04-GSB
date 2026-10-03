from math import isfinite

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant
from app.services.rules import peak_cap_for_plant

bp = Blueprint("plants", __name__, url_prefix="/plants")


@bp.route("/peak-caps")
@login_required
def peak_caps():
    plants = Plant.query.order_by(Plant.name).all()
    current_caps = {plant.id: peak_cap_for_plant(plant) for plant in plants}
    return render_template(
        "plants/peak_caps.html",
        plants=plants,
        current_caps=current_caps,
    )


@bp.route("/<int:plant_id>/peak-cap", methods=["POST"])
@login_required
def update_peak_cap(plant_id: int):
    plant = Plant.query.get_or_404(plant_id)
    enabled = request.form.get("peak_cap_enabled") == "on"
    cap_raw = (request.form.get("peak_cap_c") or "").strip()

    if enabled:
        try:
            cap = float(cap_raw)
        except ValueError:
            flash(f"「{plant.name}」已启用峰值上限，须填写有效的摄氏度数值", "error")
            return redirect(url_for("plants.peak_caps"))
        if not isfinite(cap) or cap <= 0:  # NaN/inf 或非正数
            flash(f"「{plant.name}」峰值上限须为大于 0 的摄氏度", "error")
            return redirect(url_for("plants.peak_caps"))
        plant.peak_cap_enabled = True
        plant.peak_cap_c = cap
        flash(f"「{plant.name}」峰值上限已启用：{cap:g}℃", "ok")
    else:
        # 停用后不再拦截；保留上次填写的数值便于重新启用。
        plant.peak_cap_enabled = False
        if cap_raw:
            try:
                plant.peak_cap_c = float(cap_raw)
            except ValueError:
                plant.peak_cap_c = None
        flash(f"「{plant.name}」峰值上限已停用，峰值写入不再拦截", "ok")

    db.session.commit()
    return redirect(url_for("plants.peak_caps"))
