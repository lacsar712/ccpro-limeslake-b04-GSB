import { Application, Controller } from "https://unpkg.com/@hotwired/stimulus@3.2.2/dist/stimulus.js"

const application = Application.start()

class FlashController extends Controller {
  static targets = ["item"]
  connect() {
    window.setTimeout(() => {
      this.itemTargets.forEach((el) => {
        el.style.opacity = "0"
        el.style.transition = "opacity .4s"
      })
    }, 4000)
  }
}

class FormHintController extends Controller {
  static targets = ["status", "hint"]
  connect() {
    this.update()
    this.statusTarget?.addEventListener("change", () => this.update())
  }
  update() {
    if (!this.hasHintTarget || !this.hasStatusTarget) return
    if (this.statusTarget.value === "drawn") {
      this.hintTarget.textContent =
        "当前选择「已出灰」：须存在最近批次，且峰值温度已记录并 ≥ 60℃。"
    } else {
      this.hintTarget.textContent =
        "出灰前请确认最近熟化批次已记录峰值温度且不低于 60℃。"
    }
  }
}

class BoardController extends Controller {
  static targets = ["drawer", "backdrop"]
  static values = { open: Boolean }

  connect() {
    if (this.openValue) this._setOpen(true)
  }

  openDrawer() {
    // Navigation still loads selected pond; keep drawer state consistent on SPA-less click
    this._setOpen(true)
  }

  closeDrawer(event) {
    if (event) event.preventDefault()
    this._setOpen(false)
    const closeLink = event?.currentTarget
    if (closeLink?.href) {
      window.location.href = closeLink.href
    } else if (this.hasBackdropTarget) {
      const base = new URL(window.location.href)
      base.searchParams.delete("pond")
      window.location.href = base.toString()
    }
  }

  _setOpen(open) {
    this.openValue = open
    if (this.hasDrawerTarget) {
      this.drawerTarget.classList.toggle("is-open", open)
      this.drawerTarget.setAttribute("aria-hidden", open ? "false" : "true")
    }
    if (this.hasBackdropTarget) {
      this.backdropTarget.classList.toggle("is-open", open)
    }
  }
}

class PeakLimitController extends Controller {
  static targets = ["pond", "peak", "hint"]
  connect() {
    this.update()
  }
  update() {
    const option = this.pondTarget.selectedOptions?.[0]
    const limit = option?.dataset.limit || ""
    const peak = this.hasPeakTarget ? this.peakTarget : null
    if (peak) {
      if (limit) peak.setAttribute("max", limit)
      else peak.removeAttribute("max")
    }
    if (!this.hasHintTarget) return
    if (limit) {
      this.hintTarget.textContent = `该池所属厂区峰值上限 ${limit}℃，超限保存将被拒绝（上限不替代出灰 ≥ 60℃ 规则）。`
      this.hintTarget.className = "limit-tag on"
    } else {
      this.hintTarget.textContent = "该池所属厂区峰值上限条已停用，峰值写入不拦截。"
      this.hintTarget.className = "limit-tag off"
    }
  }
}

application.register("flash", FlashController)
application.register("form-hint", FormHintController)
application.register("board", BoardController)
application.register("peak-limit", PeakLimitController)
