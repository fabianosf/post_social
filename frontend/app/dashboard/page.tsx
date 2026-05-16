"use client";
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/layout/Navbar";
import { StatsCards, StatsCardsSkeleton } from "@/components/dashboard/StatsCards";
import { GrowthPulse, GrowthPulseSkeleton } from "@/components/dashboard/GrowthPulse";
import { WeekQueue, WeekQueueSkeleton } from "@/components/dashboard/WeekQueue";
import { getDashboardStats, getWeekSchedule, getGrowthSummary } from "@/lib/api";

declare const fbq: (...args: unknown[]) => void;

function PixelTracker() {
  const params = useSearchParams();
  useEffect(() => {
    const eid = params.get("_fe");
    if (!eid || typeof fbq === "undefined") return;
    fbq("track", "CompleteRegistration", {}, { eventID: eid });
    const url = new URL(window.location.href);
    url.searchParams.delete("_fe");
    window.history.replaceState({}, "", url.toString());
  }, [params]);
  return null;
}

export default function DashboardPage() {
  const stats = useQuery({ queryKey: ["dashboard-stats"], queryFn: getDashboardStats, refetchInterval: 60_000 });
  const week  = useQuery({ queryKey: ["week-schedule"],   queryFn: getWeekSchedule,   refetchInterval: 30_000, refetchOnWindowFocus: true });
  const growth= useQuery({ queryKey: ["growth-summary"],  queryFn: getGrowthSummary,  staleTime: 5 * 60_000 });

  return (
    <>
      <Suspense fallback={null}>
        <PixelTracker />
      </Suspense>
      <Navbar />
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Dashboard</h1>
          <a
            href="/painel"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            + Novo post
          </a>
        </div>

        {stats.isLoading ? (
          <StatsCardsSkeleton />
        ) : stats.error ? (
          <p className="text-sm text-destructive">Erro ao carregar stats.</p>
        ) : (
          <StatsCards data={stats.data} />
        )}

        {growth.isLoading ? (
          <GrowthPulseSkeleton />
        ) : growth.data ? (
          <GrowthPulse data={growth.data} />
        ) : null}

        {week.isLoading ? (
          <WeekQueueSkeleton />
        ) : week.error ? (
          <p className="text-sm text-destructive">Erro ao carregar agenda.</p>
        ) : (
          <WeekQueue data={week.data ?? []} />
        )}
      </div>
    </>
  );
}
