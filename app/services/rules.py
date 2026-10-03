"""石灰熟化池业务规则。"""

from __future__ import annotations

from sqlalchemy import Float, func, literal, select, update

from app.extensions import db
from app.models import Plant, Pond, SlakeBatch

MIN_PEAK_TEMP_FOR_DRAWN = 60.0


class RuleError(ValueError):
    """业务规则校验失败。"""


def latest_batch_for_pond(pond: Pond) -> SlakeBatch | None:
    if not pond.batches:
        return None
    return max(pond.batches, key=lambda b: b.started_at)


def can_mark_pond_drawn(pond: Pond) -> tuple[bool, str]:
    """
    熟化池转为「已出灰」(drawn) 的前提：
    最近一条熟化批次的峰值温度已记录，且 >= 60℃。
    （厂区峰值上限只管写入，不替代这条出灰门槛。）
    """
    latest = latest_batch_for_pond(pond)
    if latest is None:
        return False, "该池尚无熟化批次，不能标记为已出灰"
    if latest.peak_temp_c is None:
        return False, "最近批次尚未记录峰值温度，不能标记为已出灰"
    if latest.peak_temp_c < MIN_PEAK_TEMP_FOR_DRAWN:
        return (
            False,
            f"最近批次峰值温度 {latest.peak_temp_c}℃ 低于 {MIN_PEAK_TEMP_FOR_DRAWN:.0f}℃，不能标记为已出灰",
        )
    return True, ""


def assert_can_set_pond_status(pond: Pond, new_status: str) -> None:
    if new_status not in Pond.STATUS_CHOICES:
        raise RuleError(f"无效状态：{new_status}")
    if new_status == Pond.STATUS_DRAWN:
        ok, msg = can_mark_pond_drawn(pond)
        if not ok:
            raise RuleError(msg)


# ---------------------------------------------------------------------------
# 厂区峰值上限
# ---------------------------------------------------------------------------


def peak_cap_for_plant(plant: Plant | None) -> float | None:
    """现行有效上限（℃）；停用或留空时返回 None，表示不拦截。"""
    if plant is None:
        return None
    if not plant.peak_cap_enabled:
        return None
    return plant.peak_cap_c


def assert_peak_within_cap(plant: Plant | None, peak_temp_c: float | None) -> None:
    """峰值超过厂区上限即拒；清空峰值(None)与停用/空上限一律放行。"""
    if peak_temp_c is None:
        return
    cap = peak_cap_for_plant(plant)
    if cap is not None and peak_temp_c > cap:
        raise RuleError(
            f"峰值温度 {peak_temp_c:g}℃ 超过本厂上限 {cap:g}℃，已拒绝保存"
        )


def _cap_guard_clause(pond_id: int, peak_temp_c: float | None):
    """SQL 条件：新峰值满足目标池所属厂区的现行上限（与 UPDATE 同句判定，
    兜住「校验通过后上限才被下调」的并发窗口）。上限停用/留空时恒真。"""
    cap_subq = (
        select(Plant.peak_cap_c)
        .join(Pond, Pond.plant_id == Plant.id)
        .where(Pond.id == pond_id, Plant.peak_cap_enabled.is_(True))
        .scalar_subquery()
    )
    peak_lit = literal(peak_temp_c, type_=Float)
    return peak_lit.is_(None) | (peak_lit <= func.coalesce(cap_subq, peak_lit))


def atomically_save_batch(
    *,
    batch: SlakeBatch,
    pond_id: int,
    started_at,
    target_temp_c: float,
    peak_temp_c: float | None,
    notes: str,
    expected_version: int | None,
    enforce_peak_cap: bool = True,
) -> None:
    """
    以一条 UPDATE 原子写入批次改动：
    - WHERE 带 version 乐观锁：两人几乎同时改同一熟化班，只放一版；
    - 提交了峰值时 WHERE 再带厂区现行上限条件：最终入库值不可能超过现行上限；
    - 行未命中即不入库，按现场情况抛中文 RuleError。

    expected_version 为 None 时跳过版本冲突检查（非表单直连兜底）。
    enforce_peak_cap 为 False（抽屉未填峰值、只改状态/备注）时不施加上限，
    以免历史遗留的超限旧值阻塞出灰——出灰仍只认 60℃ 门槛。
    """
    pond = db.session.get(Pond, pond_id)
    if pond is None:
        raise RuleError("所选熟化池不存在，未保存")

    conditions = [SlakeBatch.id == batch.id]
    if enforce_peak_cap:
        # 常规路径给出明确中文提示；SQL 条件再兜并发窗口。
        assert_peak_within_cap(pond.plant, peak_temp_c)
        conditions.append(_cap_guard_clause(pond_id, peak_temp_c))
    if expected_version is not None:
        conditions.append(SlakeBatch.version == expected_version)

    result = db.session.execute(
        update(SlakeBatch)
        .where(*conditions)
        .values(
            pond_id=pond_id,
            started_at=started_at,
            target_temp_c=target_temp_c,
            peak_temp_c=peak_temp_c,
            notes=notes,
            version=SlakeBatch.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        # Core UPDATE 不会自动回写 ORM 实例；刷新使本请求后续的出灰校验等
        # 读到刚入库的新峰值与新版本。
        db.session.refresh(batch)
        return

    # 未命中：版本被抢，或上限在预检后被下调。重查现场给准确中文原因。
    db.session.rollback()
    fresh = db.session.get(SlakeBatch, batch.id)
    if (
        expected_version is not None
        and fresh is not None
        and fresh.version != expected_version
    ):
        raise RuleError("该熟化班刚被他人更新，仅一版生效；请刷新后按最新值重试")
    fresh_plant = (
        db.session.get(Pond, fresh.pond_id if fresh else pond_id).plant
        if (fresh or pond)
        else None
    )
    cap_now = peak_cap_for_plant(fresh_plant)
    if peak_temp_c is not None and cap_now is not None and peak_temp_c > cap_now:
        raise RuleError(
            f"峰值温度 {peak_temp_c:g}℃ 超过本厂现行上限 {cap_now:g}℃，未保存"
        )
    raise RuleError("保存未生效，请刷新页面后重试")
