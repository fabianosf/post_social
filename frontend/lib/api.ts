import axios from "axios";

export const api = axios.create({
  baseURL: "/api",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
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

// Communities — Fase 1/2/3
export const detectNiche            = () => api.post("/communities/detect-niche").then((r) => r.data);
export const saveCommunityKeywords  = (keywords: string[]) => api.post("/communities/keywords", { keywords }).then((r) => r.data);
export const getCommunityRecs       = (params?: { niche?: string; city?: string; platform?: string; category?: string; limit?: number }) =>
  api.get("/communities/recommendations", { params }).then((r) => r.data);
export const getCommunityNiches     = () => api.get("/communities/niches").then((r) => r.data);
export const getCommunityNiche      = (id: number) => api.get(`/communities/${id}/rules`).then((r) => r.data);
export const suggestContent         = (id: number) => api.get(`/communities/${id}/suggest-content`).then((r) => r.data);
export const adaptCaption           = (id: number, caption: string) => api.post(`/communities/${id}/adapt-caption`, { caption }).then((r) => r.data);
export const getGrowthTips          = (id: number, niche?: string) => api.get(`/communities/${id}/growth-tips`, { params: { niche } }).then((r) => r.data);

// Growth Intelligence — Fase 4
export const getCompetitors         = () => api.get("/growth-intel/competitors").then((r) => r.data);
export const addCompetitor          = (data: { name: string; niche?: string; ig_username?: string; website_url?: string; notes?: string }) =>
  api.post("/growth-intel/competitors", data).then((r) => r.data);
export const deleteCompetitor       = (id: number) => api.delete(`/growth-intel/competitors/${id}`).then((r) => r.data);
export const getNicheTrends         = (niche?: string) => api.get("/growth-intel/trends", { params: { niche } }).then((r) => r.data);
export const getGrowthOpportunities = () => api.get("/growth-intel/opportunities").then((r) => r.data);
export const getCompetitiveScore    = (niche?: string, city?: string) => api.get("/growth-intel/competitive-score", { params: { niche, city } }).then((r) => r.data);
export const getCompetitiveAnalysis = () => api.get("/growth-intel/analysis").then((r) => r.data);
