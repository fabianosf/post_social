import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { DashboardStats } from "@/types/dashboard";
import { CheckCircle2, Clock, AlertCircle, Send, Layers, Loader2 } from "lucide-react";

const CARDS = [
  { key: "total",      label: "Total",        icon: Layers,       color: "text-muted-foreground" },
  { key: "posted",     label: "Publicados",   icon: CheckCircle2, color: "text-accent" },
  { key: "scheduled",  label: "Agendados",    icon: Clock,        color: "text-primary" },
  { key: "queued",     label: "Na fila",      icon: Send,         color: "text-yellow-400" },
  { key: "processing", label: "Processando",  icon: Loader2,      color: "text-blue-400" },
  { key: "failed",     label: "Falharam",     icon: AlertCircle,  color: "text-destructive" },
] as const;

const EMPTY_STATS: DashboardStats = {
  total: 0,
  posted: 0,
  queued: 0,
  scheduled: 0,
  failed: 0,
  processing: 0,
};

export function StatsCards({ data }: { data?: Partial<DashboardStats> | null }) {
  const safe =
    data && typeof data === "object" && !Array.isArray(data)
      ? { ...EMPTY_STATS, ...data }
      : EMPTY_STATS;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {CARDS.map(({ key, label, icon: Icon, color }) => (
        <Card key={key} className="flex flex-col gap-1 p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{label}</span>
            <Icon size={15} className={color} />
          </div>
          <span className="text-2xl font-bold">{safe[key]}</span>
        </Card>
      ))}
    </div>
  );
}

export function StatsCardsSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i} className="p-4">
          <Skeleton className="mb-2 h-3 w-16" />
          <Skeleton className="h-7 w-10" />
        </Card>
      ))}
    </div>
  );
}
