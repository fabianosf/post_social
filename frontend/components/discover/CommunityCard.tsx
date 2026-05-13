"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { adaptCaption, getGrowthTips, suggestContent } from "@/lib/api";
import { ExternalLink, Sparkles, ChevronDown, ChevronUp, Users } from "lucide-react";

const PLATFORM_COLOR: Record<string, string> = {
  telegram: "bg-blue-500/10 text-blue-400",
  reddit:   "bg-orange-500/10 text-orange-400",
  discord:  "bg-violet-500/10 text-violet-400",
  whatsapp: "bg-green-500/10 text-green-400",
};

export type Community = {
  id: number;
  platform: string;
  name: string;
  description?: string;
  url?: string;
  niche?: string;
  city?: string;
  member_count?: number;
  engagement_score?: number;
  verified?: boolean;
  tags?: string[];
  score?: number;
};

export function CommunityCard({ c }: { c: Community }) {
  const [expanded, setExpanded] = useState(false);
  const [tips, setTips]         = useState<string[] | null>(null);
  const [content, setContent]   = useState<string[] | null>(null);

  const tipsMut = useMutation({
    mutationFn: () => getGrowthTips(c.id),
    onSuccess: (d) => setTips(d.tips ?? []),
  });

  const contentMut = useMutation({
    mutationFn: () => suggestContent(c.id),
    onSuccess: (d) => setContent(d.tips ?? d.formats ?? []),
  });

  const platformClass = PLATFORM_COLOR[c.platform] ?? "bg-muted text-muted-foreground";

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={`text-xs ${platformClass}`}>{c.platform}</Badge>
            {c.verified && <Badge className="bg-accent/10 text-accent text-xs">Verificada</Badge>}
            {c.score !== undefined && (
              <span className="text-xs text-muted-foreground">score {c.score}</span>
            )}
          </div>
          <p className="mt-1 truncate font-medium">{c.name}</p>
          {c.description && (
            <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{c.description}</p>
          )}
        </div>
        {c.url && (
          <a href={c.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-muted-foreground hover:text-foreground">
            <ExternalLink size={15} />
          </a>
        )}
      </div>

      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
        {c.member_count ? (
          <span className="flex items-center gap-1"><Users size={11} />{c.member_count.toLocaleString("pt-BR")}</span>
        ) : null}
        {c.city && <span>{c.city}</span>}
        {c.niche && <span className="rounded bg-secondary px-1.5 py-0.5">{c.niche}</span>}
        {c.tags?.map((t) => (
          <span key={t} className="rounded bg-secondary px-1.5 py-0.5">{t}</span>
        ))}
      </div>

      <div className="flex gap-2">
        <Button
          size="sm"
          variant="ghost"
          className="h-7 gap-1 text-xs"
          onClick={() => { setExpanded(!expanded); if (!tips) tipsMut.mutate(); }}
        >
          <Sparkles size={12} />
          Growth tips
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 gap-1 text-xs"
          onClick={() => { setExpanded(!expanded); if (!content) contentMut.mutate(); }}
        >
          Conteúdo ideal
        </Button>
      </div>

      {expanded && (
        <div className="space-y-2 rounded-md bg-secondary/50 p-3 text-xs">
          {(tipsMut.isPending || contentMut.isPending) && (
            <div className="space-y-1.5">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          )}
          {tips && tips.map((t, i) => <p key={i} className="text-muted-foreground">• {t}</p>)}
          {content && content.map((t, i) => <p key={i} className="text-muted-foreground">• {t}</p>)}
        </div>
      )}
    </Card>
  );
}

export function CommunityCardSkeleton() {
  return (
    <Card className="p-4">
      <Skeleton className="mb-2 h-3 w-16" />
      <Skeleton className="mb-1 h-4 w-2/3" />
      <Skeleton className="h-3 w-full" />
    </Card>
  );
}
