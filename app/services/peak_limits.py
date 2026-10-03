"""厂区峰值温度上限条：统一校验、写入收口与并发控制。

所有峰值温度写入（平面图抽屉 / 批次表单）都必须经此模块，
避免某条路径绕过上限直接落库。出灰的 60℃ 门槛在 rules.py，
与本上限互不替代。
"""

from __future__ import annotations

from sqlalchemy import update

from app.extensions import db
from app.models import Plant, SlakeBatch


class PeakLimitError(ValueError):
    """峰值写入违反厂区上限，或与他人的并发修改冲突。"""


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def active_peak_limit(plant: Plant) -> float | None:
    """厂区现行上限；停用或未配置时返回 None（不拦截）。"""
    if plant.peak_temp_limit_enabled and plant.peak_temp_limit_c is not None:
        return float(plant.peak_temp_limit_c)
    return None


def assert_peak_within_limit(peak: float | None, plant: Plant) -> None:
    """启用上限时，峰值高于上限即中文拒绝；等于上限允许。"""
    if peak is None:
        return
    limit = active_peak_limit(plant)
    if limit is not None and peak > limit:
        raise PeakLimitError(
            f"峰值温度 {_fmt(peak)}℃ 超过{plant.name}现行上限 {_fmt(limit)}℃，"
            "已拒绝保存，请降低峰值或在「峰值上限」页调整上限。"
        )


def lock_plant_for_peak_write(plant_id: int) -> Plant:
    """
    锁定厂区行后返回厂区：
    - 串行化同厂的峰值写入，保证复查到的是「现行」上限（含刚切换的启停）；
    - 两人同时改同一熟化班时，配合批次版本号只放一版生效。
    """
    return (
        db.session.query(Plant)
        .filter(Plant.id == plant_id)
        .with_for_update()
        .populate_existing()
        .one()
    )


def update_batch_peak(
    batch: SlakeBatch,
    peak: float | None,
    expected_version: int | None,
) -> None:
    """
    在已持有厂区行锁的事务内条件更新批次峰值。

    以 UPDATE ... WHERE id=? AND version=? 做乐观锁：
    版本号已被他人推进（rowcount=0）即中文拒绝，本次不入库。
    成功后刷新 ORM 对象，供同一事务内的出灰规则读到新峰值。
    """
    current_version = batch.version
    if expected_version is None:
        expected_version = current_version

    stmt = (
        update(SlakeBatch)
        .where(SlakeBatch.id == batch.id, SlakeBatch.version == expected_version)
        .values(peak_temp_c=peak, version=SlakeBatch.version + 1)
    )
    result = db.session.execute(stmt)
    if result.rowcount == 0:
        raise PeakLimitError(
            "该熟化班的峰值刚被他人更新，本次修改未生效；"
            "请刷新页面、基于最新峰值再改。"
        )
    db.session.refresh(batch)
