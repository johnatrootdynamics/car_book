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

document.addEventListener("DOMContentLoaded", () => {
  setupEnhancedForms()
  setupCounters()
  setupAutoResizeTextareas()
  setupCommentValidation()
})
