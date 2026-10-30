// Dang nhap: lay cau hinh, user hien tai, man hinh dang nhap, nut dang xuat.
import { api, getToken, setToken } from "./api.js";
import { LEVEL_LABELS, ROLE_LABELS, escapeHtml } from "./format.js";

export async function getAuthConfig() {
  return api("/api/auth/config").catch(() => ({ auth_mode: "off", dev_login: false }));
}

/** Tra ve thong tin user, hoac null neu can dang nhap. */
export async function fetchMe(config) {
  if (config.auth_mode !== "jwt") {
    return api("/api/me").catch(() => ({ kind: "anonymous", unrestricted: true, locations: null }));
  }
  if (!getToken()) return null;
  try {
    return await api("/api/me");
  } catch (error) {
    setToken(null);
    return null;
  }
}

export function renderUserChip(container, me, config) {
  if (config.auth_mode !== "jwt") {
    container.innerHTML = `<span class="user-chip" title="AUTH_MODE=off">Không bật đăng nhập</span>`;
    return;
  }
  const name = me.full_name || me.email || me.user_id;
  const role = ROLE_LABELS[me.role] || me.role || "";
  const places = (me.locations || []).map((loc) => `${loc.name}: ${LEVEL_LABELS[loc.level] || loc.level}`).join("\n");
  container.innerHTML = `
    <span class="user-chip" title="${escapeHtml(places || "Chưa được giao khu vực nào")}">
      <span class="user-name">${escapeHtml(name)}</span>
      <span class="user-role">${escapeHtml(role)}</span>
    </span>
    <button type="button" class="ghost small" data-logout>Đăng xuất</button>`;
  container.querySelector("[data-logout]").addEventListener("click", () => {
    setToken(null);
    window.location.reload();
  });
}

export async function renderLoginScreen(container, config) {
  const users = config.dev_login ? await api("/api/auth/dev-users").catch(() => []) : [];
  container.innerHTML = `
    <section class="login">
      <h1>Đăng nhập</h1>
      <p class="muted">Mỗi tài khoản chỉ thấy camera của khu vực được giao.</p>
      ${
        users.length
          ? `<label class="field">
               <span>Tài khoản demo</span>
               <select id="loginUser">
                 ${users
                   .map((u) => `<option value="${escapeHtml(u.email)}">${escapeHtml(u.email)} (${escapeHtml(ROLE_LABELS[u.role] || u.role)})</option>`)
                   .join("")}
               </select>
             </label>
             <button type="button" class="primary" id="loginDemo">Đăng nhập</button>
             <p class="divider-text">hoặc</p>`
          : ""
      }
      <label class="field">
        <span>Token do Backend cấp</span>
        <input id="loginToken" type="password" autocomplete="off" placeholder="Dán JWT vào đây">
      </label>
      <button type="button" class="${users.length ? "" : "primary"}" id="loginWithToken">Dùng token này</button>
      <p class="form-error" id="loginError" hidden></p>
    </section>`;
  const error = container.querySelector("#loginError");
  const fail = (message) => {
    error.hidden = false;
    error.textContent = message;
  };
  container.querySelector("#loginDemo")?.addEventListener("click", async () => {
    try {
      const email = container.querySelector("#loginUser").value;
      const result = await api("/api/auth/dev-login", { method: "POST", body: JSON.stringify({ email }) });
      setToken(result.access_token);
      window.location.reload();
    } catch (err) {
      fail(`Không đăng nhập được: ${err.message}`);
    }
  });
  container.querySelector("#loginWithToken").addEventListener("click", () => {
    const token = container.querySelector("#loginToken").value.trim();
    if (!token) {
      fail("Chưa có token. Dán token do Backend cấp vào ô trên.");
      return;
    }
    setToken(token);
    window.location.reload();
  });
}
