"use client";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { WeekDay, QueuePost } from "@/types/dashboard";
import { cn } from "@/lib/utils";
import Image from "next/image";

const STATUS_BADGE: Record<string, string> = {
  posted:     "bg-accent/10 text-accent border-accent/20",
  pending:    "bg-yellow-400/10 text-yellow-400 border-yellow-400/20",
  processing: "bg-blue-400/10 text-blue-400 border-blue-400/20",
  failed:     "bg-destructive/10 text-destructive border-destructive/20",
};

function PostItem({ post }: { post: QueuePost }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-border bg-secondary/30 p-2">
      {post.thumb_url ? (
        <div className="relative h-9 w-9 shrink-0 overflow-hidden rounded-md">
          <Image src={post.thumb_url} alt="" fill className="object-cover" unoptimized />
        </div>
      ) : (
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-muted text-lg">
          {post.is_video ? "🎬" : "🖼"}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs text-muted-foreground">{post.filename}</p>
        <div className="flex items-center gap-1 mt-0.5">
          {post.time && <span className="text-xs font-medium">{post.time}</span>}
          {post.ig && <span className="text-[10px] text-muted-foreground">IG</span>}
          {post.fb && <span className="text-[10px] text-muted-foreground">FB</span>}
        </div>
      </div>
      <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", STATUS_BADGE[post.status] ?? "")}>
        {post.status}
      </Badge>
    </div>
  );
}

function DayColumn({ day }: { day: WeekDay }) {
  const posts = Array.isArray(day.posts) ? day.posts : [];
  return (
    <div className={cn("flex flex-col gap-2 rounded-xl border p-3 min-w-[140px]",
      day.is_today ? "border-primary bg-primary/5" : "border-border bg-card"
    )}>
      <div className="flex items-center justify-between">
        <div>
          <p className={cn("text-xs font-semibold", day.is_today ? "text-primary" : "text-muted-foreground")}>
            {day.day_name}
          </p>
          <p className="text-[11px] text-muted-foreground">{day.day_short}</p>
        </div>
        {posts.length > 0 && (
          <Badge variant="outline" className="text-[10px] px-1.5">{posts.length}</Badge>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        {posts.length === 0 ? (
          <p className="py-2 text-center text-[11px] text-muted-foreground/60">sem posts</p>
        ) : (
          posts.map((p) => <PostItem key={p.id} post={p} />)
        )}
      </div>
    </div>
  );
}

export function WeekQueue({ data }: { data: WeekDay[] }) {
  const days = Array.isArray(data) ? data : [];
  const totalWeek = days.reduce(
    (s, d) => s + (Array.isArray(d?.posts) ? d.posts.length : 0),
    0
  );

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Próximos 7 dias</h2>
        <span className="text-sm text-muted-foreground">{totalWeek} post{totalWeek !== 1 ? "s" : ""}</span>
      </div>

      {totalWeek === 0 ? (
        <Card className="py-12 text-center">
          <p className="text-2xl">📭</p>
          <p className="mt-2 font-medium">Nenhum post agendado</p>
          <p className="text-sm text-muted-foreground">Adicione posts para a próxima semana</p>
        </Card>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {days.map((day) => <DayColumn key={day.date} day={day} />)}
        </div>
      )}
    </div>
  );
}

export function WeekQueueSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-5 w-32" />
      <div className="flex gap-3">
        {Array.from({ length: 7 }).map((_, i) => (
          <div key={i} className="min-w-[140px] rounded-xl border border-border p-3">
            <Skeleton className="mb-2 h-4 w-16" />
            <Skeleton className="h-12 w-full rounded-lg" />
          </div>
        ))}
      </div>
    </div>
  );
}
