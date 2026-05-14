"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

function MetaPixelRoutePageView() {
  const pathname = usePathname();
  const skipFirst = useRef(true);
  useEffect(() => {
    if (skipFirst.current) {
      skipFirst.current = false;
      return;
    }
    const w = window as unknown as { fbq?: (...args: unknown[]) => void };
    w.fbq?.("track", "PageView");
  }, [pathname]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
  }));

  return (
    <QueryClientProvider client={qc}>
      <ThemeProvider attribute="class" defaultTheme="dark" forcedTheme="dark">
        <MetaPixelRoutePageView />
        {children}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
