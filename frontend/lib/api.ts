import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) window.location.href = "/login";
    return Promise.reject(err);
  }
);

export const getDashboardStats  = () => api.get("/dashboard/stats").then((r) => r.data);
export const getWeekSchedule    = () => api.get("/week-schedule").then((r) => r.data);
export const getGrowthSummary   = () => api.get("/growth/summary").then((r) => r.data);
export const getAnalyticsSummary= () => api.get("/analytics/summary").then((r) => r.data);

// AI Keys
export const getAIKeys        = () => api.get("/ai-keys").then((r) => r.data);
export const saveAIKey        = (provider: string, api_key: string) =>
  api.post("/ai-keys", { provider, api_key }).then((r) => r.data);
export const deleteAIKey      = (provider: string) =>
  api.delete(`/ai-keys/${provider}`).then((r) => r.data);
export const toggleAIKey      = (provider: string) =>
  api.post(`/ai-keys/${provider}/toggle`).then((r) => r.data);
export const setDefaultAIKey  = (provider: string) =>
  api.post(`/ai-keys/${provider}/set-default`).then((r) => r.data);
export const testAIKey        = (provider: string) =>
  api.post(`/ai-keys/${provider}/test`).then((r) => r.data);
