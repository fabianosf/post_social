"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { getCompetitors, addCompetitor, deleteCompetitor, getCompetitiveAnalysis } from "@/lib/api";
import { Trash2, Plus, Sparkles, Brain } from "lucide-react";

type Competitor = {
  id: number;
  name: string;
  niche?: string;
  ig_username?: string;
  website_url?: string;
};

type Analysis = {
  insights?: string[];
  strategy?: string;
  differentiation?: string[];
  community_types?: string[];
};

export function CompetitorPanel() {
  const qc = useQueryClient();
  const [name, setName]     = useState("");
  const [niche, setNiche]   = useState("");
  const [ig, setIg]         = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);

  const comps   = useQuery({ queryKey: ["competitors"], queryFn: getCompetitors });
  const addMut  = useMutation({
    mutationFn: () => addCompetitor({ name, niche: niche || undefined, ig_username: ig || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["competitors"] }); setName(""); setNiche(""); setIg(""); },
  });
  const delMut  = useMutation({
    mutationFn: (id: number) => deleteCompetitor(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["competitors"] }),
  });
  const analysisMut = useMutation({
    mutationFn: getCompetitiveAnalysis,
    onSuccess: setAnalysis,
  });

  return (
    <div className="space-y-4">
      {/* Adicionar concorrente */}
      <Card className="p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Plus size={15} className="text-primary" />
          Adicionar concorrente
        </h3>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input placeholder="Nome ou marca*" value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-sm" />
          <Input placeholder="Nicho" value={niche} onChange={(e) => setNiche(e.target.value)} className="h-8 text-sm" />
          <Input placeholder="@instagram" value={ig} onChange={(e) => setIg(e.target.value)} className="h-8 text-sm" />
          <Button
            size="sm"
            className="h-8 shrink-0"
            disabled={!name || addMut.isPending}
            onClick={() => addMut.mutate()}
          >
            {addMut.isPending ? "Salvando…" : "Adicionar"}
          </Button>
        </div>
      </Card>

      {/* Lista de concorrentes */}
      <Card className="p-4">
        <h3 className="mb-3 text-sm font-medium">Seus concorrentes</h3>
        {comps.isLoading ? (
          <div className="space-y-2">{[1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : Array.isArray(comps.data) && comps.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhum concorrente cadastrado.</p>
        ) : (
          <ul className="space-y-2">
            {(Array.isArray(comps.data) ? comps.data : []).map((c: Competitor) => (
              <li key={c.id} className="flex items-center justify-between rounded-md bg-secondary px-3 py-2">
                <div>
                  <p className="text-sm font-medium">{c.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {[c.niche, c.ig_username ? `@${c.ig_username}` : null].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                  onClick={() => delMut.mutate(c.id)}
                >
                  <Trash2 size={13} />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Análise IA */}
      <Card className="p-4">
        <div className="flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Brain size={15} className="text-primary" />
            Análise estratégica por IA
          </h3>
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-1 text-xs"
            disabled={analysisMut.isPending}
            onClick={() => analysisMut.mutate()}
          >
            <Sparkles size={12} />
            {analysisMut.isPending ? "Analisando…" : "Analisar"}
          </Button>
        </div>

        {analysis && (
          <div className="mt-3 space-y-3 text-sm">
            {analysis.strategy && (
              <div className="rounded-md border border-primary/20 bg-primary/5 p-3">
                <p className="font-medium text-primary">Estratégia recomendada</p>
                <p className="mt-0.5 text-muted-foreground">{analysis.strategy}</p>
              </div>
            )}
            {analysis.insights && analysis.insights.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Insights</p>
                <ul className="space-y-1">
                  {analysis.insights.map((s, i) => <li key={i} className="text-muted-foreground">• {s}</li>)}
                </ul>
              </div>
            )}
            {analysis.differentiation && analysis.differentiation.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Diferenciais a explorar</p>
                <ul className="space-y-1">
                  {analysis.differentiation.map((s, i) => <li key={i} className="text-muted-foreground">• {s}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
