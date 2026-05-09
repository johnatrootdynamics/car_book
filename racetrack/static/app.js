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

document.addEventListener("DOMContentLoaded", () => {
  setupEnhancedForms()
  setupCounters()
  setupAutoResizeTextareas()
  setupCommentValidation()
  setupLandingFlow()
})
