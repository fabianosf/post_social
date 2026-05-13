"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Navbar } from "@/components/layout/Navbar";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { CommunityCard, CommunityCardSkeleton } from "@/components/discover/CommunityCard";
import { TrendsPanel } from "@/components/discover/TrendsPanel";
import { CompetitorPanel } from "@/components/discover/CompetitorPanel";
import { detectNiche, getCommunityNiches, getCommunityRecs } from "@/lib/api";
import { Sparkles, Search } from "lucide-react";

const PLATFORMS = ["", "telegram", "reddit", "discord", "whatsapp"];

export default function DiscoverPage() {
  const qc = useQueryClient();

  // Filtros
  const [niche, setNiche]       = useState("");
  const [city, setCity]         = useState("");
  const [platform, setPlatform] = useState("");
  const [search, setSearch]     = useState("");

  // Nicho detectado
  const [detectedNiche, setDetectedNiche] = useState<string | null>(null);

  const niches = useQuery({ queryKey: ["community-niches"], queryFn: getCommunityNiches, staleTime: 3_600_000 });
  const recs   = useQuery({
    queryKey: ["community-recs", niche, city, platform],
    queryFn: () => getCommunityRecs({ niche, city, platform, limit: 30 }),
    staleTime: 60_000,
  });

  const detectMut = useMutation({
    mutationFn: detectNiche,
    onSuccess: (d) => {
      setDetectedNiche(d.niche);
      setNiche(d.niche);
      qc.invalidateQueries({ queryKey: ["community-recs"] });
      qc.invalidateQueries({ queryKey: ["niche-trends"] });
      qc.invalidateQueries({ queryKey: ["competitive-score"] });
    },
  });

  const communities = (recs.data ?? []).filter((c: { name: string }) =>
    !search || c.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {/* Header */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-bold">Discover</h1>
            <p className="text-sm text-muted-foreground">Encontre comunidades, tendências e oportunidades de crescimento</p>
          </div>
          <Button
            className="gap-2"
            onClick={() => detectMut.mutate()}
            disabled={detectMut.isPending}
          >
            <Sparkles size={15} />
            {detectMut.isPending ? "Detectando…" : "Detectar meu nicho"}
          </Button>
        </div>

        {detectedNiche && (
          <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-4 py-2 text-sm">
            <Sparkles size={14} className="text-primary" />
            Nicho detectado: <Badge className="bg-primary/10 text-primary">{detectedNiche}</Badge>
          </div>
        )}

        <Tabs defaultValue="communities">
          <TabsList className="w-full sm:w-auto">
            <TabsTrigger value="communities">Comunidades</TabsTrigger>
            <TabsTrigger value="trends">Tendências</TabsTrigger>
            <TabsTrigger value="competitors">Concorrentes</TabsTrigger>
          </TabsList>

          {/* ── Tab: Comunidades ── */}
          <TabsContent value="communities" className="mt-4 space-y-4">
            {/* Filtros */}
            <div className="flex flex-wrap gap-2">
              <div className="relative flex-1 min-w-40">
                <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Buscar…"
                  className="h-8 pl-7 text-sm"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <select
                className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                value={niche}
                onChange={(e) => setNiche(e.target.value)}
              >
                <option value="">Todos os nichos</option>
                {niches.data?.map((n: { niche: string }) => (
                  <option key={n.niche} value={n.niche}>{n.niche}</option>
                ))}
              </select>
              <select
                className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
              >
                {PLATFORMS.map((p) => (
                  <option key={p} value={p}>{p || "Todas as plataformas"}</option>
                ))}
              </select>
              <Input
                placeholder="Cidade"
                className="h-8 w-32 text-sm"
                value={city}
                onChange={(e) => setCity(e.target.value)}
              />
            </div>

            {/* Lista */}
            {recs.isLoading ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 6 }).map((_, i) => <CommunityCardSkeleton key={i} />)}
              </div>
            ) : communities.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Nenhuma comunidade encontrada.{" "}
                {!niche && "Detecte seu nicho para ver recomendações personalizadas."}
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {communities.map((c: Parameters<typeof CommunityCard>[0]["c"]) => (
                  <CommunityCard key={c.id} c={c} />
                ))}
              </div>
            )}
          </TabsContent>

          {/* ── Tab: Tendências ── */}
          <TabsContent value="trends" className="mt-4">
            <TrendsPanel niche={niche || detectedNiche || undefined} />
          </TabsContent>

          {/* ── Tab: Concorrentes ── */}
          <TabsContent value="competitors" className="mt-4">
            <CompetitorPanel />
          </TabsContent>
        </Tabs>
      </div>
    </>
  );
}
