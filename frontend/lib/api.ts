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
