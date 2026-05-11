"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { BarChart2, Zap, Brain, TrendingUp, Settings } from "lucide-react";

const linkClass = (path: string, href: string) =>
  cn(
    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
    path === href || path.startsWith(href + "/")
      ? "bg-primary/10 text-primary font-medium"
      : "text-muted-foreground hover:text-foreground hover:bg-secondary"
  );

export function Navbar() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
      <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <Link href="/dashboard" className="text-xl font-bold text-primary">
          Postay
        </Link>

        <ul className="hidden md:flex items-center gap-1">
          {/* /dashboard é rota Next.js — usa Link */}
          <li>
            <Link href="/dashboard" className={linkClass(path, "/dashboard")}>
              <BarChart2 size={15} />
              Stats
            </Link>
          </li>
          {/* Rotas Flask — usa <a> para forçar navegação completa */}
          <li>
            <a href="/analytics" className={linkClass(path, "/analytics")}>
              <TrendingUp size={15} />
              Analytics
            </a>
          </li>
          <li>
            <a href="/ai" className={linkClass(path, "/ai")}>
              <Brain size={15} />
              IA
            </a>
          </li>
          <li>
            <a href="/growth" className={linkClass(path, "/growth")}>
              <TrendingUp size={15} />
              Crescimento
            </a>
          </li>
          <li>
            <a href="/automacoes" className={linkClass(path, "/automacoes")}>
              <Zap size={15} />
              Automações
            </a>
          </li>
        </ul>

        <div className="flex items-center gap-2">
          <Link href="/settings/ai">
            <Button variant="ghost" size="icon" className="text-muted-foreground" title="Configurações IA">
              <Settings size={18} />
            </Button>
          </Link>
          <a href="/logout">
            <Button variant="outline" size="sm">Sair</Button>
          </a>
        </div>
      </nav>
    </header>
  );
}
