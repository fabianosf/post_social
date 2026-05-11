"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { BarChart2, Zap, Brain, TrendingUp, Settings } from "lucide-react";

const links = [
  { href: "/dashboard",   label: "Stats",         icon: BarChart2 },
  { href: "/analytics",   label: "Analytics",     icon: TrendingUp },
  { href: "/ai",          label: "IA",            icon: Brain },
  { href: "/growth",      label: "Crescimento",   icon: TrendingUp },
  { href: "/automacoes",  label: "Automações",    icon: Zap },
];

export function Navbar() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
      <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        <Link href="/dashboard" className="text-xl font-bold text-primary">
          Postay
        </Link>

        <ul className="hidden md:flex items-center gap-1">
          {links.map(({ href, label, icon: Icon }) => (
            <li key={href}>
              <Link
                href={href}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
                  path.startsWith(href)
                    ? "bg-primary/10 text-primary font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                )}
              >
                <Icon size={15} />
                {label}
              </Link>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2">
          <Link href="/configuracoes">
            <Button variant="ghost" size="icon" className="text-muted-foreground">
              <Settings size={18} />
            </Button>
          </Link>
          <Link href="/logout">
            <Button variant="outline" size="sm">Sair</Button>
          </Link>
        </div>
      </nav>
    </header>
  );
}
