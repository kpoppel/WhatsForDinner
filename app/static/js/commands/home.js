import { api } from "../api.js";

export async function requestHomeData(path, options) {
  return await api(path, options);
}