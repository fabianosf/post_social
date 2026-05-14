export interface DashboardStats {
  total: number;
  posted: number;
  queued: number;
  scheduled: number;
  failed: number;
  processing: number;
}

export interface QueuePost {
  id: number;
  filename: string;
  time: string;
  status: "pending" | "posted" | "processing" | "failed";
  ig: boolean;
  fb: boolean;
  thumb_url: string;
  is_video: boolean;
}

export interface WeekDay {
  date: string;
  weekday: number;
  day_name: string;
  day_short: string;
  posts: QueuePost[];
  ig_count: number;
  fb_count: number;
  max: number;
  is_today: boolean;
  is_past: boolean;
}

export interface GrowthSummary {
  growth_score?: { score: number; label: string; components: Record<string, number> } | null;
  kpis?: {
    posts_published: number;
    total_reach: number;
    total_likes: number;
    total_saves: number;
    avg_post_score: number;
    reach_delta_pct: number;
    likes_delta_pct: number;
    saves_delta_pct: number;
  } | null;
  best_format: string;
  trends: Array<{ metric: string; direction: string; insight: string }>;
}
