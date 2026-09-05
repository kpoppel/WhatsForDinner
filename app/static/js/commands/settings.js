import { api } from "../api.js";

export async function requestSettings(path, options) {
  return await api(path, options);
}