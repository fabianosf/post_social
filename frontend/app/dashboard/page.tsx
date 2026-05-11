"use client";
import { useQuery } from "@tanstack/react-query";
import { Navbar } from "@/components/layout/Navbar";
import { StatsCards, StatsCardsSkeleton } from "@/components/dashboard/StatsCards";
import { GrowthPulse, GrowthPulseSkeleton } from "@/components/dashboard/GrowthPulse";
import { WeekQueue, WeekQueueSkeleton } from "@/components/dashboard/WeekQueue";
import { getDashboardStats, getWeekSchedule, getGrowthSummary } from "@/lib/api";

export default function DashboardPage() {
  const stats = useQuery({ queryKey: ["dashboard-stats"], queryFn: getDashboardStats, refetchInterval: 60_000 });
  const week  = useQuery({ queryKey: ["week-schedule"],   queryFn: getWeekSchedule,   refetchInterval: 120_000 });
  const growth= useQuery({ queryKey: ["growth-summary"],  queryFn: getGrowthSummary,  staleTime: 5 * 60_000 });

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold">Dashboard</h1>
          <a
            href="/painel"
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            + Novo post
          </a>
        </div>

        {/* Stats */}
        {stats.isLoading ? (
          <StatsCardsSkeleton />
        ) : stats.error ? (
          <p className="text-sm text-destructive">Erro ao carregar stats.</p>
        ) : (
          <StatsCards data={stats.data} />
        )}

        {/* Growth Pulse */}
        {growth.isLoading ? (
          <GrowthPulseSkeleton />
        ) : growth.data ? (
          <GrowthPulse data={growth.data} />
        ) : null}

        {/* Week Queue */}
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
