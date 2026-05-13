"use client";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getNicheTrends, getGrowthOpportunities, getCompetitiveScore } from "@/lib/api";
import { TrendingUp, Zap, AlertTriangle } from "lucide-react";

const OPPORTUNITY_COLOR: Record<string, string> = {
  alta:  "bg-green-500/10 text-green-400",
  média: "bg-yellow-500/10 text-yellow-400",
  baixa: "bg-red-500/10 text-red-400",
};

export function TrendsPanel({ niche }: { niche?: string }) {
  const trends = useQuery({ queryKey: ["niche-trends", niche], queryFn: () => getNicheTrends(niche), staleTime: 3_600_000 });
  const opps   = useQuery({ queryKey: ["growth-opps"],          queryFn: getGrowthOpportunities,    staleTime: 1_800_000 });
  const score  = useQuery({ queryKey: ["competitive-score", niche], queryFn: () => getCompetitiveScore(niche), staleTime: 1_800_000 });

  return (
    <div className="space-y-4">
      {/* Score Competitivo */}
      <Card className="p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Zap size={15} className="text-primary" />
          Score competitivo
        </h3>
        {score.isLoading ? (
          <div className="flex gap-3">
            <Skeleton className="h-12 w-24 rounded-lg" />
            <Skeleton className="h-12 w-24 rounded-lg" />
          </div>
        ) : score.data ? (
          <div className="flex flex-wrap gap-3">
            <div className="rounded-lg bg-secondary p-3 text-center">
              <p className="text-xs text-muted-foreground">Oportunidade</p>
              <Badge className={`mt-1 ${OPPORTUNITY_COLOR[score.data.opportunity] ?? ""}`}>
                {score.data.opportunity}
              </Badge>
            </div>
            <div className="rounded-lg bg-secondary p-3 text-center">
              <p className="text-xs text-muted-foreground">Saturação</p>
              <Badge className={`mt-1 ${OPPORTUNITY_COLOR[score.data.saturation === "baixa" ? "alta" : score.data.saturation === "alta" ? "baixa" : "média"] ?? ""}`}>
                {score.data.saturation}
              </Badge>
            </div>
            <div className="rounded-lg bg-secondary p-3 text-center">
              <p className="text-xs text-muted-foreground">Comunidades</p>
              <p className="mt-1 text-lg font-bold">{score.data.total_communities}</p>
            </div>
          </div>
        ) : null}
      </Card>

      {/* Tendências do nicho */}
      <Card className="p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <TrendingUp size={15} className="text-primary" />
          Tendências — {niche ?? "seu nicho"}
        </h3>
        {trends.isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-3 w-full" />)}
          </div>
        ) : trends.data ? (
          <div className="space-y-4">
            {trends.data.trends?.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">Em alta</p>
                <div className="flex flex-wrap gap-2">
                  {trends.data.trends.map((t: string, i: number) => (
                    <Badge key={i} variant="secondary">{t}</Badge>
                  ))}
                </div>
              </div>
            )}
            {trends.data.rising_topics?.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">Emergentes</p>
                <div className="flex flex-wrap gap-2">
                  {trends.data.rising_topics.map((t: string, i: number) => (
                    <Badge key={i} className="bg-primary/10 text-primary">{t}</Badge>
                  ))}
                </div>
              </div>
            )}
            {trends.data.content_opportunities?.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wide">Oportunidades de conteúdo</p>
                <ul className="space-y-1">
                  {trends.data.content_opportunities.map((t: string, i: number) => (
                    <li key={i} className="text-sm text-muted-foreground">• {t}</li>
                  ))}
                </ul>
              </div>
            )}
            {trends.data.tip && (
              <div className="rounded-md border border-primary/20 bg-primary/5 p-3 text-sm">
                <p className="font-medium text-primary">Dica</p>
                <p className="mt-0.5 text-muted-foreground">{trends.data.tip}</p>
              </div>
            )}
          </div>
        ) : null}
      </Card>

      {/* Oportunidades */}
      {opps.data?.adjacent_niches?.length > 0 && (
        <Card className="p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <AlertTriangle size={15} className="text-yellow-400" />
            Nichos adjacentes com menor concorrência
          </h3>
          <div className="flex flex-wrap gap-2">
            {opps.data.adjacent_niches.map((n: { niche: string; community_count: number }) => (
              <div key={n.niche} className="rounded-lg bg-secondary px-3 py-2 text-center">
                <p className="text-sm font-medium">{n.niche}</p>
                <p className="text-xs text-muted-foreground">{n.community_count} comunidades</p>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
