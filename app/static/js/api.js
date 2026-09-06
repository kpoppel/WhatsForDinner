const apiPrefix = window.WFD_API_PREFIX;

export async function api(path, options = {}) {
  const response = await fetch(`${apiPrefix}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    if (typeof data.detail === "string") {
      throw new Error(data.detail);
    }
    throw new Error(JSON.stringify(data));
  }
  return data;
}

export async function apiUpload(path, formData) {
  const response = await fetch(`${apiPrefix}${path}`, {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) {
    if (typeof data.detail === "string") {
      throw new Error(data.detail);
    }
    throw new Error(JSON.stringify(data));
  }
  return data;
}

export async function health() {
  return await api("/health", { cache: "no-store", signal: AbortSignal.timeout(5000) });
}
