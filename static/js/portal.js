/* Emendas.gov.com — interações do portal público
   Spinner "Aguarde..." + Assistente de Transparência IA (Gemini). */

(function () {
  "use strict";

  // ---------- Spinner de carregamento ----------
  const overlay = document.getElementById("spinner-overlay");

  function mostrarSpinner() {
    if (overlay) overlay.classList.add("ativo");
  }

  function ocultarSpinner() {
    if (overlay) overlay.classList.remove("ativo");
  }

  // Exibe o spinner ao enviar formulários de pesquisa e ao navegar em links
  // marcados com data-spinner (transições de tela / drill-downs).
  document.querySelectorAll("form[data-spinner]").forEach(function (form) {
    form.addEventListener("submit", mostrarSpinner);
  });
  document.querySelectorAll("a[data-spinner]").forEach(function (link) {
    link.addEventListener("click", mostrarSpinner);
  });
  window.addEventListener("pageshow", ocultarSpinner);

  // ---------- Assistente de Transparência IA ----------
  const fab = document.getElementById("fab-chat");
  const drawer = document.getElementById("chat-drawer");
  if (!fab || !drawer) return;

  const mensagens = drawer.querySelector(".chat-mensagens");
  const formulario = drawer.querySelector(".chat-entrada");
  const entrada = formulario.querySelector("input");
  const chips = drawer.querySelector(".chat-chips");
  const urlAssistente = drawer.dataset.url;
  const tokenCsrf = drawer.dataset.csrf;

  fab.addEventListener("click", function () {
    drawer.classList.toggle("aberto");
    if (drawer.classList.contains("aberto")) entrada.focus();
  });
  drawer.querySelector(".fechar").addEventListener("click", function () {
    drawer.classList.remove("aberto");
  });

  function adicionarMensagem(texto, classe) {
    const el = document.createElement("div");
    el.className = "msg " + classe;
    el.textContent = texto;
    mensagens.appendChild(el);
    mensagens.scrollTop = mensagens.scrollHeight;
    return el;
  }

  function perguntar(pergunta) {
    if (!pergunta.trim()) return;
    if (chips) chips.style.display = "none";
    adicionarMensagem(pergunta, "usuario");
    const aguardando = adicionarMensagem("Consultando os dados do município…", "ia");
    fetch(urlAssistente, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": tokenCsrf,
      },
      body: JSON.stringify({ pergunta: pergunta }),
    })
      .then(function (resp) { return resp.json(); })
      .then(function (dados) {
        aguardando.textContent =
          dados.resposta || dados.erro || "Não consegui responder agora.";
      })
      .catch(function () {
        aguardando.textContent =
          "Estamos com instabilidade momentânea. Tente novamente em instantes.";
      });
  }

  formulario.addEventListener("submit", function (evento) {
    evento.preventDefault();
    const texto = entrada.value;
    entrada.value = "";
    perguntar(texto);
  });

  if (chips) {
    chips.querySelectorAll("button").forEach(function (chip) {
      chip.addEventListener("click", function () {
        perguntar(chip.textContent.trim());
      });
    });
  }
})();
