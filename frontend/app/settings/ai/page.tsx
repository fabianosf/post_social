"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Navbar } from "@/components/layout/Navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getAIKeys, saveAIKey, deleteAIKey,
  toggleAIKey, setDefaultAIKey, testAIKey,
} from "@/lib/api";
import { Eye, EyeOff, Trash2, CheckCircle, XCircle, Loader2 } from "lucide-react";

const PROVIDER_COLORS: Record<string, string> = {
  openai:     "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
  gemini:     "bg-blue-500/10 border-blue-500/30 text-blue-400",
  groq:       "bg-orange-500/10 border-orange-500/30 text-orange-400",
  claude:     "bg-amber-500/10 border-amber-500/30 text-amber-400",
  openrouter: "bg-purple-500/10 border-purple-500/30 text-purple-400",
};

const PROVIDER_DOCS: Record<string, string> = {
  openai:     "platform.openai.com/api-keys",
  gemini:     "aistudio.google.com/app/apikey",
  groq:       "console.groq.com/keys",
  claude:     "console.anthropic.com/settings/keys",
  openrouter: "openrouter.ai/keys",
};

type AIKey = {
  provider: string;
  label: string;
  has_key: boolean;
  masked_key: string | null;
  is_active: boolean;
  is_default: boolean;
};

function ProviderCard({ entry, onRefresh }: { entry: AIKey; onRefresh: () => void }) {
  const [editing, setEditing]   = useState(false);
  const [input, setInput]       = useState("");
  const [showKey, setShowKey]   = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [testing, setTesting]   = useState(false);

  const qc = useQueryClient();
  const invalidate = () => { qc.invalidateQueries({ queryKey: ["ai-keys"] }); onRefresh(); };

  const save = useMutation({
    mutationFn: () => saveAIKey(entry.provider, input),
    onSuccess: () => { setEditing(false); setInput(""); invalidate(); },
  });

  const remove = useMutation({
    mutationFn: () => deleteAIKey(entry.provider),
    onSuccess: invalidate,
  });

  const toggle = useMutation({
    mutationFn: () => toggleAIKey(entry.provider),
    onSuccess: invalidate,
  });

  const setDefault = useMutation({
    mutationFn: () => setDefaultAIKey(entry.provider),
    onSuccess: invalidate,
  });

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await testAIKey(entry.provider);
      setTestResult({ ok: true, msg: res.message });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { error?: string } } })?.response?.data?.error ?? "Erro na conexão";
      setTestResult({ ok: false, msg });
    } finally {
      setTesting(false);
    }
  };

  const colorClass = PROVIDER_COLORS[entry.provider] ?? "bg-zinc-800/50 border-zinc-700";

  return (
    <div className={`rounded-xl border p-5 space-y-4 ${colorClass}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-semibold">{entry.label}</span>
          {entry.has_key && entry.is_default && (
            <Badge className="text-xs bg-primary/20 text-primary border-primary/30">Padrão</Badge>
          )}
          {entry.has_key && (
            <Badge variant="outline" className={`text-xs ${entry.is_active ? "text-green-400 border-green-400/40" : "text-zinc-500 border-zinc-600"}`}>
              {entry.is_active ? "Ativa" : "Inativa"}
            </Badge>
          )}
        </div>
        <a
          href={`https://${PROVIDER_DOCS[entry.provider]}`}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          Obter chave ↗
        </a>
      </div>

      {/* Key display */}
      {entry.has_key && !editing && (
        <div className="flex items-center gap-2 bg-black/30 rounded-lg px-3 py-2">
          <code className="flex-1 text-sm font-mono text-zinc-300">
            {showKey ? entry.masked_key : "••••••••••••••••••••"}
          </code>
          <button onClick={() => setShowKey(!showKey)} className="text-zinc-400 hover:text-zinc-200">
            {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        </div>
      )}

      {/* Edit form */}
      {editing && (
        <div className="flex gap-2">
          <Input
            type="password"
            placeholder="Cole sua API key aqui..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="bg-black/40 border-zinc-700 font-mono text-sm"
            autoFocus
          />
          <Button size="sm" onClick={() => save.mutate()} disabled={!input.trim() || save.isPending}>
            {save.isPending ? <Loader2 size={14} className="animate-spin" /> : "Salvar"}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setInput(""); }}>
            Cancelar
          </Button>
        </div>
      )}

      {/* Test result */}
      {testResult && (
        <div className={`flex items-center gap-2 text-sm rounded-lg px-3 py-2 ${testResult.ok ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"}`}>
          {testResult.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
          {testResult.msg}
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" className="border-zinc-700" onClick={() => { setEditing(true); setTestResult(null); }}>
          {entry.has_key ? "Atualizar key" : "+ Adicionar key"}
        </Button>

        {entry.has_key && (
          <>
            <Button
              size="sm" variant="outline" className="border-zinc-700"
              onClick={runTest} disabled={testing}
            >
              {testing ? <Loader2 size={14} className="animate-spin mr-1" /> : null}
              Testar conexão
            </Button>

            <Button
              size="sm" variant="outline" className="border-zinc-700"
              onClick={() => toggle.mutate()} disabled={toggle.isPending}
            >
              {entry.is_active ? "Desativar" : "Ativar"}
            </Button>

            {!entry.is_default && (
              <Button
                size="sm" variant="outline" className="border-zinc-700"
                onClick={() => setDefault.mutate()} disabled={setDefault.isPending}
              >
                Definir padrão
              </Button>
            )}

            <Button
              size="sm" variant="ghost" className="text-red-400 hover:text-red-300 hover:bg-red-500/10 ml-auto"
              onClick={() => remove.mutate()} disabled={remove.isPending}
            >
              <Trash2 size={14} />
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

export default function AISettingsPage() {
  const { data, isLoading, refetch } = useQuery<AIKey[]>({
    queryKey: ["ai-keys"],
    queryFn: getAIKeys,
  });

  return (
    <>
      <Navbar />
      <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-xl font-bold">Configurações de IA</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Conecte suas próprias API keys. As chaves são criptografadas e nunca expostas ao cliente.
          </p>
        </div>

        {isLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}
          </div>
        ) : (
          <div className="space-y-4">
            {(data ?? []).map((entry) => (
              <ProviderCard key={entry.provider} entry={entry} onRefresh={refetch} />
            ))}
          </div>
        )}

        <p className="text-xs text-muted-foreground border-t border-border pt-4">
          🔒 As API keys são criptografadas com AES-256 antes de serem armazenadas. Nem a equipe do Postay consegue visualizar suas chaves.
        </p>
      </div>
    </>
  );
}
