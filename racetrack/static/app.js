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

  const closeSidebar = () => document.body.classList.remove("sidebar-open")

  toggle.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open")
  })

  overlay.addEventListener("click", closeSidebar)

  window.addEventListener("resize", () => {
    if (window.innerWidth > 960) closeSidebar()
  })
}

document.addEventListener("DOMContentLoaded", () => {
  setupEnhancedForms()
  setupCounters()
  setupAutoResizeTextareas()
  setupCommentValidation()
  setupLandingFlow()
  setupDriverClassSearch()
  setupSidebarToggle()
})
