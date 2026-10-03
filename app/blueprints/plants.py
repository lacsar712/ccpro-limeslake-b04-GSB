"""厂区级配置：峰值温度上限条。"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.extensions import db
from app.models import Plant
from app.services.peak_limits import active_peak_limit

bp = Blueprint("plants", __name__, url_prefix="/plants")


@bp.route("/peak-limit", methods=["GET", "POST"])
@login_required
def peak_limit_settings():
    plants = Plant.query.order_by(Plant.name).all()
    if request.method == "POST":
        plant_id = int(request.form["plant_id"])
        plant = db.session.get(Plant, plant_id)
        if plant is None:
            flash("厂区不存在", "error")
            return redirect(url_for("plants.peak_limit_settings"))

        enabled = request.form.get("peak_temp_limit_enabled") == "on"
        limit_raw = (request.form.get("peak_temp_limit_c") or "").strip()

        if enabled:
            try:
                limit = float(limit_raw)
            except ValueError:
                flash("启用上限时必须填写有效的最高峰值摄氏度", "error")
                return redirect(url_for("plants.peak_limit_settings"))
            if limit <= 0:
                flash("最高峰值摄氏度必须大于 0", "error")
                return redirect(url_for("plants.peak_limit_settings"))
            plant.peak_temp_limit_enabled = True
            plant.peak_temp_limit_c = limit
            flash(
                f"{plant.name} 峰值上限条已启用：写入峰值不得超过 {limit:g}℃",
                "ok",
            )
        else:
            plant.peak_temp_limit_enabled = False
            # 停用后保留上次填写的数值，重新启用时仍可见
            if limit_raw:
                try:
                    plant.peak_temp_limit_c = float(limit_raw)
                except ValueError:
                    pass
            flash(f"{plant.name} 峰值上限条已停用，峰值写入不再拦截", "ok")

        db.session.commit()
        return redirect(url_for("plants.peak_limit_settings"))

    rows = [
        {
            "plant": plant,
            "active_limit": active_peak_limit(plant),
        }
        for plant in plants
    ]
    return render_template("plants/peak_limit.html", rows=rows)
