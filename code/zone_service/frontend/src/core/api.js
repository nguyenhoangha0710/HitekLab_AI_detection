// Goi API Zone Service, tu gan token dang nhap (JWT) neu co.
const TOKEN_KEY = "hitek_access_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (error) {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (error) {
    // trinh duyet chan storage: token chi song trong phien nay
  }
  memoryToken = token || null;
}

let memoryToken = null;

function currentToken() {
  return getToken() || memoryToken;
}

// <img>, <video>, EventSource khong gui duoc header Authorization -> gan ?access_token=
export function withToken(url) {
  const token = currentToken();
  if (!token || !url) return url;
  return `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(token)}`;
}

export async function api(path, options = {}) {
  const token = currentToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("auth-required"));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return null;
  return response.json();
}
