"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Navbar } from "@/components/layout/Navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getAIKeys, saveAIKey, testAIKey, setDefaultAIKey } from "@/lib/api";
import { Eye, EyeOff, CheckCircle2, XCircle, Loader2, Zap } from "lucide-react";

type AIKey = {
  provider: string;
  label: string;
  has_key: boolean;
  masked_key: string | null;
  is_active: boolean;
  is_default: boolean;
  last_validated_at: string | null;
};

const PROVIDERS: { id: string; label: string; placeholder: string; color: string }[] = [
  { id: "openai",     label: "OpenAI",          placeholder: "sk-...",          color: "#10b981" },
  { id: "gemini",     label: "Google Gemini",    placeholder: "AIza...",         color: "#3b82f6" },
  { id: "groq",       label: "Groq",             placeholder: "gsk_...",         color: "#f97316" },
  { id: "claude",     label: "Anthropic Claude", placeholder: "sk-ant-...",      color: "#f59e0b" },
  { id: "openrouter", label: "OpenRouter",       placeholder: "sk-or-...",       color: "#a855f7" },
];

function fmtDate(iso: string | null) {
  if (!iso) return null;
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export default function AISettingsPage() {
  const [selected, setSelected] = useState(PROVIDERS[0].id);
  const [keyInput, setKeyInput]  = useState("");
  const [showKey, setShowKey]    = useState(false);
  const [testMsg, setTestMsg]    = useState<{ ok: boolean; text: string } | null>(null);

  const qc = useQueryClient();
  const { data: keys = [], isLoading } = useQuery<AIKey[]>({ queryKey: ["ai-keys"], queryFn: getAIKeys });

  const current = keys.find((k) => k.provider === selected);
  const providerMeta = PROVIDERS.find((p) => p.id === selected)!;
  const defaultKey = keys.find((k) => k.is_default && k.has_key);

  const invalidate = () => qc.invalidateQueries({ queryKey: ["ai-keys"] });

  const save = useMutation({
    mutationFn: () => saveAIKey(selected, keyInput),
    onSuccess: () => { setKeyInput(""); setTestMsg(null); invalidate(); },
  });

  const test = useMutation({
    mutationFn: () => testAIKey(selected),
    onSuccess: (res) => { setTestMsg({ ok: true, text: res.message }); invalidate(); },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "Erro na conexão";
      setTestMsg({ ok: false, text: msg });
    },
  });

  const setDefault = useMutation({
    mutationFn: () => setDefaultAIKey(selected),
    onSuccess: invalidate,
  });

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-2xl px-4 py-10 space-y-8">

        {/* Header */}
        <div>
          <h1 className="text-2xl font-bold">Configurações de IA</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Conecte sua própria API key. As chaves são criptografadas e nunca expostas.
          </p>
        </div>

        {/* Provider padrão ativo */}
        {defaultKey && (
          <div className="flex items-center gap-2 rounded-lg border border-green-500/30 bg-green-500/5 px-4 py-3">
            <Zap size={15} className="text-green-400 shrink-0" />
            <span className="text-sm text-green-300">
              Provider ativo: <strong>{PROVIDERS.find(p => p.id === defaultKey.provider)?.label}</strong>
            </span>
            <Badge className="ml-auto text-xs bg-green-500/20 text-green-400 border-green-500/30">Padrão</Badge>
          </div>
        )}

        {/* Tab selector */}
        <div className="flex gap-1 flex-wrap">
          {PROVIDERS.map((p) => {
            const k = keys.find((k) => k.provider === p.id);
            const connected = k?.has_key && k?.is_active;
            return (
              <button
                key={p.id}
                onClick={() => { setSelected(p.id); setKeyInput(""); setTestMsg(null); }}
                className={[
                  "flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-all border",
                  selected === p.id
                    ? "bg-primary/10 border-primary/40 text-primary"
                    : "border-border text-muted-foreground hover:text-foreground hover:border-zinc-600",
                ].join(" ")}
              >
                {p.label}
                {connected && <span className="w-1.5 h-1.5 rounded-full bg-green-400" />}
              </button>
            );
          })}
        </div>

        {/* Form */}
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-10 rounded-lg" />
            <Skeleton className="h-10 w-48 rounded-lg" />
          </div>
        ) : (
          <div className="rounded-xl border border-border bg-card p-6 space-y-5">
            {/* Status atual */}
            <div className="flex items-center justify-between">
              <span className="font-semibold">{providerMeta.label}</span>
              {current?.has_key ? (
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={15} className="text-green-400" />
                  <span className="text-sm text-green-400">Conectado</span>
                  {current.last_validated_at && (
                    <span className="text-xs text-muted-foreground">· validado {fmtDate(current.last_validated_at)}</span>
                  )}
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <XCircle size={15} className="text-zinc-500" />
                  <span className="text-sm text-zinc-500">Não configurado</span>
                </div>
              )}
            </div>

            {/* Chave atual mascarada */}
            {current?.has_key && (
              <div className="flex items-center gap-2 rounded-lg bg-black/30 px-3 py-2">
                <code className="flex-1 text-sm font-mono text-zinc-300">
                  {showKey ? current.masked_key : "••••••••••••••••••••••••"}
                </code>
                <button onClick={() => setShowKey(!showKey)} className="text-zinc-400 hover:text-zinc-200 shrink-0">
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            )}

            {/* Input nova key */}
            <div className="space-y-2">
              <label className="text-sm text-muted-foreground">
                {current?.has_key ? "Nova API key (substitui a atual)" : "API key"}
              </label>
              <div className="flex gap-2">
                <Input
                  type="password"
                  placeholder={providerMeta.placeholder}
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  className="font-mono text-sm bg-black/20"
                />
                <Button
                  onClick={() => save.mutate()}
                  disabled={!keyInput.trim() || save.isPending}
                >
                  {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Salvar"}
                </Button>
              </div>
            </div>

            {/* Ações */}
            {current?.has_key && (
              <div className="flex gap-2 flex-wrap">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => { setTestMsg(null); test.mutate(); }}
                  disabled={test.isPending}
                  className="border-zinc-700"
                >
                  {test.isPending ? <Loader2 size={13} className="animate-spin mr-1" /> : null}
                  Testar conexão
                </Button>

                {!current.is_default && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDefault.mutate()}
                    disabled={setDefault.isPending}
                    className="border-zinc-700"
                  >
                    Definir como padrão
                  </Button>
                )}

                {current.is_default && (
                  <Badge className="self-center text-xs bg-primary/10 text-primary border-primary/30">
                    Provider padrão
                  </Badge>
                )}
              </div>
            )}

            {/* Resultado do teste */}
            {testMsg && (
              <div className={[
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm",
                testMsg.ok ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400",
              ].join(" ")}>
                {testMsg.ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {testMsg.text}
              </div>
            )}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          🔒 Chaves criptografadas com AES-256 no servidor. Nem a equipe do Postay consegue visualizá-las.
        </p>
      </div>
    </>
  );
}
