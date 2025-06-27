const BACKEND_URL = "https://descargayt-hw7y.onrender.com"

// Elementos del DOM
const form = document.getElementById("form")
const submitBtn = document.getElementById("submit-btn")
const message = document.getElementById("message")
const progressSection = document.getElementById("progress-section")
const progressBar = document.getElementById("progress-bar")
const progressText = document.getElementById("progress-text")
const funnyMessage = document.getElementById("funny-message")
const funnyText = document.getElementById("funny-text")
const urlInput = document.getElementById("url")
const formatSelect = document.getElementById("format")

// Frases divertidas e irónicas
const funnyMessages = [
  "Mientras esperas, recuerda que esto lo hizo un abogado... ¡por amor! 💕",
  "Servidor gratuito detectado. Paciencia nivel: esposa de abogado 😅",
  "El amor no tiene precio, pero el hosting sí... y elegimos el barato 💸",
  "Procesando con la velocidad de un trámite legal... pero gratis 📋",
  "Este sitio funciona con café y amor conyugal ☕❤️",
  "Mientras descargas, el servidor está pidiendo más RAM a los Reyes Magos 🎁",
  "Velocidad patrocinada por 'Hazlo por amor, no por dinero' 💝",
  "El servidor está trabajando más duro que un abogado en temporada de divorcios 👨‍💼",
  "Gratis como el amor... y a veces igual de lento 🐌",
  "Procesando en un servidor que cuesta menos que una cena romántica 🍝",
  "La paciencia es una virtud... especialmente con hosting gratuito 😇",
  "Mientras esperas, piensa que alguien programó esto en lugar de ver Netflix 📺",
  "Servidor alimentado por suspiros de amor y oraciones 🙏",
  "Velocidad: 'Lo hice por ti, mi amor' edition 💕",
  "El amor es paciente, el servidor... también (por necesidad) ⏰",
  "Procesando con la dedicación de un esposo enamorado 💑",
  "Gratis como los consejos legales en reuniones familiares 👨‍⚖️",
  "El servidor está haciendo su mejor esfuerzo... como en el matrimonio 💒",
  "Velocidad patrocinada por 'Feliz esposa, vida feliz' 👸",
  "Mientras descargas, recuerda: esto nació del amor verdadero 💖",
  "Procesando con amor artesanal y presupuesto de estudiante 🎓",
  "El servidor trabaja por amor, no por dinero... se nota ¿verdad? 😂",
  "Paciencia nivel: esperar que tu esposo termine un proyecto 'rápido' 🔧",
  "Gratis como las flores del jardín... pero menos rápido 🌸",
  "El amor mueve montañas, pero el servidor va más despacio 🏔️",
  "Procesando con la velocidad del romance: lento pero seguro 🐢💕",
  "Mientras esperas, alguien está orgulloso de haber hecho esto funcionar 🏆",
  "Servidor powered by 'Sí, mi amor, ya casi termino' ⚡",
  "La descarga va lenta, pero el amor que hay detrás es infinito ∞",
  "Gratis como los abrazos... y a veces igual de necesarios 🤗",
]

// Keep-alive para evitar que el servidor se duerma
setInterval(
  () => {
    fetch(`${BACKEND_URL}/health`).catch(() => {})
  },
  5 * 60 * 1000,
) // Cada 5 minutos

// Función para obtener mensaje divertido aleatorio
function getRandomFunnyMessage() {
  const randomIndex = Math.floor(Math.random() * funnyMessages.length)
  return funnyMessages[randomIndex]
}

// Función para mostrar mensaje divertido
function showFunnyMessage() {
  const randomMessage = getRandomFunnyMessage()
  funnyText.textContent = randomMessage
  funnyMessage.classList.remove("hidden")
}

// Función para ocultar mensaje divertido
function hideFunnyMessage() {
  funnyMessage.classList.add("hidden")
}

// Función para actualizar el botón
function updateButton(loading, text) {
  const btnIcon = submitBtn.querySelector(".btn-icon")
  const btnText = submitBtn.querySelector(".btn-text")

  if (loading) {
    btnIcon.innerHTML = '<div class="loading-spinner"></div>'
    btnText.textContent = text || "Procesando..."
    submitBtn.disabled = true
  } else {
    btnIcon.textContent = "⬇️"
    btnText.textContent = "Descargar"
    submitBtn.disabled = false
  }
}

// Función para mostrar progreso
function showProgress(status, percentage = 0) {
  progressSection.classList.remove("hidden")
  progressBar.style.width = percentage + "%"
  progressText.textContent = status
  showFunnyMessage()
}

// Función para actualizar progreso
function updateProgress(percentage, status) {
  progressBar.style.width = percentage + "%"
  progressText.textContent = status
  showFunnyMessage() // Cambiar mensaje en cada actualización
}

// Función para mostrar mensaje de éxito
function showSuccess(text) {
  progressSection.classList.add("hidden")
  hideFunnyMessage()
  message.textContent = text
  message.className = "message success"
  resetForm()
}

// Función para mostrar mensaje de error
function showError(text) {
  progressSection.classList.add("hidden")
  hideFunnyMessage()
  message.textContent = text
  message.className = "message error"
  resetForm()
}

// Función para resetear el formulario
function resetForm() {
  updateButton(false)
  progressBar.style.width = "0%"
}

// Función para descargar archivo
function downloadFile(downloadUrl) {
  const link = document.createElement("a")
  link.href = downloadUrl
  link.download = ""
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

// Función para hacer polling del estado de la tarea
function pollTaskStatus(taskId) {
  const interval = setInterval(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/status/${taskId}`)
      const data = await response.json()

      if (data.state === "PENDING") {
        updateProgress(10, "Esperando en cola...")
      } else if (data.state === "PROGRESS") {
        updateProgress(50, data.status || "Procesando...")
      } else if (data.state === "SUCCESS") {
        clearInterval(interval)
        updateProgress(100, "¡Descarga completada!")

        setTimeout(() => {
          showSuccess("¡Listo! La descarga comenzará automáticamente...")
          downloadFile(data.download_url)
        }, 1000)
      } else if (data.state === "FAILURE") {
        clearInterval(interval)
        showError("Error: " + (data.error || "Error desconocido"))
      }
    } catch (err) {
      clearInterval(interval)
      showError("Error al verificar el estado de la descarga")
      console.error("Error en polling:", err)
    }
  }, 2000) // Verificar cada 2 segundos
}

// Event listener para el formulario
form.addEventListener("submit", async (e) => {
  e.preventDefault()
  const url = urlInput.value
  const format = formatSelect.value

  // Limpiar mensajes anteriores
  message.textContent = ""
  message.className = "message"

  // Iniciar descarga
  updateButton(true, "Procesando...")
  showProgress("Iniciando...", 5)

  try {
    // Iniciar descarga asíncrona
    const response = await fetch(`${BACKEND_URL}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url, format: format }),
    })

    const data = await response.json()

    if (response.ok && data.success) {
      // Iniciar polling del estado
      pollTaskStatus(data.task_id)
    } else {
      showError("Error: " + (data.error || "Respuesta inesperada del servidor."))
    }
  } catch (err) {
    showError("Error de conexión. Verifica tu conexión a internet.")
    console.error("Error en el fetch:", err)
  }
})

// Efectos adicionales para mejorar la experiencia
urlInput.addEventListener("paste", () => {
  setTimeout(() => {
    if (urlInput.value) {
      urlInput.style.borderColor = "#10b981"
      setTimeout(() => {
        urlInput.style.borderColor = "#e5e7eb"
      }, 1000)
    }
  }, 100)
})

// Animación sutil al cargar la página
document.addEventListener("DOMContentLoaded", () => {
  document.body.style.opacity = "0"
  document.body.style.transition = "opacity 0.5s ease"

  setTimeout(() => {
    document.body.style.opacity = "1"
  }, 100)
})
