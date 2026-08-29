function setupEnhancedForms() {
  const forms = document.querySelectorAll("form[data-enhanced]")
  forms.forEach((form) => {
    form.addEventListener("submit", () => {
      const submit = form.querySelector("button[type='submit'], input[type='submit']")
      if (!submit) return
      submit.dataset.originalText = submit.innerText || submit.value
      if (submit.tagName === "BUTTON") submit.innerText = "Saving..."
      if (submit.tagName === "INPUT") submit.value = "Saving..."
      submit.disabled = true
    })
  })
}

function setupCounters() {
  const fields = document.querySelectorAll("[data-counter]")
  fields.forEach((field) => {
    const counterId = field.getAttribute("data-counter")
    const counter = document.getElementById(counterId)
    if (!counter) return
    const max = Number(field.getAttribute("maxlength") || 0)
    const update = () => {
      const count = field.value.length
      counter.textContent = max > 0 ? `${count}/${max}` : `${count}`
    }
    field.addEventListener("input", update)
    update()
  })
}

function setupAutoResizeTextareas() {
  const textareas = document.querySelectorAll("textarea[data-autoresize]")
  textareas.forEach((ta) => {
    const resize = () => {
      ta.style.height = "auto"
      ta.style.height = `${Math.max(88, ta.scrollHeight)}px`
    }
    ta.addEventListener("input", resize)
    resize()
  })
}

function setupCommentValidation() {
  const forms = document.querySelectorAll("form[data-comment-form]")
  forms.forEach((form) => {
    const textarea = form.querySelector("textarea")
    const submit = form.querySelector("button[type='submit'], input[type='submit']")
    if (!textarea || !submit) return
    const update = () => {
      submit.disabled = textarea.value.trim().length === 0
    }
    textarea.addEventListener("input", update)
    update()
  })
}

function setupLandingFlow() {
  const landing = document.querySelector("[data-landing-page]")
  if (!landing) return

  const links = Array.from(landing.querySelectorAll(".flow-link"))
  const sections = Array.from(landing.querySelectorAll("[data-flow-section]"))
  if (links.length === 0 || sections.length === 0) return

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href")
      if (!href || !href.startsWith("#")) return
      const target = document.querySelector(href)
      if (!target) return
      event.preventDefault()
      target.scrollIntoView({ behavior: "smooth", block: "start" })
    })
  })

  const setActive = (id) => {
    links.forEach((link) => {
      const active = link.getAttribute("href") === `#${id}`
      link.classList.toggle("is-active", active)
    })
  }

  const sectionObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        if (entry.target.id) setActive(entry.target.id)
      })
    },
    { rootMargin: "-35% 0px -52% 0px", threshold: 0.2 }
  )

  const revealObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return
        entry.target.classList.add("is-visible")
        observer.unobserve(entry.target)
      })
    },
    { threshold: 0.12 }
  )

  sections.forEach((section) => {
    sectionObserver.observe(section)
    revealObserver.observe(section)
  })

  setActive("overview")
}

function setupDriverClassSearch() {
  const root = document.querySelector("[data-class-search]")
  if (!root) return

  const input = root.querySelector(".class-search-input")
  const results = root.querySelector(".class-search-results")
  const searchUrl = root.getAttribute("data-search-url")
  const csrfToken = root.getAttribute("data-csrf-token")
  if (!input || !results || !searchUrl || !csrfToken) return

  const classLabel = (value) => {
    if (value === "A") return "Advanced"
    if (value === "B") return "Intermediate"
    return "Novice"
  }

  const renderResults = (drivers) => {
    results.innerHTML = ""
    if (!drivers.length) {
      const empty = document.createElement("p")
      empty.className = "muted-line"
      empty.textContent = "No drivers found."
      results.appendChild(empty)
      return
    }

    const grid = document.createElement("div")
    grid.className = "class-manager-grid"

    drivers.forEach((driver) => {
      const card = document.createElement("article")
      card.className = "class-manager-card"
      card.innerHTML = `
        <div class="class-manager-head">
          <strong>${driver.name}</strong>
          <span class="driver-class-pill driver-class-${driver.driver_class}">Current: ${driver.driver_class}</span>
        </div>
        <p class="muted-line">${driver.email}</p>
        <div class="class-actions">
          <form method="post" action="${driver.update_url}">
            <input type="hidden" name="csrf_token" value="${csrfToken}">
            <input type="hidden" name="driver_class" value="A">
            <button type="submit" class="btn btn-sm ${driver.driver_class === "A" ? "class-btn-active class-A" : "btn-secondary"}">Set A</button>
          </form>
          <form method="post" action="${driver.update_url}">
            <input type="hidden" name="csrf_token" value="${csrfToken}">
            <input type="hidden" name="driver_class" value="B">
            <button type="submit" class="btn btn-sm ${driver.driver_class === "B" ? "class-btn-active class-B" : "btn-secondary"}">Set B</button>
          </form>
          <form method="post" action="${driver.update_url}">
            <input type="hidden" name="csrf_token" value="${csrfToken}">
            <input type="hidden" name="driver_class" value="C">
            <button type="submit" class="btn btn-sm ${driver.driver_class === "C" ? "class-btn-active class-C" : "btn-secondary"}">Set C</button>
          </form>
        </div>
        <p class="hint">${classLabel(driver.driver_class)}</p>
      `
      grid.appendChild(card)
    })

    results.appendChild(grid)
  }

  let timer = null
  input.addEventListener("input", () => {
    const q = input.value.trim()
    if (timer) clearTimeout(timer)

    if (q.length < 2) {
      results.innerHTML = ""
      return
    }

    timer = setTimeout(async () => {
      try {
        const response = await fetch(`${searchUrl}?q=${encodeURIComponent(q)}`, {
          headers: { Accept: "application/json" },
        })
        const data = await response.json()
        renderResults(data.drivers || [])
      } catch (error) {
        results.innerHTML = '<p class="flash flash-error">Search failed. Try again.</p>'
      }
    }, 180)
  })
}

function setupSidebarToggle() {
  const toggle = document.querySelector("[data-sidebar-toggle]")
  const overlay = document.querySelector("[data-sidebar-overlay]")
  if (!toggle || !overlay) return

  const isMobile = () => window.innerWidth <= 960

  const closeMobileSidebar = () => document.body.classList.remove("sidebar-open")

  toggle.addEventListener("click", () => {
    if (isMobile()) {
      document.body.classList.toggle("sidebar-open")
      document.body.classList.remove("sidebar-collapsed")
    } else {
      document.body.classList.toggle("sidebar-collapsed")
      document.body.classList.remove("sidebar-open")
    }
  })

  overlay.addEventListener("click", closeMobileSidebar)

  window.addEventListener("resize", () => {
    if (!isMobile()) document.body.classList.remove("sidebar-open")
  })
}

function setupProfilePhotoUpload() {
  const form = document.querySelector("[data-profile-photo-form]")
  if (!form) return
  const trigger = form.querySelector("[data-profile-photo-trigger]")
  const input = form.querySelector("[data-profile-photo-input]")
  if (!trigger || !input) return

  trigger.addEventListener("click", () => input.click())
  input.addEventListener("change", () => {
    if (!input.files || input.files.length === 0) return
    form.submit()
  })
}

function setupLiveTrackSearch() {
  const form = document.querySelector("[data-live-track-search]")
  if (!form) return

  const input = form.querySelector("[data-track-search-input]")
  const cards = Array.from(document.querySelectorAll("[data-track-card]"))
  const empty = document.querySelector("[data-track-search-empty]")
  if (!input || cards.length === 0) return

  const filter = () => {
    const q = input.value.trim().toLowerCase()
    let visibleCount = 0
    cards.forEach((card) => {
      const haystack = card.getAttribute("data-track-search-text") || ""
      const show = q.length === 0 || haystack.includes(q)
      card.style.display = show ? "" : "none"
      if (show) visibleCount += 1
    })
    if (empty) empty.style.display = visibleCount === 0 ? "block" : "none"
  }

  input.addEventListener("input", filter)
  filter()
}

function setupInspectionNameSearch() {
  const root = document.querySelector("[data-inspect-name-search]")
  if (!root) return

  const input = root.querySelector("[data-inspect-name-input]")
  const results = root.querySelector("[data-inspect-name-results]")
  const searchUrl = root.getAttribute("data-search-url")
  if (!input || !results || !searchUrl) return

  const render = (rows) => {
    results.innerHTML = ""
    if (!rows.length) {
      const p = document.createElement("p")
      p.className = "muted-line"
      p.textContent = "No matching drivers."
      results.appendChild(p)
      return
    }

    const grid = document.createElement("div")
    grid.className = "class-manager-grid"
    rows.forEach((row) => {
      const card = document.createElement("article")
      card.className = "class-manager-card"
      card.innerHTML = `
        <div class="class-manager-head"><strong>${row.driver_name}</strong><span class="muted-line">@${row.username}</span></div>
        <p class="muted-line">${row.car}</p>
        <p class="muted-line">Code: <code>${row.checkin_code}</code></p>
        ${row.waiver_ok ? `<a class="btn btn-sm" href="${row.inspect_url}">Open Inspection</a>` : `<span class="badge badge-failed">Waiver Missing</span>`}
      `
      grid.appendChild(card)
    })
    results.appendChild(grid)
  }

  let timer = null
  input.addEventListener("input", () => {
    const q = input.value.trim()
    if (timer) clearTimeout(timer)
    if (q.length < 2) {
      results.innerHTML = ""
      return
    }
    timer = setTimeout(async () => {
      try {
        const response = await fetch(`${searchUrl}?q=${encodeURIComponent(q)}`, {
          headers: { Accept: "application/json" },
        })
        const data = await response.json()
        render(data.rows || [])
      } catch (error) {
        results.innerHTML = '<p class="flash flash-error">Lookup failed. Try again.</p>'
      }
    }, 180)
  })
}

function setupTicketQrScanner() {
  const root = document.querySelector("[data-ticket-scanner]")
  if (!root) return

  const form = root.querySelector("[data-ticket-qr-form]")
  const input = root.querySelector("[data-ticket-qr-input]")
  const startButton = root.querySelector("[data-ticket-camera-start]")
  const panel = root.querySelector("[data-ticket-camera-panel]")
  const status = root.querySelector("[data-ticket-camera-status]")
  const reader = root.querySelector("[data-ticket-qr-reader]")
  const activeInput = root.querySelector("[data-ticket-scanner-active]")
  if (!form || !input || !startButton || !panel || !reader || !activeInput) return

  const extractCode = (value) => {
    const raw = (value || "").trim()
    if (!raw.toLowerCase().startsWith("http")) return raw
    try {
      return new URL(raw).searchParams.get("code") || raw
    } catch (error) {
      return raw
    }
  }

  let scanner = null
  let submitted = false
  let starting = false
  const currentCode = (root.dataset.currentCode || "").trim().toUpperCase()

  const startScanner = async () => {
    if (starting || scanner) return
    if (typeof window.Html5Qrcode === "undefined") {
      if (status) status.textContent = "Camera scanning could not load. Enter the ticket code manually."
      panel.hidden = false
      return
    }
    starting = true
    panel.hidden = false
    startButton.disabled = true
    startButton.innerHTML = '<i class="bi bi-broadcast-pin" aria-hidden="true"></i> Continuous scanner active'
    activeInput.value = "1"
    if (status) status.textContent = "Starting camera…"
    try {
      scanner = new window.Html5Qrcode(reader.id)
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 230, height: 230 }, aspectRatio: 1 },
        (decodedText) => {
          if (submitted) return
          const decodedCode = extractCode(decodedText).trim().toUpperCase()
          if (!decodedCode) return
          if (decodedCode === currentCode) {
            if (status) status.textContent = "This ticket is already displayed. Move it away — ready for the next guest."
            return
          }
          submitted = true
          input.value = decodedCode
          if (status) status.textContent = "Ticket found. Verifying…"
          form.requestSubmit()
        },
        () => {}
      )
      if (status) status.textContent = currentCode
        ? "Move the last ticket away, then present the next QR code."
        : "Scanner is ready. Point the camera at a ticket QR code."
    } catch (error) {
      scanner = null
      startButton.disabled = false
      startButton.innerHTML = '<i class="bi bi-camera" aria-hidden="true"></i> Resume continuous scanner'
      if (status) status.textContent = "Camera access was unavailable. Check permission or enter the code manually."
    } finally {
      starting = false
    }
  }

  startButton.addEventListener("click", startScanner)

  if (root.dataset.verificationState === "used" && typeof navigator.vibrate === "function") {
    navigator.vibrate([180, 80, 180])
  }

  if (root.dataset.scannerActive === "1") {
    window.setTimeout(startScanner, 120)
  }
}

function setupInspectionQrScanner() {
  const root = document.querySelector("[data-inspection-scanner]")
  if (!root) return

  const form = root.querySelector("[data-inspection-qr-form]")
  const input = root.querySelector("[data-inspection-qr-input]")
  const startButton = root.querySelector("[data-inspection-camera-start]")
  const panel = root.querySelector("[data-inspection-camera-panel]")
  const status = root.querySelector("[data-inspection-camera-status]")
  const reader = root.querySelector("[data-inspection-qr-reader]")
  const activeInput = root.querySelector("[data-inspection-scanner-active]")
  if (!form || !input || !startButton || !panel || !reader || !activeInput) return

  const extractCode = (value) => {
    const raw = (value || "").trim()
    if (!raw.toLowerCase().startsWith("http")) return raw
    try {
      return new URL(raw).searchParams.get("code") || raw
    } catch (error) {
      return raw
    }
  }

  let scanner = null
  let submitted = false
  let starting = false
  const currentCode = (root.dataset.currentCode || "").trim().toUpperCase()

  const startScanner = async () => {
    if (starting || scanner) return
    if (typeof window.Html5Qrcode === "undefined") {
      panel.hidden = false
      if (status) status.textContent = "Camera scanning could not load. Enter a QR code, name, or email above."
      return
    }
    starting = true
    panel.hidden = false
    startButton.disabled = true
    startButton.innerHTML = '<i class="bi bi-broadcast-pin" aria-hidden="true"></i> Camera active'
    activeInput.value = "1"
    if (status) status.textContent = "Starting camera…"
    try {
      scanner = new window.Html5Qrcode(reader.id)
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 230, height: 230 }, aspectRatio: 1 },
        (decodedText) => {
          if (submitted) return
          const decodedCode = extractCode(decodedText).trim().toUpperCase()
          if (!decodedCode) return
          if (decodedCode === currentCode) {
            if (status) status.textContent = "That code was just checked. Move it away, then present the next driver’s QR."
            return
          }
          submitted = true
          input.value = decodedCode
          if (status) status.textContent = "Driver found. Opening inspection…"
          form.requestSubmit()
        },
        () => {}
      )
      if (status) status.textContent = currentCode
        ? "Ready for the next driver. Point the camera at their QR code."
        : "Scanner ready. Point the camera at the driver’s QR code."
    } catch (error) {
      scanner = null
      startButton.disabled = false
      startButton.innerHTML = '<i class="bi bi-camera" aria-hidden="true"></i> Resume camera'
      if (status) status.textContent = "Camera access was unavailable. Check permission or use the lookup field above."
    } finally {
      starting = false
    }
  }

  startButton.addEventListener("click", startScanner)
  if (root.dataset.scannerActive === "1") window.setTimeout(startScanner, 120)
}

document.addEventListener("DOMContentLoaded", () => {
  setupEnhancedForms()
  setupCounters()
  setupAutoResizeTextareas()
  setupCommentValidation()
  setupLandingFlow()
  setupDriverClassSearch()
  setupSidebarToggle()
  setupProfilePhotoUpload()
  setupLiveTrackSearch()
  setupInspectionNameSearch()
  setupTicketQrScanner()
  setupInspectionQrScanner()
})
