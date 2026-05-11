import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ArrowRight, Zap, BarChart2, Brain, TrendingUp, Clock, Shield } from "lucide-react";

const features = [
  { icon: Clock,      title: "Agendamento Automático", desc: "Posts publicados no horário certo, todo dia, sem você precisar lembrar." },
  { icon: Brain,      title: "IA para Conteúdo",       desc: "Gere legendas, hashtags e roteiros de vídeo em segundos com GPT-4o." },
  { icon: BarChart2,  title: "Analytics Avançado",     desc: "Entenda o que funciona: alcance, engajamento e tendências do seu perfil." },
  { icon: TrendingUp, title: "Growth Score",           desc: "Score de crescimento 0-100 com benchmark real do Instagram 2024." },
  { icon: Zap,        title: "Automações",             desc: "Regras inteligentes que publicam, notificam e adaptam estratégias automaticamente." },
  { icon: Shield,     title: "Multi-plataforma",       desc: "Instagram, Facebook e TikTok em um único painel." },
];

const plans = [
  {
    name: "Free", price: "R$ 0", period: "/mês",
    features: ["1 conta Instagram", "30 posts/mês", "Agendamento automático", "IA para legendas"],
    cta: "Começar grátis", highlight: false,
  },
  {
    name: "Pro", price: "R$ 99", period: "/mês",
    features: ["3 contas Instagram", "Posts ilimitados", "Análise Visual IA", "Growth Analytics", "Automações", "Relatório semanal"],
    cta: "Testar 3 dias grátis", highlight: true,
  },
  {
    name: "Agency", price: "R$ 249", period: "/mês",
    features: ["10 contas Instagram", "Posts ilimitados", "Tudo do Pro", "Suporte prioritário"],
    cta: "Falar com time", highlight: false,
  },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen">
      {/* Navbar */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
        <nav className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
          <span className="text-xl font-bold text-primary">Postay</span>
          <div className="flex items-center gap-3">
            <Link href="/login"><Button variant="ghost" size="sm">Entrar</Button></Link>
            <Link href="/cadastro"><Button size="sm">Começar grátis</Button></Link>
          </div>
        </nav>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-7xl px-4 pt-24 pb-20 text-center">
        <Badge variant="outline" className="mb-6 border-primary/30 text-primary">
          ✨ IA Multimodal + Growth Analytics
        </Badge>
        <h1 className="mx-auto max-w-3xl text-5xl font-bold leading-tight tracking-tight md:text-6xl">
          Publique nas redes sociais{" "}
          <span className="bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
            no piloto automático
          </span>
        </h1>
        <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground">
          Agende posts, gere legendas com IA, analise crescimento e automatize sua presença digital no Instagram, Facebook e TikTok.
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-3">
          <Link href="/cadastro">
            <Button size="lg" className="gap-2">
              Começar grátis — 3 dias Pro <ArrowRight size={16} />
            </Button>
          </Link>
          <Link href="#planos">
            <Button size="lg" variant="outline">Ver planos</Button>
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-7xl px-4 py-20">
        <h2 className="mb-12 text-center text-3xl font-bold">Tudo que você precisa para crescer</h2>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map(({ icon: Icon, title, desc }) => (
            <div key={title} className="rounded-xl border border-border bg-card p-6 transition-colors hover:border-primary/40">
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                <Icon size={20} className="text-primary" />
              </div>
              <h3 className="mb-2 font-semibold">{title}</h3>
              <p className="text-sm text-muted-foreground">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="planos" className="mx-auto max-w-7xl px-4 py-20">
        <h2 className="mb-12 text-center text-3xl font-bold">Planos simples e transparentes</h2>
        <div className="grid gap-6 md:grid-cols-3">
          {plans.map((plan) => (
            <div
              key={plan.name}
              className={`relative rounded-xl border p-8 ${
                plan.highlight ? "border-primary bg-primary/5 ring-1 ring-primary" : "border-border bg-card"
              }`}
            >
              {plan.highlight && (
                <Badge className="absolute -top-3 left-1/2 -translate-x-1/2 bg-primary text-white">
                  Mais popular
                </Badge>
              )}
              <p className="text-sm font-medium text-muted-foreground">{plan.name}</p>
              <div className="mt-2 flex items-baseline gap-1">
                <span className="text-4xl font-bold">{plan.price}</span>
                <span className="text-muted-foreground">{plan.period}</span>
              </div>
              <ul className="mt-6 space-y-3">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-center gap-2 text-sm">
                    <span className="text-accent">✓</span> {f}
                  </li>
                ))}
              </ul>
              <Link href="/cadastro" className="mt-8 block">
                <Button className="w-full" variant={plan.highlight ? "default" : "outline"}>
                  {plan.cta}
                </Button>
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* CTA final */}
      <section className="mx-auto max-w-7xl px-4 py-20 text-center">
        <div className="rounded-2xl border border-primary/20 bg-primary/5 px-8 py-16">
          <h2 className="text-3xl font-bold">Pronto para crescer no automático?</h2>
          <p className="mt-4 text-muted-foreground">Comece grátis hoje. Sem cartão de crédito.</p>
          <Link href="/cadastro" className="mt-8 inline-block">
            <Button size="lg" className="gap-2">Criar conta grátis <ArrowRight size={16} /></Button>
          </Link>
        </div>
      </section>

      <footer className="border-t border-border py-8 text-center text-sm text-muted-foreground">
        © 2026 Postay ·
        <Link href="/termos" className="ml-2 hover:text-foreground">Termos</Link> ·
        <Link href="/privacidade" className="ml-2 hover:text-foreground">Privacidade</Link>
      </footer>
    </main>
  );
}
