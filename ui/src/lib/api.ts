export type EndpointStatus = 'active' | 'zombie' | 'shadow' | string

export interface ApiNode {
  id: string
  method: string
  path: string
  status: EndpointStatus
  flow: string
  auth_required: boolean | null
  last_traffic: string | null
  owner: string
  recommendation: string
  data_exposed: string[]
  reachable: boolean
}

export interface ApiEdge {
  source: string
  target: string
  flow: string
}

export interface ApiGraph {
  nodes: ApiNode[]
  edges: ApiEdge[]
}

export interface InventoryItem {
  method: string
  path: string
  classification: EndpointStatus
  reachable: boolean
  status_code: number | null
  last_traffic: string | null
  auth_required: boolean | null
  data_exposed: string[]
  owner: string
  recommendation: string
  roles: string[]
  sources: string[]
}

export interface InventoryResponse {
  items: InventoryItem[]
}

async function getJson<T>(baseUrl: string, path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal,
  })
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail =
      typeof payload === 'object' &&
      payload !== null &&
      'detail' in payload &&
      typeof payload.detail === 'string'
        ? payload.detail
        : `Dashboard API returned HTTP ${response.status}.`
    throw new Error(detail)
  }
  return payload as T
}

export function fetchGraph(baseUrl: string, signal?: AbortSignal) {
  return getJson<ApiGraph>(baseUrl, '/api/graph', signal)
}

export function fetchInventory(baseUrl: string, signal?: AbortSignal) {
  return getJson<InventoryResponse>(baseUrl, '/api/inventory', signal)
}

export function fetchOpenApi(baseUrl: string) {
  return getJson<Record<string, unknown>>(baseUrl, '/api/openapi')
}
