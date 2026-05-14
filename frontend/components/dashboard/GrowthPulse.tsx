import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp } from "lucide-react";
import type { GrowthSummary } from "@/types/dashboard";

const scoreColor = (s: number) =>
  s >= 70 ? "text-accent" : s >= 40 ? "text-yellow-400" : "text-destructive";

export function GrowthPulse({ data }: { data: GrowthSummary }) {
  if (!data || typeof data !== "object") return null;
  const { score = 0, label = "—" } = data.growth_score ?? {};
  const { total_reach = 0, reach_delta_pct = 0 } = data.kpis ?? {};
  const delta = reach_delta_pct ?? 0;

  return (
    <Card className="flex flex-wrap items-center gap-4 px-5 py-3">
      <div className="flex items-center gap-3">
        <TrendingUp size={18} className="text-primary" />
        <span className="text-sm font-medium text-muted-foreground">Growth</span>
        <span className={`text-2xl font-bold ${scoreColor(score)}`}>{score}</span>
        <Badge variant="outline" className="text-xs">{label}</Badge>
      </div>

      <div className="flex items-center gap-1 text-sm text-muted-foreground">
        Alcance:
        <span className="ml-1 font-medium text-foreground">{total_reach.toLocaleString("pt-BR")}</span>
        <span className={`ml-1 text-xs ${delta >= 0 ? "text-accent" : "text-destructive"}`}>
          {delta >= 0 ? "▲" : "▼"} {Math.abs(delta)}%
        </span>
      </div>

      {data.best_format && (
        <div className="text-sm text-muted-foreground">
          Melhor formato: <span className="font-medium text-foreground">{data.best_format}</span>
        </div>
      )}

      <a href="/growth" className="ml-auto text-xs text-primary hover:underline">
        Ver crescimento →
      </a>
    </Card>
  );
}

export function GrowthPulseSkeleton() {
  return (
    <Card className="flex items-center gap-4 px-5 py-3">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-6 w-12" />
      <Skeleton className="h-4 w-32" />
    </Card>
  );
}
