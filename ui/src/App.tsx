import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  fetchGraph,
  fetchInventory,
  fetchOpenApi,
  type ApiGraph,
  type ApiNode,
  type InventoryItem,
} from './lib/api'

const ApiMap = lazy(() => import('./components/ApiMap'))

type Remote<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: T }

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:9000'

const statusStyles: Record<string, string> = {
  active: 'border-teal-400/30 bg-teal-400/10 text-teal-200',
  zombie: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
  shadow: 'border-violet-400/30 bg-violet-400/10 text-violet-200',
}

function formatTraffic(value: string | null): string {
  if (!value) return 'No recorded traffic'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString()
}

function StatePanel({
  state,
  label,
  onRetry,
}: {
  state: Remote<unknown>
  label: string
  onRetry: () => void
}) {
  if (state.status === 'loading') {
    return (
      <div className="flex h-full min-h-40 items-center justify-center gap-3 text-sm text-slate-400">
        <span className="size-2 animate-pulse rounded-full bg-teal-300" />
        Loading {label} from the local API...
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className="flex h-full min-h-40 flex-col items-center justify-center gap-3 px-6 text-center">
        <p className="text-sm font-medium text-rose-200">{label} unavailable</p>
        <p className="max-w-xl text-xs leading-5 text-slate-400">{state.message}</p>
        <button
          className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 transition hover:border-teal-300/50"
          onClick={onRetry}
          type="button"
        >
          Retry
        </button>
      </div>
    )
  }
  return null
}

function PlaceholderPanel({
  title,
  milestone,
  children,
  buttonLabel,
}: {
  title: string
  milestone: string
  children: string
  buttonLabel?: string
}) {
  return (
    <article className="rounded-xl border border-dashed border-slate-800 bg-slate-950/40 p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
        <span className="rounded border border-slate-800 px-2 py-1 text-[9px] font-semibold tracking-[0.14em] text-slate-500">
          PLACEHOLDER | {milestone}
        </span>
      </div>
      <p className="mt-3 text-xs leading-5 text-slate-500">{children}</p>
      <p className="mt-3 text-[10px] uppercase tracking-[0.16em] text-slate-600">
        Not connected | no demo data
      </p>
      {buttonLabel && (
        <button
          className="mt-4 w-full cursor-not-allowed rounded-md border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-500"
          disabled
          type="button"
        >
          {buttonLabel}
        </button>
      )}
    </article>
  )
}

function DetailPanel({
  endpoint,
  onClear,
}: {
  endpoint: ApiNode | null
  onClear: () => void
}) {
  if (!endpoint) {
    return (
      <div className="flex min-h-[440px] flex-col justify-between p-5">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Endpoint detail
          </p>
          <h2 className="mt-3 text-lg font-semibold text-slate-200">
            Select a node
          </h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Choose an endpoint on the topology map to inspect its observed flow
            and inventory metadata.
          </p>
        </div>
        <div className="rounded-lg border border-slate-800/80 bg-slate-950/50 p-3 text-xs leading-5 text-slate-500">
          Node detail is sourced from the M3 knowledge base through the read-only
          dashboard API.
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-[440px] p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
            Selected endpoint
          </p>
          <h2 className="mt-3 break-all font-mono text-sm font-semibold text-slate-100">
            {endpoint.method} {endpoint.path}
          </h2>
        </div>
        <button
          aria-label="Clear endpoint selection"
          className="rounded-md border border-slate-800 px-2 py-1 text-xs text-slate-400 hover:border-slate-600 hover:text-white"
          onClick={onClear}
          type="button"
        >
          Clear
        </button>
      </div>
      <dl className="mt-6 space-y-4">
        <DetailRow label="Classification">
          <span
            className={`rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${
              statusStyles[endpoint.status] ?? 'border-slate-700 text-slate-300'
            }`}
          >
            {endpoint.status}
          </span>
        </DetailRow>
        <DetailRow label="Flow">{endpoint.flow}</DetailRow>
        <DetailRow label="Authentication">
          {endpoint.auth_required === null
            ? 'Not confirmed'
            : endpoint.auth_required
              ? 'Required'
              : 'Not required'}
        </DetailRow>
        <DetailRow label="Last traffic">
          {formatTraffic(endpoint.last_traffic)}
        </DetailRow>
        <DetailRow label="Owner">{endpoint.owner || 'Unassigned'}</DetailRow>
      </dl>
      <div className="mt-6 border-t border-slate-800 pt-5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Recommended action
        </p>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          {endpoint.recommendation || 'No recommendation recorded.'}
        </p>
      </div>
    </div>
  )
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] items-start gap-3">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="break-words text-xs leading-5 text-slate-300">{children}</dd>
    </div>
  )
}

function InventoryTable({ items }: { items: InventoryItem[] }) {
  if (!items.length) {
    return (
      <div className="px-5 py-12 text-center text-sm text-slate-500">
        No inventory endpoints are present in the M3 knowledge base.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-left">
        <thead>
          <tr className="border-b border-slate-800 text-[10px] uppercase tracking-[0.15em] text-slate-500">
            <th className="px-5 py-3 font-medium">Endpoint</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Auth</th>
            <th className="px-4 py-3 font-medium">Last traffic</th>
            <th className="px-4 py-3 font-medium">Owner</th>
            <th className="px-5 py-3 font-medium">Recommendation</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr
              className="border-b border-slate-900 transition hover:bg-white/[0.025]"
              key={`${item.method} ${item.path}`}
            >
              <td className="px-5 py-3 font-mono text-xs text-slate-300">
                <span className="mr-2 text-[10px] text-slate-500">{item.method}</span>
                {item.path}
              </td>
              <td className="px-4 py-3">
                <span
                  className={`rounded border px-2 py-1 text-[9px] font-semibold uppercase tracking-wide ${
                    statusStyles[item.classification] ??
                    'border-slate-700 text-slate-400'
                  }`}
                >
                  {item.classification}
                </span>
              </td>
              <td className="px-4 py-3 text-xs text-slate-400">
                {item.auth_required === null
                  ? 'Unknown'
                  : item.auth_required
                    ? 'Required'
                    : 'No'}
              </td>
              <td className="px-4 py-3 text-xs text-slate-400">
                {formatTraffic(item.last_traffic)}
              </td>
              <td className="px-4 py-3 text-xs text-slate-400">{item.owner}</td>
              <td className="max-w-sm px-5 py-3 text-xs leading-5 text-slate-500">
                {item.recommendation}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function App() {
  const [graph, setGraph] = useState<Remote<ApiGraph>>({ status: 'loading' })
  const [inventory, setInventory] = useState<Remote<InventoryItem[]>>({
    status: 'loading',
  })
  const [selected, setSelected] = useState<ApiNode | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [downloadBusy, setDownloadBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetchGraph(API_BASE_URL, controller.signal)
      .then((data) => setGraph({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setGraph({
            status: 'error',
            message: error instanceof Error ? error.message : 'Dashboard API request failed.',
          })
        }
      })
    fetchInventory(API_BASE_URL, controller.signal)
      .then((data) => setInventory({ status: 'ready', data: data.items }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setInventory({
            status: 'error',
            message: error instanceof Error ? error.message : 'Dashboard API request failed.',
          })
        }
      })
    return () => controller.abort()
  }, [refreshKey])

  const retry = useCallback(() => setRefreshKey((value) => value + 1), [])
  const selectedNode = useMemo(() => {
    if (graph.status !== 'ready' || !selected) return null
    return graph.data.nodes.find((node) => node.id === selected.id) ?? null
  }, [graph, selected])

  const downloadOpenApi = useCallback(async () => {
    setDownloadBusy(true)
    setDownloadError(null)
    try {
      const openapiDocument = await fetchOpenApi(API_BASE_URL)
      const blob = new Blob([JSON.stringify(openapiDocument, null, 2)], {
        type: 'application/json',
      })
      const href = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = href
      anchor.download = 'skyvoyage-openapi.json'
      anchor.click()
      window.setTimeout(() => URL.revokeObjectURL(href), 1000)
    } catch (error) {
      setDownloadError(
        error instanceof Error ? error.message : 'OpenAPI download failed.',
      )
    } finally {
      setDownloadBusy(false)
    }
  }, [])

  const activeCount =
    inventory.status === 'ready'
      ? inventory.data.filter((item) => item.classification === 'active').length
      : null
  const zombieCount =
    inventory.status === 'ready'
      ? inventory.data.filter((item) => item.classification === 'zombie').length
      : null
  const shadowCount =
    inventory.status === 'ready'
      ? inventory.data.filter((item) => item.classification === 'shadow').length
      : null
  const connected = graph.status === 'ready' && inventory.status === 'ready'

  return (
    <main className="mx-auto min-h-screen max-w-[1680px] px-4 pb-10 pt-5 sm:px-6 lg:px-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
        <div className="flex items-center gap-4">
          <div className="grid size-10 place-items-center rounded-lg border border-teal-300/25 bg-teal-300/[0.08] font-mono text-sm font-bold text-teal-200">
            SW
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-wide text-slate-100">
                SKYWARDEN
              </h1>
              <span className="rounded border border-slate-800 px-2 py-0.5 text-[9px] font-semibold tracking-[0.16em] text-slate-500">
                MISSION CONTROL
              </span>
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-500">
              SkyVoyage | local attack surface
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${
              connected
                ? 'border-teal-400/20 bg-teal-400/[0.06] text-teal-200'
                : 'border-amber-400/20 bg-amber-400/[0.06] text-amber-200'
            }`}
          >
            <span
              className={`size-1.5 rounded-full ${
                connected ? 'bg-teal-300' : 'bg-amber-300'
              }`}
            />
            {connected ? 'API connected' : 'Awaiting local API'}
          </span>
          <button
            className="rounded-md border border-slate-700 px-3 py-2 text-xs text-slate-300 transition hover:border-teal-300/50 hover:text-white"
            onClick={retry}
            type="button"
          >
            Refresh data
          </button>
        </div>
      </header>

      <section className="mb-5 grid grid-cols-3 gap-3">
        <MetricCard label="Active endpoints" value={activeCount} tone="teal" />
        <MetricCard label="Zombie endpoints" value={zombieCount} tone="amber" />
        <MetricCard label="Shadow endpoints" value={shadowCount} tone="violet" />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,0.8fr)]">
        <article className="overflow-hidden rounded-xl border border-slate-800 bg-[#0b111a]/90 shadow-[0_20px_70px_rgba(0,0,0,0.2)]">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-teal-300/80">
                Surface topology
              </p>
              <h2 className="mt-1 text-sm font-semibold text-slate-100">
                API endpoint map
              </h2>
            </div>
            <div className="flex flex-wrap items-center gap-3 text-[10px] text-slate-400">
              <Legend color="bg-teal-300" label="Active" />
              <Legend color="bg-amber-300" label="Zombie" />
              <Legend color="bg-violet-300" label="Shadow" />
              <span className="border-l border-slate-800 pl-3 font-mono text-slate-500">
                {graph.status === 'ready' ? `${graph.data.nodes.length} nodes` : '- nodes'}
              </span>
            </div>
          </div>
          <div className="relative h-[380px] sm:h-[480px]">
            {graph.status === 'loading' || graph.status === 'error' ? (
              <StatePanel state={graph} label="Topology" onRetry={retry} />
            ) : graph.data.nodes.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center">
                <div className="mb-3 size-10 rounded-full border border-slate-800 bg-slate-900/80" />
                <p className="text-sm font-medium text-slate-300">
                  No endpoint data available
                </p>
                <p className="mt-2 max-w-md text-xs leading-5 text-slate-500">
                  Generate the M3 inventory from the owned SkyVoyage mock app to
                  populate this map. The UI does not substitute sample nodes.
                </p>
              </div>
            ) : (
              <Suspense
                fallback={
                  <div className="flex h-full items-center justify-center text-sm text-slate-400">
                    Preparing the endpoint map...
                  </div>
                }
              >
                <ApiMap
                  graph={graph.data}
                  onSelect={(node) => setSelected(node)}
                />
              </Suspense>
            )}
          </div>
          <div className="flex items-center justify-between border-t border-slate-800 px-5 py-3 text-[10px] text-slate-500">
            <span>Drag to orbit | scroll to zoom | select a node for details</span>
            <span className="font-mono">MAX 100 NODES</span>
          </div>
        </article>

        <aside className="rounded-xl border border-slate-800 bg-[#0b111a]/90">
          <DetailPanel
            endpoint={selectedNode}
            onClear={() => setSelected(null)}
          />
        </aside>
      </section>

      <section className="mt-5 overflow-hidden rounded-xl border border-slate-800 bg-[#0b111a]/90">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-5 py-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-500">
              M3 knowledge base
            </p>
            <h2 className="mt-1 text-sm font-semibold text-slate-100">
              Endpoint inventory
            </h2>
          </div>
          <div className="flex items-center gap-3">
            {downloadError && (
              <span className="max-w-xs text-right text-xs text-rose-300">
                {downloadError}
              </span>
            )}
            <button
              className="rounded-md border border-teal-300/30 bg-teal-300/[0.08] px-3 py-2 text-xs font-medium text-teal-100 transition hover:border-teal-200/60 hover:bg-teal-300/[0.13] disabled:cursor-wait disabled:opacity-50"
              disabled={downloadBusy}
              onClick={downloadOpenApi}
              type="button"
            >
              {downloadBusy ? 'Preparing...' : 'Download OpenAPI'}
            </button>
          </div>
        </div>
        {inventory.status === 'loading' || inventory.status === 'error' ? (
          <StatePanel
            state={inventory}
            label="Inventory"
            onRetry={retry}
          />
        ) : (
          <InventoryTable items={inventory.data} />
        )}
      </section>

      <section className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <PlaceholderPanel
          title="Agent timeline"
          milestone="M6 EVENTS"
        >
          WebSocket event stream will populate this panel in the later API
          milestone.
        </PlaceholderPanel>
        <PlaceholderPanel
          title="Safety controls"
          milestone="M6 APPROVALS"
        >
          Live gate status, approvals, and kill-switch controls are not connected
          in this read-only slice.
        </PlaceholderPanel>
        <PlaceholderPanel title="Findings" milestone="M4-M6">
          Confirmed findings and retest actions will appear when the reporting
          API is implemented.
        </PlaceholderPanel>
        <PlaceholderPanel
          title="Deploy v3.1"
          milestone="M6"
          buttonLabel="Deploy v3.1 | not connected"
        >
          Demo deployment is not connected yet. No deploy request will be sent
          from this placeholder.
        </PlaceholderPanel>
      </section>

      <footer className="mt-8 flex flex-wrap justify-between gap-2 border-t border-slate-900 pt-4 text-[10px] text-slate-600">
        <span>LOCAL DEMO | SYNTHETIC SKYVOYAGE DATA ONLY</span>
        <span className="font-mono">READ-ONLY DASHBOARD SLICE</span>
      </footer>
    </main>
  )
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string
  value: number | null
  tone: 'teal' | 'amber' | 'violet'
}) {
  const toneColor = {
    teal: 'text-teal-200',
    amber: 'text-amber-200',
    violet: 'text-violet-200',
  }[tone]
  return (
    <div className="rounded-lg border border-slate-800 bg-[#0b111a]/80 px-4 py-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.15em] text-slate-500">
        {label}
      </p>
      <p className={`mt-1 font-mono text-xl font-semibold ${toneColor}`}>
        {value === null ? '-' : value}
      </p>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`size-1.5 rounded-full ${color}`} />
      {label}
    </span>
  )
}

export default App
