// CAROL - Frontend Application Logic

// Estado global
let usuarioLogado = null;
let partesGlobais = [];
let temp2FAToken = null;
let comunicacoesCarregadas = [];
let intervalMetricas = null;

document.addEventListener("DOMContentLoaded", () => {
  verificarAutenticacao();
});

// --- Sistema de Notificações Toast ---
function mostrarToast(mensagem, tipo = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${tipo}`;
  
  const icon = tipo === "success" ? "✓" : tipo === "error" ? "✕" : "ℹ";
  toast.innerHTML = `<span style="font-weight: 700;">${icon}</span><span>${mensagem}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ==============================================================================
// 1. FLUXO DE AUTENTICAÇÃO E SESSÃO
// ==============================================================================

async function checarSetupStatus() {
  try {
    const res = await fetch("/api/auth/setup-status");
    if (!res.ok) return false;
    const dados = await res.json();
    return dados.setup_necessario === true;
  } catch (e) {
    return false;
  }
}

async function verificarAutenticacao() {
  try {
    const res = await fetch("/api/auth/me");
    if (res.ok) {
      usuarioLogado = await res.json();
      aplicarUsuarioLogado();
    } else {
      await exibirTelaLogin();
    }
  } catch (err) {
    await exibirTelaLogin();
  }
}

async function exibirTelaLogin() {
  usuarioLogado = null;
  const loginScreen = document.getElementById("login-screen");
  const mainLayout = document.getElementById("app-main-layout");
  if (loginScreen) loginScreen.style.display = "flex";
  if (mainLayout) mainLayout.style.display = "none";
  if (intervalMetricas) {
    clearInterval(intervalMetricas);
    intervalMetricas = null;
  }

  const precisaSetup = await checarSetupStatus();
  const fLogin = document.getElementById("form-login");
  const f2fa = document.getElementById("form-login-2fa");
  const fSetup = document.getElementById("form-setup-inicial");

  if (precisaSetup) {
    if (fLogin) fLogin.style.display = "none";
    if (f2fa) f2fa.style.display = "none";
    if (fSetup) fSetup.style.display = "block";
  } else {
    if (fSetup) fSetup.style.display = "none";
    if (f2fa) f2fa.style.display = "none";
    if (fLogin) fLogin.style.display = "block";
  }
}

async function realizarSetupInicial(e) {
  e.preventDefault();
  const nome = document.getElementById("setup-nome").value.trim();
  const email = document.getElementById("setup-email").value.trim();
  const senha = document.getElementById("setup-senha").value;
  const senhaConfirma = document.getElementById("setup-senha-confirma").value;
  const btn = document.getElementById("btn-setup-submit");

  if (senha !== senhaConfirma) {
    mostrarToast("A confirmação de senha não confere.", "error");
    return;
  }

  btn.disabled = true;
  btn.innerText = "Criando Administrador...";

  try {
    const res = await fetch("/api/auth/setup-inicial", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nome, email, senha })
    });

    const dados = await res.json();
    if (!res.ok) {
      throw new Error(dados.detail || "Erro ao realizar configuração inicial.");
    }

    mostrarToast("Administrador configurado com sucesso! Bem-vindo ao CAROL.", "success");
    usuarioLogado = dados.usuario;
    aplicarUsuarioLogado();
  } catch (err) {
    mostrarToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "Criar Administrador e Iniciar";
  }
}

function aplicarUsuarioLogado() {
  const loginScreen = document.getElementById("login-screen");
  const mainLayout = document.getElementById("app-main-layout");
  if (loginScreen) loginScreen.style.display = "none";
  if (mainLayout) mainLayout.style.display = "block";

  // Preenche dados do usuário no header
  const elNome = document.getElementById("header-user-nome");
  const elBadge = document.getElementById("header-user-badge");
  const elAvatar = document.getElementById("user-avatar-initial");

  if (elNome) elNome.innerText = usuarioLogado.nome;
  if (elBadge) elBadge.innerText = usuarioLogado.perfil === "admin" ? "Administrador" : "Operador";
  if (elAvatar) elAvatar.innerText = usuarioLogado.nome.charAt(0).toUpperCase();

  // Exibe aba admin se for administrador
  const tabAdmin = document.getElementById("tab-btn-admin");
  if (tabAdmin) {
    tabAdmin.style.display = usuarioLogado.perfil === "admin" ? "flex" : "none";
  }

  // Carrega dados iniciais
  carregarMetricas();
  carregarPartes();

  if (!intervalMetricas) {
    intervalMetricas = setInterval(carregarMetricas, 30000);
  }
}

async function realizarLogin(e) {
  e.preventDefault();
  const email = document.getElementById("login-email").value.trim();
  const senha = document.getElementById("login-senha").value;
  const btn = document.getElementById("btn-login-submit");

  btn.disabled = true;
  btn.innerText = "Verificando...";

  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, senha })
    });

    const dados = await res.json();

    if (!res.ok) {
      throw new Error(dados.detail || "Falha no login");
    }

    if (dados.status === "2fa_obrigatorio") {
      temp2FAToken = dados.temp_token;
      document.getElementById("form-login").style.display = "none";
      document.getElementById("form-login-2fa").style.display = "block";
      const totpInput = document.getElementById("login-totp-codigo");
      totpInput.value = "";
      totpInput.focus();
      mostrarToast("Código de 6 dígitos do Google Authenticator solicitado.", "info");
    } else {
      usuarioLogado = dados.usuario;
      mostrarToast(`Bem-vindo(a), ${usuarioLogado.nome}!`, "success");
      aplicarUsuarioLogado();
    }
  } catch (err) {
    mostrarToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "Entrar no Sistema";
  }
}

async function confirmarLogin2FA(e) {
  e.preventDefault();
  const codigo = document.getElementById("login-totp-codigo").value.trim();
  const btn = document.getElementById("btn-login-2fa-submit");

  btn.disabled = true;
  btn.innerText = "Validando código...";

  try {
    const res = await fetch("/api/auth/login-2fa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ temp_token: temp2FAToken, codigo_2fa: codigo })
    });

    const dados = await res.json();

    if (!res.ok) {
      throw new Error(dados.detail || "Código 2FA incorreto.");
    }

    usuarioLogado = dados.usuario;
    mostrarToast("Autenticação em dois fatores confirmada com sucesso!", "success");
    aplicarUsuarioLogado();
  } catch (err) {
    mostrarToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "Verificar e Entrar";
  }
}

function voltarParaEtapa1Login() {
  temp2FAToken = null;
  const f1 = document.getElementById("form-login");
  const f2 = document.getElementById("form-login-2fa");
  const fSetup = document.getElementById("form-setup-inicial");
  if (fSetup) fSetup.style.display = "none";
  if (f1) f1.style.display = "block";
  if (f2) f2.style.display = "none";
}

async function fazerLogout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  mostrarToast("Sessão finalizada.", "info");
  exibirTelaLogin();
}

// ==============================================================================
// 2. CONFIGURAÇÃO DE 2FA (GOOGLE AUTHENTICATOR)
// ==============================================================================

async function abrirModalGerenciar2FA() {
  if (!usuarioLogado) return;
  const modal = document.getElementById("modal-2fa");
  const boxAtivacao = document.getElementById("conteudo-ativacao-2fa");
  const boxDesativar = document.getElementById("conteudo-desativar-2fa");

  if (usuarioLogado.totp_habilitado) {
    boxAtivacao.style.display = "none";
    boxDesativar.style.display = "block";
    document.getElementById("senha-desativar-2fa").value = "";
  } else {
    boxAtivacao.style.display = "block";
    boxDesativar.style.display = "none";
    document.getElementById("codigo-confirmar-2fa").value = "";

    try {
      const res = await fetch("/api/auth/2fa/gerar", { method: "POST" });
      const dados = await res.json();
      document.getElementById("img-qrcode-2fa").src = dados.qrcode_base64;
      document.getElementById("texto-chave-backup-2fa").innerText = dados.secret;
    } catch (err) {
      mostrarToast("Erro ao gerar QR Code para 2FA.", "error");
    }
  }

  modal.classList.add("open");
}

function fecharModal2FA() {
  document.getElementById("modal-2fa").classList.remove("open");
}

async function confirmarAtivacao2FA(e) {
  e.preventDefault();
  const codigo = document.getElementById("codigo-confirmar-2fa").value.trim();

  try {
    const res = await fetch("/api/auth/2fa/confirmar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ codigo_2fa: codigo })
    });

    const dados = await res.json();
    if (!res.ok) throw new Error(dados.detail || "Código incorreto");

    usuarioLogado.totp_habilitado = true;
    mostrarToast("Autenticação 2FA ativada com sucesso!", "success");
    fecharModal2FA();
    if (usuarioLogado.perfil === "admin") carregarUsuarios();
  } catch (err) {
    mostrarToast(err.message, "error");
  }
}

async function desativar2FA(e) {
  e.preventDefault();
  const senha = document.getElementById("senha-desativar-2fa").value;

  try {
    const res = await fetch("/api/auth/2fa/desativar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ senha })
    });

    const dados = await res.json();
    if (!res.ok) throw new Error(dados.detail || "Erro ao desativar 2FA");

    usuarioLogado.totp_habilitado = false;
    mostrarToast("2FA desativado.", "info");
    fecharModal2FA();
    if (usuarioLogado.perfil === "admin") carregarUsuarios();
  } catch (err) {
    mostrarToast(err.message, "error");
  }
}

// ==============================================================================
// 3. ÁREA ADMINISTRATIVA: GESTÃO DE USUÁRIOS
// ==============================================================================

let usuariosGlobais = [];

async function carregarUsuarios() {
  if (!usuarioLogado || usuarioLogado.perfil !== "admin") return;

  const tbody = document.getElementById("tabela-usuarios-body");
  try {
    const res = await fetch("/api/usuarios");
    usuariosGlobais = await res.json();

    if (!usuariosGlobais || usuariosGlobais.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2rem;">Nenhum usuário cadastrado.</td></tr>`;
      return;
    }

    tbody.innerHTML = usuariosGlobais.map(u => {
      const perfilBadge = u.perfil === "admin"
        ? `<span class="badge badge-indigo">Administrador</span>`
        : `<span class="badge badge-cyan">Operador</span>`;

      const totpBadge = u.totp_habilitado
        ? `<span class="badge badge-emerald">🟢 Ativo (Google Auth)</span>`
        : `<span class="badge badge-amber">⚪ Pendente</span>`;

      const statusBadge = u.ativo
        ? `<span class="badge badge-emerald">Ativo</span>`
        : `<span class="badge badge-rose">Inativo</span>`;

      const botaoReset2FA = u.totp_habilitado
        ? `<button class="btn btn-secondary btn-sm" onclick="resetar2FAUsuario(${u.id}, '${u.nome}')" title="Resetar 2FA caso o usuário tenha perdido o smartphone">🛡️ Reset 2FA</button>`
        : "";

      return `
        <tr>
          <td>
            <div style="font-weight: 700; color: #f8fafc;">${u.nome}</div>
            <div style="font-size: 0.75rem; color: var(--text-muted);">ID #${u.id}</div>
          </td>
          <td style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-cyan);">${u.email}</td>
          <td>${perfilBadge}</td>
          <td>${totpBadge}</td>
          <td>${statusBadge}</td>
          <td style="font-size: 0.8rem; color: var(--text-muted);">${u.criado_em}</td>
          <td style="text-align: right; white-space: nowrap;">
            ${botaoReset2FA}
            <button class="btn btn-secondary btn-sm" onclick="editarUsuario(${u.id})" title="Editar Usuário">✏️</button>
            <button class="btn btn-danger btn-sm" onclick="excluirUsuario(${u.id}, '${u.nome}')" title="Excluir Usuário">🗑️</button>
          </td>
        </tr>
      `;
    }).join("");

  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="color: var(--accent-rose); text-align: center;">Erro ao carregar usuários.</td></tr>`;
  }
}

function abrirModalNovoUsuario() {
  document.getElementById("modal-usuario-titulo").innerText = "Cadastrar Novo Usuário";
  document.getElementById("usuario-id").value = "";
  document.getElementById("usuario-nome").value = "";
  document.getElementById("usuario-email").value = "";
  document.getElementById("usuario-senha").value = "";
  document.getElementById("usuario-senha").required = true;
  document.getElementById("help-usuario-senha").style.display = "none";
  document.getElementById("usuario-perfil").value = "operador";
  document.getElementById("usuario-ativo").checked = true;

  document.getElementById("modal-usuario").classList.add("open");
}

function editarUsuario(id) {
  const u = usuariosGlobais.find(item => item.id === id);
  if (!u) return;

  document.getElementById("modal-usuario-titulo").innerText = `Editar Usuário: ${u.nome}`;
  document.getElementById("usuario-id").value = u.id;
  document.getElementById("usuario-nome").value = u.nome;
  document.getElementById("usuario-email").value = u.email;
  document.getElementById("usuario-senha").value = "";
  document.getElementById("usuario-senha").required = false;
  document.getElementById("help-usuario-senha").style.display = "block";
  document.getElementById("usuario-perfil").value = u.perfil;
  document.getElementById("usuario-ativo").checked = !!u.ativo;

  document.getElementById("modal-usuario").classList.add("open");
}

function fecharModalUsuario() {
  document.getElementById("modal-usuario").classList.remove("open");
}

async function salvarUsuario(e) {
  e.preventDefault();
  const id = document.getElementById("usuario-id").value;
  const nome = document.getElementById("usuario-nome").value.trim();
  const email = document.getElementById("usuario-email").value.trim();
  const senha = document.getElementById("usuario-senha").value;
  const perfil = document.getElementById("usuario-perfil").value;
  const ativo = document.getElementById("usuario-ativo").checked;

  const btn = document.getElementById("btn-salvar-usuario");
  btn.disabled = true;

  try {
    let res;
    if (id) {
      res = await fetch(`/api/usuarios/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome, email, perfil, ativo, nova_senha: senha || null })
      });
    } else {
      res = await fetch("/api/usuarios", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nome, email, senha, perfil, ativo })
      });
    }

    const dados = await res.json();
    if (!res.ok) throw new Error(dados.detail || "Erro ao salvar usuário.");

    fecharModalUsuario();
    mostrarToast("Usuário salvo com sucesso!", "success");
    carregarUsuarios();
  } catch (err) {
    mostrarToast(err.message, "error");
  } finally {
    btn.disabled = false;
  }
}

async function excluirUsuario(id, nome) {
  if (!confirm(`Deseja realmente remover o usuário "${nome}"?`)) return;

  try {
    const res = await fetch(`/api/usuarios/${id}`, { method: "DELETE" });
    const dados = await res.json();
    if (!res.ok) throw new Error(dados.detail || "Erro ao excluir");

    mostrarToast(`Usuário "${nome}" removido.`, "success");
    carregarUsuarios();
  } catch (err) {
    mostrarToast(err.message, "error");
  }
}

async function resetar2FAUsuario(id, nome) {
  if (!confirm(`Deseja resetar a autenticação 2FA de "${nome}"? O usuário precisará configurar novamente com o Google Authenticator.`)) return;

  try {
    const res = await fetch(`/api/usuarios/${id}/resetar-2fa`, { method: "POST" });
    const dados = await res.json();
    if (!res.ok) throw new Error(dados.detail || "Erro ao resetar 2FA");

    mostrarToast(dados.mensagem, "success");
    carregarUsuarios();
  } catch (err) {
    mostrarToast(err.message, "error");
  }
}

// ==============================================================================
// 4. NAVEGAÇÃO POR ABAS & FILTRO DE MOVIMENTAÇÕES
// ==============================================================================

function trocarAba(nomeAba) {
  document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(content => content.classList.remove("active"));

  const btn = document.getElementById(`tab-btn-${nomeAba}`);
  const aba = document.getElementById(`aba-${nomeAba}`);

  if (btn) btn.classList.add("active");
  if (aba) aba.classList.add("active");

  if (nomeAba === "partes") carregarPartes();
  else if (nomeAba === "movimentacoes") carregarComunicacoes();
  else if (nomeAba === "webhooks") carregarHistoricoWebhooks();
  else if (nomeAba === "tribunais") carregarTribunais();
  else if (nomeAba === "admin") carregarUsuarios();
}

async function carregarMetricas() {
  if (!usuarioLogado) return;
  try {
    const res = await fetch("/api/metricas");
    if (res.status === 401) {
      exibirTelaLogin();
      return;
    }
    if (!res.ok) return;
    const m = await res.json();
    const ePartes = document.getElementById("metrica-total-partes");
    const eAtivas = document.getElementById("metrica-partes-ativas");
    const eComs = document.getElementById("metrica-comunicacoes");
    const eWebhooks = document.getElementById("metrica-webhooks");
    if (ePartes) ePartes.innerText = m.total_partes;
    if (eAtivas) eAtivas.innerText = m.total_partes_ativas;
    if (eComs) eComs.innerText = m.total_comunicacoes;
    if (eWebhooks) eWebhooks.innerText = m.total_webhooks;
  } catch (err) {
    console.error("Erro ao carregar métricas:", err);
  }
}

// --- Gerenciamento de Partes (CRUD) ---
async function carregarPartes() {
  if (!usuarioLogado) return;
  const tbody = document.getElementById("tabela-partes-body");
  const selectFiltro = document.getElementById("filtro-comunicacao-parte");

  try {
    const res = await fetch("/api/partes");
    if (res.status === 401) {
      exibirTelaLogin();
      return;
    }
    partesGlobais = await res.json();

    if (selectFiltro) {
      const valorAtual = selectFiltro.value;
      selectFiltro.innerHTML = `<option value="">Todas as Partes Monitoradas</option>` +
        partesGlobais.map(p => `<option value="${p.id}">${p.nome_parte}</option>`).join("");
      selectFiltro.value = valorAtual;
    }

    if (!partesGlobais || partesGlobais.length === 0) {
      if (tbody) {
        tbody.innerHTML = `
          <tr>
            <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 3rem;">
              Nenhuma parte cadastrada ainda. Clique em <strong>+ Cadastrar Parte</strong> acima para começar.
            </td>
          </tr>
        `;
      }
      return;
    }

    if (tbody) {
      tbody.innerHTML = partesGlobais.map(p => {
        const statusBadge = p.ativo 
          ? `<span class="badge badge-emerald">Ativo</span>`
          : `<span class="badge badge-rose">Pausado</span>`;

        const tribunal = p.sigla_tribunal || `<span style="color: var(--text-muted);">Todos</span>`;
        const prox = p.proxima_consulta ? p.proxima_consulta.replace("T", " ") : "Em breve";
        const periodoBadge = p.data_inicio 
          ? `<div style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 0.2rem;">📅 Desde ${p.data_inicio} até Hoje</div>`
          : `<div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 0.2rem;">📅 Últimos 30 dias</div>`;

        return `
          <tr>
            <td>
              <div style="font-weight: 700; color: #f8fafc;">${p.nome_parte}</div>
              <div style="font-size: 0.75rem; color: var(--text-muted);">ID #${p.id}</div>
              ${periodoBadge}
            </td>
            <td style="max-width: 200px;">
              <div style="font-family: var(--font-mono); font-size: 0.8rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--accent-cyan);" title="${p.webhook_url}">
                ${p.webhook_url}
              </div>
            </td>
            <td>
              <span class="badge badge-indigo" style="font-family: var(--font-mono);">${p.cron_expression}</span>
            </td>
            <td>${tribunal}</td>
            <td>${statusBadge}</td>
            <td style="font-size: 0.85rem; color: var(--text-secondary);">${prox}</td>
            <td>
              <span class="badge badge-amber" style="font-weight: 700;">${p.total_notificacoes}</span>
            </td>
            <td style="text-align: right; white-space: nowrap;">
              <button class="btn btn-secondary btn-sm" onclick="consultarParteAgora(${p.id}, 30)" title="Consultar últimos 30 dias no PJe">
                🔍 30 Dias
              </button>
              <button class="btn btn-secondary btn-sm" onclick="consultarParteAgora(${p.id}, 0)" title="Carga Histórica Completa (sem limite de 30 dias)">
                📚 Histórico
              </button>
              <button class="btn btn-secondary btn-sm" onclick="testarWebhook(${p.id})" title="Testar endpoint de webhook">
                ⚡ Testar
              </button>
              <button class="btn btn-secondary btn-sm" onclick="editarParte(${p.id})" title="Editar parte">
                ✏️
              </button>
              <button class="btn btn-danger btn-sm" onclick="excluirParte(${p.id}, '${p.nome_parte}')" title="Excluir">
                🗑️
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }

  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="8" style="color: var(--accent-rose); text-align: center;">Erro ao carregar partes.</td></tr>`;
  }
}

function abrirModalNovaParte() {
  document.getElementById("modal-parte-titulo").innerText = "Cadastrar Nova Parte";
  document.getElementById("parte-id").value = "";
  document.getElementById("parte-nome").value = "";
  document.getElementById("parte-webhook").value = "";
  document.getElementById("parte-cron").value = "0 */2 * * *";
  document.getElementById("parte-tribunal").value = "";
  document.getElementById("parte-data-inicio").value = "";
  document.getElementById("parte-ativo").checked = true;
  document.getElementById("modal-parte").classList.add("open");
}

function editarParte(id) {
  const p = partesGlobais.find(item => item.id === id);
  if (!p) return;

  document.getElementById("modal-parte-titulo").innerText = "Editar Parte";
  document.getElementById("parte-id").value = p.id;
  document.getElementById("parte-nome").value = p.nome_parte;
  document.getElementById("parte-webhook").value = p.webhook_url;
  document.getElementById("parte-cron").value = p.cron_expression || "0 */2 * * *";
  document.getElementById("parte-tribunal").value = p.sigla_tribunal || "";
  document.getElementById("parte-data-inicio").value = p.data_inicio || "";
  document.getElementById("parte-ativo").checked = !!p.ativo;

  document.getElementById("modal-parte").classList.add("open");
}

function fecharModalParte() {
  document.getElementById("modal-parte").classList.remove("open");
}

function definirCron(expr) {
  document.getElementById("parte-cron").value = expr;
}

async function salvarParte(e) {
  e.preventDefault();
  const id = document.getElementById("parte-id").value;
  const payload = {
    nome_parte: document.getElementById("parte-nome").value.trim(),
    webhook_url: document.getElementById("parte-webhook").value.trim(),
    cron_expression: document.getElementById("parte-cron").value.trim(),
    sigla_tribunal: document.getElementById("parte-tribunal").value.trim() || null,
    data_inicio: document.getElementById("parte-data-inicio").value || null,
    ativo: document.getElementById("parte-ativo").checked
  };

  const btn = document.getElementById("btn-salvar-parte");
  btn.disabled = true;
  btn.innerText = "Salvando...";

  try {
    let res;
    if (id) {
      res = await fetch(`/api/partes/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    } else {
      res = await fetch("/api/partes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erro ao salvar parte");
    }

    fecharModalParte();
    mostrarToast("Parte salva com sucesso!", "success");
    carregarPartes();
    carregarMetricas();
  } catch (err) {
    mostrarToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "Salvar Parte";
  }
}

async function excluirParte(id, nome) {
  if (!confirm(`Tem certeza que deseja excluir o monitoramento de "${nome}"?`)) return;

  try {
    const res = await fetch(`/api/partes/${id}`, { method: "DELETE" });
    if (res.ok) {
      mostrarToast(`Parte "${nome}" removida.`, "success");
      carregarPartes();
      carregarMetricas();
    } else {
      mostrarToast("Erro ao excluir parte.", "error");
    }
  } catch (err) {
    mostrarToast("Erro na requisição.", "error");
  }
}

// Consultas Imediatas
async function consultarParteAgora(id, dias = 30) {
  const rotulo = dias === 0 ? "histórico completo" : `últimos ${dias} dias`;
  mostrarToast(`Iniciando consulta (${rotulo})...`, "info");
  try {
    const res = await fetch(`/api/partes/${id}/consultar?dias=${dias}`, { method: "POST" });
    const dados = await res.json();

    if (dados.novas_atualizacoes > 0) {
      mostrarToast(`Detectadas ${dados.novas_atualizacoes} novidade(s)! Webhook disparado.`, "success");
    } else {
      mostrarToast("Consulta concluída. Nenhuma alteração no estado (sem disparo desnecessário).", "info");
    }

    carregarPartes();
    carregarMetricas();
    carregarComunicacoes();
  } catch (err) {
    mostrarToast("Erro ao executar consulta.", "error");
  }
}

async function executarVarreduraGeral() {
  const btn = document.getElementById("btn-varredura-geral");
  btn.disabled = true;
  btn.innerText = "⚡ Varrendo...";
  mostrarToast("Executando varredura em todas as partes ativas...", "info");

  try {
    const res = await fetch("/api/consultar-todas", { method: "POST" });
    const dados = await res.json();
    mostrarToast(dados.mensagem, "success");
    carregarPartes();
    carregarMetricas();
  } catch (err) {
    mostrarToast("Erro ao executar varredura geral.", "error");
  } finally {
    btn.disabled = false;
    btn.innerText = "⚡ Varredura Geral";
  }
}

// Teste de Webhook
async function testarWebhook(id) {
  const modal = document.getElementById("modal-teste-webhook");
  const container = document.getElementById("teste-webhook-conteudo");
  container.innerHTML = `<p style="color: var(--accent-cyan);">Enviando payload de teste para o Webhook...</p>`;
  modal.classList.add("open");

  try {
    const res = await fetch(`/api/partes/${id}/testar-webhook`, { method: "POST" });
    const dados = await res.json();

    if (dados.sucesso) {
      container.innerHTML = `
        <div style="background: rgba(16, 185, 129, 0.15); border: 1px solid var(--accent-emerald); border-radius: var(--radius-sm); padding: 1rem; margin-bottom: 1rem;">
          <h4 style="color: var(--accent-emerald); margin-bottom: 0.35rem;">✓ Webhook Respondeu com Sucesso!</h4>
          <p style="font-size: 0.85rem;">Status HTTP: <strong>${dados.status_code}</strong></p>
        </div>
        <p class="form-label">Resposta retornada pelo endpoint:</p>
        <div class="code-preview">${dados.resposta || "Sem corpo de resposta"}</div>
      `;
    } else {
      container.innerHTML = `
        <div style="background: rgba(244, 63, 94, 0.15); border: 1px solid var(--accent-rose); border-radius: var(--radius-sm); padding: 1rem; margin-bottom: 1rem;">
          <h4 style="color: var(--accent-rose); margin-bottom: 0.35rem;">✕ Falha na Conexão do Webhook</h4>
          <p style="font-size: 0.85rem;">Status HTTP: <strong>${dados.status_code || "Erro de Conexão"}</strong></p>
        </div>
        <p class="form-label">Detalhes do erro:</p>
        <div class="code-preview">${dados.resposta}</div>
      `;
    }
  } catch (err) {
    container.innerHTML = `<p style="color: var(--accent-rose);">Erro ao disparar teste: ${err.message}</p>`;
  }
}

function fecharModalTesteWebhook() {
  document.getElementById("modal-teste-webhook").classList.remove("open");
}

// ==============================================================================
// 5. MOVIMENTAÇÕES PROCESSUAIS COM FILTRO POR PARTE
// ==============================================================================

async function carregarComunicacoes() {
  if (!usuarioLogado) return;
  const container = document.getElementById("comunicacoes-feed");
  const selectParte = document.getElementById("filtro-comunicacao-parte");
  const parteId = selectParte ? selectParte.value : "";

  let url = "/api/comunicacoes?limite=100";
  if (parteId) {
    url += `&parte_id=${parteId}`;
  }

  try {
    const res = await fetch(url);
    comunicacoesCarregadas = await res.json();
    renderizarCardsComunicacoes(comunicacoesCarregadas);
  } catch (err) {
    if (container) container.innerHTML = `<p style="color: var(--accent-rose); text-align: center;">Erro ao carregar movimentações.</p>`;
  }
}

function renderizarCardsComunicacoes(lista) {
  const container = document.getElementById("comunicacoes-feed");
  if (!container) return;

  if (!lista || lista.length === 0) {
    container.innerHTML = `
      <p style="color: var(--text-muted); text-align: center; padding: 3rem;">
        Nenhuma movimentação encontrada para o filtro selecionado.
      </p>
    `;
    return;
  }

  container.innerHTML = lista.map(c => {
    const dataDisp = c.data_disponibilizacao || "Recentemente";
    const certidaoBtn = c.hash 
      ? `<a href="/api/comunicacoes/${c.hash}/certidao" target="_blank" class="btn btn-secondary btn-sm" style="color: var(--accent-cyan);">📥 Baixar Certidão PDF</a>`
      : "";

    return `
      <div class="comunicacao-card">
        <div class="comunicacao-header">
          <div>
            <span class="process-number">${c.numero_processo || "Processo Sem Número"}</span>
            <span class="badge badge-indigo" style="margin-left: 0.5rem;">[${c.sigla_tribunal || 'PJe'}]</span>
            <span class="badge badge-cyan" style="margin-left: 0.25rem;">${c.tipo_comunicacao || 'Intimação'}</span>
          </div>
          <div>${certidaoBtn}</div>
        </div>

        <div class="comunicacao-meta">
          <span><strong>Parte:</strong> ${c.nome_parte}</span>
          <span><strong>Disponibilização:</strong> ${dataDisp}</span>
          <span><strong>Capturado em:</strong> ${c.capturado_em}</span>
        </div>

        <div class="comunicacao-texto">
          ${c.texto_resumo || "Sem resumo disponível."}
        </div>
      </div>
    `;
  }).join("");
}

function filtrarCardsComunicacoesLocalmente() {
  const termo = document.getElementById("filtro-comunicacao-busca").value.toLowerCase().trim();
  if (!termo) {
    renderizarCardsComunicacoes(comunicacoesCarregadas);
    return;
  }

  const filtrados = comunicacoesCarregadas.filter(c => {
    const proc = (c.numero_processo || "").toLowerCase();
    const tribunal = (c.sigla_tribunal || "").toLowerCase();
    const texto = (c.texto_resumo || "").toLowerCase();
    const parte = (c.nome_parte || "").toLowerCase();
    return proc.includes(termo) || tribunal.includes(termo) || texto.includes(termo) || parte.includes(termo);
  });

  renderizarCardsComunicacoes(filtrados);
}

function limparFiltrosComunicacoes() {
  document.getElementById("filtro-comunicacao-parte").value = "";
  document.getElementById("filtro-comunicacao-busca").value = "";
  carregarComunicacoes();
}

// --- Histórico de Webhooks ---
async function carregarHistoricoWebhooks() {
  if (!usuarioLogado) return;
  const tbody = document.getElementById("tabela-webhooks-body");
  try {
    const res = await fetch("/api/webhooks/historico?limite=50");
    const logs = await res.json();

    if (!logs || logs.length === 0) {
      if (tbody) {
        tbody.innerHTML = `
          <tr>
            <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 2.5rem;">
              Nenhum disparo de webhook registrado ainda.
            </td>
          </tr>
        `;
      }
      return;
    }

    if (tbody) {
      tbody.innerHTML = logs.map(l => {
        const statusBadge = l.sucesso 
          ? `<span class="badge badge-emerald">HTTP ${l.status_code} Sucesso</span>`
          : `<span class="badge badge-rose">HTTP ${l.status_code || 0} Falha</span>`;

        return `
          <tr>
            <td style="font-size: 0.85rem; color: var(--text-secondary);">${l.enviado_em}</td>
            <td style="font-weight: 600;">${l.nome_parte || 'Parte #' + l.parte_id}</td>
            <td style="font-family: var(--font-mono); font-size: 0.85rem; color: var(--accent-cyan);">${l.numero_processo || '-'}</td>
            <td style="font-family: var(--font-mono); font-size: 0.75rem; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${l.webhook_url}">
              ${l.webhook_url}
            </td>
            <td>${statusBadge}</td>
            <td style="font-size: 0.8rem; color: var(--text-muted); max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              ${l.resposta || '-'}
            </td>
            <td style="text-align: right;">
              <button class="btn btn-secondary btn-sm" onclick="alert('Payload:\\n' + JSON.stringify(JSON.parse('${l.payload.replace(/'/g, "\\'")}'), null, 2))">
                👁️ Payload
              </button>
            </td>
          </tr>
        `;
      }).join("");
    }

  } catch (err) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="7" style="color: var(--accent-rose); text-align: center;">Erro ao carregar histórico.</td></tr>`;
  }
}

// --- Tribunais Integrados ---
async function carregarTribunais() {
  if (!usuarioLogado) return;
  const container = document.getElementById("tribunais-container");
  try {
    const res = await fetch("/api/tribunais");
    const estados = await res.json();

    if (container) {
      container.innerHTML = estados.map(e => {
        const siglas = e.instituicoes.map(i => `<span class="badge badge-indigo" style="margin: 0.2rem;">${i.sigla}</span>`).join(" ");
        const uf = e.uf || "BR";

        return `
          <div class="metric-card" style="display: block;">
            <div style="font-weight: 700; color: var(--accent-cyan); margin-bottom: 0.5rem;">
              ${uf} - ${e.nomeEstado}
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 0.25rem;">
              ${siglas}
            </div>
          </div>
        `;
      }).join("");
    }
  } catch (err) {
    if (container) container.innerHTML = `<p style="color: var(--accent-rose);">Erro ao listar tribunais.</p>`;
  }
}
